#!/usr/bin/env python
"""UserMemoryFact 双时间机制模型测试（async 化，db_session 事务内创建，回滚不落库）"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from internal.model import UserMemoryFact


class TestUserMemoryFact:
    @pytest.mark.asyncio
    async def test_create_fact_with_dual_time(self, db_session):
        fact = UserMemoryFact(
            app_id=uuid4(), user_id=uuid4(),
            fact_key="location", fact_value={"city": "北京"},
            source="llm_inferred", trust_score=0.8, confidence=0.9,
            is_implicit=True,
            valid_from=datetime.now(),
            valid_to=None,
            tx_created_at=datetime.now(),
            tx_invalidated_at=None,
        )
        db_session.add(fact)
        await db_session.flush()

        await db_session.refresh(fact)
        assert fact.valid_to is None, "当前有效事实 valid_to 应为 NULL"
        assert fact.tx_invalidated_at is None, "未作废事实 tx_invalidated_at 应为 NULL"
        assert fact.fact_value == {"city": "北京"}

    @pytest.mark.asyncio
    async def test_invalidated_fact_keeps_history(self, db_session):
        now = datetime.now()
        fact = UserMemoryFact(
            app_id=uuid4(), user_id=uuid4(),
            fact_key="location", fact_value={"city": "深圳"},
            source="user_explicit", trust_score=1.0, confidence=1.0,
            is_implicit=False,
            valid_from=now - timedelta(days=30),
            valid_to=now,
            tx_created_at=now - timedelta(days=30),
            tx_invalidated_at=now,
        )
        db_session.add(fact)
        await db_session.flush()
        await db_session.refresh(fact)
        assert fact.valid_to is not None, "失效事实保留历史记录"
