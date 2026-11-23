#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""weaviate delete_memory（按 app_id 清空记忆集合）单元测试：不连真实 Weaviate/DB。"""
from uuid import UUID, uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.weaviate_vector_service import WeaviateVectorService

APP_ID = uuid4()
ACCOUNT_ID = uuid4()


class FakeApp:
    id = APP_ID
    created_by = ACCOUNT_ID


class FakeDB:
    def __init__(self, app):
        self._app = app

    async def get(self, model, pk):
        return self._app


class FakeData:
    def __init__(self):
        self.deleted = []

    def delete_many(self, where=None):
        self.deleted.append(where)
        return None


class FakeCol:
    def __init__(self):
        self.data = FakeData()


class FakeClient:
    def __init__(self):
        self.col = FakeCol()

    @property
    def collections(self):
        return _CollectionsProxy(self.col)


class _CollectionsProxy:
    def __init__(self, col):
        self._col = col

    def get(self, name):
        return self._col


def _make_service(db, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(
        "internal.service.weaviate_vector_service.get_weaviate_client",
        lambda: client,
    )
    svc = WeaviateVectorService(db=db, embeddings_service=None, redis_client=None)
    return svc, client


def test_delete_memory_ok(monkeypatch):
    """合法应用 + 归属当前账号：按 app_id 过滤删除。"""
    svc, client = _make_service(FakeDB(FakeApp()), monkeypatch)
    import asyncio

    asyncio.run(svc.delete_memory("EpisodicMemory", APP_ID, _FakeAccount()))
    # delete_many 被调用且携带 app_id 过滤器（Filter.by_property("app_id").equal(app_id)）
    assert len(client.col.data.deleted) == 1
    assert client.col.data.deleted[0] is not None


class _FakeAccount:
    id = ACCOUNT_ID


def test_delete_memory_orphan_when_app_missing(monkeypatch):
    """应用已不存在（孤儿记忆残留）：允许清理（否则残留数据永远删不掉）。"""
    svc, client = _make_service(FakeDB(None), monkeypatch)
    import asyncio

    asyncio.run(svc.delete_memory("EpisodicMemory", APP_ID, _FakeAccount()))
    assert len(client.col.data.deleted) == 1


def test_delete_memory_legacy_app_with_empty_owner(monkeypatch):
    """应用存在但 created_by 为空（早期旧数据，无归属者）：允许清理。"""

    class LegacyApp(FakeApp):
        created_by = ""

    svc, client = _make_service(FakeDB(LegacyApp()), monkeypatch)
    import asyncio

    asyncio.run(svc.delete_memory("EpisodicMemory", APP_ID, _FakeAccount()))
    assert len(client.col.data.deleted) == 1


def test_delete_memory_forbidden_when_not_owner(monkeypatch):
    """应用存在但属于他人：拒绝删除（防越权）。"""

    class OtherApp(FakeApp):
        created_by = uuid4()

    svc, client = _make_service(FakeDB(OtherApp()), monkeypatch)
    import asyncio

    with pytest.raises(ForbiddenException):
        asyncio.run(svc.delete_memory("EpisodicMemory", APP_ID, _FakeAccount()))
    assert client.col.data.deleted == []
