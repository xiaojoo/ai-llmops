#!/usr/bin/env python
"""ProceduralMemory 程序记忆模型测试（async 化，db_session 事务内创建，回滚不落库）"""
from uuid import uuid4

import pytest

from internal.model import ProceduralMemory


class TestProceduralMemory:
    @pytest.mark.asyncio
    async def test_create_instruction(self, db_session):
        record = ProceduralMemory(
            app_id=uuid4(), user_id=uuid4(),
            content="回答用户时先给结论再给细节",
            source="reflection", trust_score=0.6, version=1,
        )
        db_session.add(record)
        await db_session.flush()
        await db_session.refresh(record)
        assert record.version == 1
        assert record.is_deleted is False
