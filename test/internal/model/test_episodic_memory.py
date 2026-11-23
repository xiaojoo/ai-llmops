#!/usr/bin/env python
"""EpisodicMemory 情景记忆模型测试（async 化，db_session 事务内创建，回滚不落库）"""
from datetime import datetime
from uuid import uuid4

import pytest

from internal.model import EpisodicMemory


class TestEpisodicMemory:
    @pytest.mark.asyncio
    async def test_create_episode(self, db_session):
        episode = EpisodicMemory(
            app_id=uuid4(), user_id=uuid4(),
            content="用户询问北京天气，Agent 推荐了周末行程并调用地图工具规划路线",
            importance=0.8, source="llm_inferred", trust_score=0.5,
            expires_at=None,
        )
        db_session.add(episode)
        await db_session.flush()
        await db_session.refresh(episode)
        assert episode.importance == 0.8
        assert episode.is_deleted is False
        assert episode.embedding_id == "", "未入库向量时 embedding_id 为空串"
