#!/usr/bin/env python
"""消息反馈测试（async）——点赞消息一定加入短期记忆（解除归档）+ 异步滚入长期记忆摘要"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message
from internal.service import ConversationService


class TestUpdateMessageFeedback:
    async def _setup(self, db, is_archived=True):
        user_id = uuid4()
        app_id = uuid4()
        conv = Conversation(
            app_id=app_id, created_by=user_id, updated_by=user_id,
            name="测试会话", invoke_from="debugger", summary="旧摘要",
        )
        db.add(conv)
        await db.flush()
        msg = Message(
            app_id=app_id, conversation_id=conv.id,
            created_by=user_id, updated_by=user_id,
            invoke_from="debugger",
            query="问题", answer="答案",
            status=MessageStatus.NORMAL, is_archived=is_archived, feedback="",
        )
        db.add(msg)
        await db.flush()
        return conv, msg, user_id

    @pytest.mark.asyncio
    async def test_like_unarchives_and_starts_summary_thread(self, db_session, monkeypatch):
        """点赞：已归档消息解除归档回到短期记忆窗口，并异步启动滚动进摘要的线程"""
        from internal.service import conversation_service as cs

        conv, msg, user_id = await self._setup(db_session, is_archived=True)

        started = []

        class FakeThread:
            def __init__(self, target=None, kwargs=None):
                self.target = target
                self.kwargs = kwargs or {}

            def start(self):
                started.append((self.target, self.kwargs))

        monkeypatch.setattr(cs, "Thread", FakeThread)

        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        account = MagicMock(id=user_id)
        await service.update_message_feedback(conv.id, msg.id, "like", account)

        await db_session.refresh(msg)
        assert msg.feedback == "like"
        assert msg.is_archived is False, "点赞消息应解除归档，回到短期记忆窗口"
        # 点赞应异步启动"滚动进长期记忆摘要"的线程
        assert len(started) == 1, "点赞应启动摘要滚动线程"
        assert started[0][1]["conversation_id"] == conv.id
        assert started[0][1]["query"] == "问题"
        assert started[0][1]["answer"] == "答案"

    @pytest.mark.asyncio
    async def test_unlike_keeps_archived_state(self, db_session, monkeypatch):
        """取消点赞（''）：不解除归档，也不触发摘要滚动线程"""
        from internal.service import conversation_service as cs

        conv, msg, user_id = await self._setup(db_session, is_archived=True)

        started = []

        class FakeThread:
            def __init__(self, target=None, kwargs=None):
                self.target = target
                self.kwargs = kwargs or {}

            def start(self):
                started.append((self.target, self.kwargs))

        monkeypatch.setattr(cs, "Thread", FakeThread)

        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        account = MagicMock(id=user_id)
        await service.update_message_feedback(conv.id, msg.id, "", account)

        await db_session.refresh(msg)
        assert msg.feedback == ""
        assert msg.is_archived is True, "取消点赞不应改变归档状态"
        assert len(started) == 0, "取消点赞不应触发摘要滚动线程"
