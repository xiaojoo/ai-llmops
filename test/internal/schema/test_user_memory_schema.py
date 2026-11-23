#!/usr/bin/env python
"""用户事实响应 schema Pydantic 化测试：status 状态标记（生效中/已失效/未生效）"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from internal.schema.user_memory_schema import UserMemoryFactResp


def _mock_fact(valid_from, valid_to):
    return MagicMock(
        fact_key="notice:test", fact_value={"title": "通告"},
        source="system", trust_score=1.0, confidence=1.0,
        is_implicit=False,
        valid_from=valid_from, valid_to=valid_to,
        tx_created_at=valid_from, tx_invalidated_at=None,
    )


def _dump(obj):
    return UserMemoryFactResp.model_validate(obj).model_dump(mode="json")


class TestUserMemoryFactRespStatus:
    def test_active_when_within_valid_range(self):
        """生效中：valid_from <= now < valid_to"""
        now = datetime.now()
        data = _dump(_mock_fact(
            now - timedelta(days=1), now + timedelta(days=1),
        ))
        assert data["status"] == "active"

    def test_active_when_no_valid_to(self):
        """长期有效（valid_to=None）：生效中"""
        now = datetime.now()
        data = _dump(_mock_fact(
            now - timedelta(days=1), None,
        ))
        assert data["status"] == "active"

    def test_expired_when_valid_to_passed(self):
        """已失效：valid_to 已过"""
        now = datetime.now()
        data = _dump(_mock_fact(
            now - timedelta(days=30), now - timedelta(days=1),
        ))
        assert data["status"] == "expired"

    def test_upcoming_when_valid_from_future(self):
        """未生效：valid_from 未到"""
        now = datetime.now()
        data = _dump(_mock_fact(
            now + timedelta(days=1), now + timedelta(days=30),
        ))
        assert data["status"] == "upcoming"
