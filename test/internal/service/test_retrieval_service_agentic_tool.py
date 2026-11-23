#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time   : 2026/08/26
@Author : sunxiaojie
@File   : test_retrieval_service_agentic_tool.py

知识库检索工具（dataset_retrieval）的 Agentic 重检分流测试：
- 默认（agentic_enable=False）走 search_in_datasets 普通检索
- 开启后走 search_agentic 多轮重检，并透传 max_rounds
- 兼容 retrieval_config 里 agentic 字典结构

工具 `_do_search` 改为在桥接 loop 内自建 engine+session（请求 session 跨 loop 不可用），
因此测试通过打桩 `internal.container.create_retrieval_service` 捕获桥接 loop 内创建的本地服务，
断言分流与参数透传发生在本地服务上。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from internal.service.retrieval_service import RetrievalService

DATASET_ID = "11111111-1111-1111-1111-111111111111"


def _build_svc() -> RetrievalService:
    return RetrievalService(
        db=MagicMock(),
        ltp_service=MagicMock(),
        vector_database_service=MagicMock(),
    )


async def _make_tool(monkeypatch, svc: RetrievalService, **kwargs):
    """创建工具并打桩桥接 loop 内的服务工厂（monkeypatch 全测试有效，invoke 时仍生效）；
    返回 (tool, captured)——captured['local_svc'] 在 invoke 后才有值。"""
    captured: dict = {}

    def _fake_retrieval_service(session, redis_client):
        fake = MagicMock()
        fake.search_agentic = AsyncMock(return_value=[])
        fake.search_in_datasets = AsyncMock(return_value=[])
        captured["local_svc"] = fake
        return fake

    def _fake_sessionmaker(engine):
        class _Ctx:
            async def __aenter__(self):
                self.session = MagicMock()
                return self.session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return lambda: _Ctx()

    def _fake_engine(*a, **k):
        engine = MagicMock()
        engine.dispose = AsyncMock()
        return engine

    monkeypatch.setattr("internal.container.create_retrieval_service", _fake_retrieval_service)
    monkeypatch.setattr("package.database.build_engine", _fake_engine)
    monkeypatch.setattr("package.database.build_sessionmaker", _fake_sessionmaker)

    tool = await svc.create_langchain_tool_from_search(
        dataset_ids=[DATASET_ID],
        account_id=MagicMock(),
        **kwargs,
    )
    return tool, captured


class TestAgenticRetrievalTool:
    @pytest.mark.asyncio
    async def test_default_uses_search_in_datasets(self, monkeypatch):
        """默认关闭 Agentic：走普通检索 search_in_datasets"""
        svc = _build_svc()
        tool, captured = await _make_tool(monkeypatch, svc)
        tool.invoke({"query": "测试问题"})
        local = captured["local_svc"]

        local.search_in_datasets.assert_called_once()
        local.search_agentic.assert_not_called()

    @pytest.mark.asyncio
    async def test_agentic_enable_uses_search_agentic(self, monkeypatch):
        """开启 Agentic：走多轮重检 search_agentic，并透传 max_rounds"""
        svc = _build_svc()
        tool, captured = await _make_tool(monkeypatch, svc, agentic_enable=True, max_rounds=3)
        tool.invoke({"query": "测试问题"})
        local = captured["local_svc"]

        local.search_agentic.assert_called_once()
        assert local.search_agentic.call_args.kwargs.get("max_rounds") == 3
        assert local.search_agentic.call_args.kwargs.get("query") == "测试问题"
        local.search_in_datasets.assert_not_called()

    @pytest.mark.asyncio
    async def test_agentic_dict_compat(self, monkeypatch):
        """兼容 retrieval_config 里 agentic 字典结构 {enable, max_rounds}"""
        svc = _build_svc()
        tool, captured = await _make_tool(monkeypatch, svc, agentic={"enable": True, "max_rounds": 2})
        tool.invoke({"query": "测试问题"})
        local = captured["local_svc"]

        local.search_agentic.assert_called_once()
        assert local.search_agentic.call_args.kwargs.get("max_rounds") == 2

    @pytest.mark.asyncio
    async def test_agentic_false_still_plain(self, monkeypatch):
        """显式 agentic_enable=False 仍走普通检索"""
        svc = _build_svc()
        tool, captured = await _make_tool(monkeypatch, svc, agentic_enable=False, max_rounds=3)
        tool.invoke({"query": "测试问题"})
        local = captured["local_svc"]

        local.search_in_datasets.assert_called_once()
        local.search_agentic.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_result_message(self, monkeypatch):
        """检索无结果时返回提示文案"""
        svc = _build_svc()
        tool, captured = await _make_tool(monkeypatch, svc, agentic_enable=True)
        result = tool.invoke({"query": "查不到的内容"})

        assert "没有检索到" in result
