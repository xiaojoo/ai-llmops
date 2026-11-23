#!/usr/bin/env python
"""惰性压缩测试（async）——窗口 token 超预算阈值时归档最旧消息并更新滚动摘要"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ConfigDict
from sqlalchemy import select

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message
from internal.service import ConversationService


class BudgetLLM(BaseLanguageModel):
    """token 计数可编程的假 LLM：每条消息计 per_message token"""
    # langchain-core 1.6.0 的 BaseLanguageModel model_config 为 extra='ignore'，
    # 需显式开启 extra='allow' 才能承载 per_message 自定义字段
    model_config = ConfigDict(extra='allow')

    def __init__(self, *args, per_message=100, **kwargs):
        super().__init__(*args, **kwargs)
        self.per_message = per_message

    def get_num_tokens_safe(self, messages):
        return len(messages) * self.per_message

    # langchain BaseLanguageModel 抽象方法：测试不实际调用
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class TestCompactIfNeeded:
    async def _setup_conversation(self, db, rounds=5, feedback_map=None):
        user_id = uuid4()
        app_id = uuid4()
        conv = Conversation(
            app_id=app_id, created_by=user_id, updated_by=user_id,
            name="测试会话", invoke_from="debugger", summary="",
        )
        db.add(conv)
        await db.flush()
        for i in range(rounds):
            db.add(Message(
                app_id=app_id, conversation_id=conv.id,
                created_by=user_id, updated_by=user_id,
                invoke_from="debugger",
                query=f"问题{i}", answer=f"答案{i}",
                status=MessageStatus.NORMAL, is_archived=False,
                feedback=(feedback_map or {}).get(i, ""),
            ))
            await db.flush()
        return conv

    @pytest.mark.asyncio
    async def test_compacts_when_over_budget(self, db_session, monkeypatch):
        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        conv = await self._setup_conversation(db_session, rounds=5)

        # 窗口 5 轮 = 10 条消息 = 1000 token；预算推导 monkeypatch 为 600，阈值 600*0.6=360 → 触发压缩
        monkeypatch.setattr(
            "internal.memory.token_buffer_memory.TokenBufferMemory._derive_max_token_limit",
            lambda self: 600,
        )

        llm = BudgetLLM(context_window=32768, per_message=100)
        fake_summary = AsyncMock(return_value="压缩后的摘要")
        service._summarize = fake_summary

        compressed = await service.compact_if_needed(conv.id, llm)

        assert compressed is True, "窗口 1000 token > 预算600*0.6=360，应触发压缩"
        assert fake_summary.called, "应调用摘要生成"
        archived = (await db_session.scalars(
            select(Message).where(
                Message.conversation_id == conv.id, Message.is_archived.is_(True)
            )
        )).all()
        assert len(archived) >= 1, "应有消息被归档"
        await db_session.refresh(conv)
        assert conv.summary == "压缩后的摘要"

    @pytest.mark.asyncio
    async def test_no_compact_within_budget(self, db_session, monkeypatch):
        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        conv = await self._setup_conversation(db_session, rounds=1)

        monkeypatch.setattr(
            "internal.memory.token_buffer_memory.TokenBufferMemory._derive_max_token_limit",
            lambda self: 600,
        )
        llm = BudgetLLM(context_window=32768, per_message=100)
        fake_summary = AsyncMock(return_value="x")
        service._summarize = fake_summary

        compressed = await service.compact_if_needed(conv.id, llm)

        assert compressed is False, "1 轮 2 条消息 200 token < 360，不应压缩"
        assert not fake_summary.called

    @pytest.mark.asyncio
    async def test_compact_never_archives_liked(self, db_session, monkeypatch):
        """点赞（feedback=like）的消息永不归档，一定留在短期记忆窗口"""
        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        # 第 1 轮（最旧）点赞，窗口 5 轮 = 10 条消息 = 1000 token
        conv = await self._setup_conversation(db_session, rounds=5, feedback_map={0: "like"})

        monkeypatch.setattr(
            "internal.memory.token_buffer_memory.TokenBufferMemory._derive_max_token_limit",
            lambda self: 600,
        )
        llm = BudgetLLM(context_window=32768, per_message=100)
        fake_summary = AsyncMock(return_value="压缩后的摘要")
        service._summarize = fake_summary

        compressed = await service.compact_if_needed(conv.id, llm)

        assert compressed is True, "窗口超预算应触发压缩"
        liked = (await db_session.scalars(
            select(Message).where(
                Message.conversation_id == conv.id, Message.feedback == "like"
            )
        )).one()
        assert liked.is_archived is False, "点赞消息永不归档"
        # 其余消息被归档，摘要正常滚动
        archived = (await db_session.scalars(
            select(Message).where(
                Message.conversation_id == conv.id, Message.is_archived.is_(True)
            )
        )).all()
        assert len(archived) >= 1

    @pytest.mark.asyncio
    async def test_compact_archives_disliked_and_excludes_from_summary(self, db_session, monkeypatch):
        """点踩（feedback=dislike）的消息优先归档离开窗口，且不滚入长期记忆摘要"""
        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        # 第 1 轮（最旧）点踩，窗口 5 轮 = 10 条消息 = 1000 token
        conv = await self._setup_conversation(db_session, rounds=5, feedback_map={0: "dislike"})

        monkeypatch.setattr(
            "internal.memory.token_buffer_memory.TokenBufferMemory._derive_max_token_limit",
            lambda self: 600,
        )
        llm = BudgetLLM(context_window=32768, per_message=100)
        fake_summary = AsyncMock(return_value="摘要")
        service._summarize = fake_summary

        compressed = await service.compact_if_needed(conv.id, llm)

        assert compressed is True
        disliked = (await db_session.scalars(
            select(Message).where(
                Message.conversation_id == conv.id, Message.feedback == "dislike"
            )
        )).one()
        assert disliked.is_archived is True, "点踩消息应被归档离开短期记忆窗口"
        # 滚动进摘要的内容不应包含点踩轮次
        assert fake_summary.await_args is not None, "应调用摘要生成"
        new_lines = fake_summary.await_args.args[1]
        assert "问题0" not in new_lines and "答案0" not in new_lines, "点踩内容不进长期记忆"
