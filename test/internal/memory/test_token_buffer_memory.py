#!/usr/bin/env python
"""TokenBufferMemory 窗口互斥测试（async）——归档消息不进入短期记忆窗口"""
from uuid import uuid4

import pytest

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.entity.conversation_entity import MessageStatus
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Conversation, Message


class WindowLLM(BaseLanguageModel):
    def get_num_tokens(self, text: str) -> int:
        return len(text.encode("utf-8"))

    # langchain BaseLanguageModel 抽象方法：测试不实际调用
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class TestTokenBufferMemoryWindow:
    @pytest.mark.asyncio
    async def test_archived_messages_excluded(self, db_session):
        llm = WindowLLM(context_window=32768)
        user_id = uuid4()
        app_id = uuid4()

        conv = Conversation(
            app_id=app_id, created_by=user_id, updated_by=user_id,
            name="测试会话", invoke_from="debugger",
        )
        db_session.add(conv)
        await db_session.flush()

        # 3 轮消息：第 1 轮归档，第 2、3 轮未归档
        for i, archived in enumerate([True, False, False]):
            msg = Message(
                app_id=app_id, conversation_id=conv.id,
                created_by=user_id, updated_by=user_id,
                invoke_from="debugger",
                query=f"问题{i}", answer=f"答案{i}",
                status=MessageStatus.NORMAL, is_archived=archived,
            )
            db_session.add(msg)
            await db_session.flush()

        memory = TokenBufferMemory(db=db_session, conversation=conv, model_instance=llm)
        history = await memory.get_history_prompt_messages(message_limit=10)

        texts = [m.content for m in history]
        assert "问题0" not in texts, "归档消息不应进入窗口"
        assert "问题1" in texts and "问题2" in texts
