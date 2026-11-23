#!/usr/bin/env python
"""反馈反思改写测试：dislike 触发程序记忆更新

ReflectionService 经 container 工厂构造（真实 db_session），
load_default_language_model 为 AsyncMock，reflect_on_feedback 为 async（kwargs 版）。
"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from internal.container import create_reflection_service
from internal.model import ProceduralMemory


class FakeReflectLLM:
    temperature = 0.0

    def __init__(self, reply):
        self.reply = reply

    def invoke(self, inputs):
        """Runnable 协议：prompt | llm | StrOutputParser 链的 invoke 路径"""
        return self.reply

    def __call__(self, inputs):
        return self.reply


class TestReflection:
    @pytest.mark.asyncio
    async def test_dislike_reflection_writes_instruction(self, db_session, monkeypatch):
        service = create_reflection_service(db_session)
        app_id, user_id = uuid4(), uuid4()

        raw = (
            '```json\n{"instruction": "回答用户时应先给结论，再展开细节，'
            '避免冗长铺垫"}\n```'
        )
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            AsyncMock(return_value=FakeReflectLLM(raw)),
        )

        await service.reflect_on_feedback(
            app_id=app_id, user_id=user_id,
            query="请帮我分析这份报告",
            answer="（一段很长的铺垫后给出结论）",
            feedback="dislike",
        )

        stmt = select(ProceduralMemory).where(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        )
        records = (await db_session.execute(stmt)).scalars().all()
        assert len(records) == 1
        assert "先给结论" in records[0].content

    @pytest.mark.asyncio
    async def test_like_does_not_reflect(self, db_session, monkeypatch):
        service = create_reflection_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        fake_llm = FakeReflectLLM("{}")
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            AsyncMock(return_value=fake_llm),
        )

        await service.reflect_on_feedback(
            app_id=app_id, user_id=user_id,
            query="谢谢", answer="不客气", feedback="like",
        )

        stmt = select(ProceduralMemory).where(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        )
        records = (await db_session.execute(stmt)).scalars().all()
        assert len(records) == 0, "like 不应触发规则改写"
