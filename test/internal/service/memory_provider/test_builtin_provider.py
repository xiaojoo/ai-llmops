#!/usr/bin/env python
"""BuiltinMemoryProvider 测试：四方法委托现有 service，行为与现状一致

provider 经 container 工厂构造（db 为 MagicMock，依赖 service 方法
monkeypatch 为 AsyncMock）；trigger_write 经 asyncio.to_thread(worker_run) 执行，
用 fake_worker_run 捕获两次抽取协程。
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.container import create_builtin_memory_provider
from internal.service.memory_provider import BuiltinMemoryProvider
from internal.service.memory_provider.base import MemoryReadContext


class TestBuiltinMemoryProvider:
    @pytest.mark.asyncio
    async def test_get_user_profile_delegates_to_user_memory_service(self, monkeypatch):
        provider = create_builtin_memory_provider(MagicMock())
        app_id, user_id = uuid4(), uuid4()
        fake_facts = [MagicMock(fact_key="location", fact_value={"city": "北京"},
                                source="user_explicit", confidence=0.9)]
        monkeypatch.setattr(
            provider.user_memory_service, "get_current_facts",
            AsyncMock(return_value=fake_facts),
        )
        profile = await provider.get_user_profile({"model_config": {}}, app_id, user_id)
        assert "location" in profile and "北京" in profile

    @pytest.mark.asyncio
    async def test_get_read_context_episodic_and_procedural(self, monkeypatch):
        provider = create_builtin_memory_provider(MagicMock())
        app_id, user_id = uuid4(), uuid4()
        monkeypatch.setattr(
            provider.episodic_memory_service, "search_episodes",
            AsyncMock(return_value=[MagicMock(content="用户正在准备搬家到北京")]),
        )
        monkeypatch.setattr(
            provider.procedural_memory_service, "get_instructions",
            AsyncMock(return_value="先给结论再给细节"),
        )
        ctx = await provider.get_read_context({"model_config": {}}, app_id, user_id, "搬家")
        assert isinstance(ctx, MemoryReadContext)
        assert "用户正在准备搬家到北京" in ctx.episodic_memory
        assert ctx.procedural_instructions == "先给结论再给细节"

    @pytest.mark.asyncio
    async def test_get_read_context_episodic_failure_keeps_procedural(self, monkeypatch):
        provider = create_builtin_memory_provider(MagicMock())
        app_id, user_id = uuid4(), uuid4()

        def boom(a, u, q, **kw):
            raise RuntimeError("weaviate down")

        monkeypatch.setattr(provider.episodic_memory_service, "search_episodes",
                            AsyncMock(side_effect=boom))
        monkeypatch.setattr(
            provider.procedural_memory_service, "get_instructions",
            AsyncMock(return_value="规则还在"),
        )
        ctx = await provider.get_read_context({"model_config": {}}, app_id, user_id, "q")
        assert ctx.episodic_memory == ""
        assert ctx.procedural_instructions == "规则还在"

    @pytest.mark.asyncio
    async def test_get_memory_tools_returns_four_tools(self):
        provider = create_builtin_memory_provider(MagicMock())
        app_id, user_id = uuid4(), uuid4()
        tools = await provider.get_memory_tools({"model_config": {}}, app_id, user_id)
        assert {t.name for t in tools} == {"search_memory", "write_memory", "update_memory", "forget_memory"}

    @pytest.mark.asyncio
    async def test_trigger_write_spawns_two_extraction_coros(self, monkeypatch):
        """trigger_write 经 to_thread(worker_run) 执行两次抽取协程（用户事实 + 情景记忆）"""
        provider = create_builtin_memory_provider(MagicMock())
        app_id, user_id = uuid4(), uuid4()
        captured = []

        def fake_worker_run(coro_factory, *, commit_on_success=True, engine=None, engine_factory=None):
            captured.append(coro_factory)

        monkeypatch.setattr(
            "internal.service.memory_provider.builtin_provider.worker_run",
            fake_worker_run,
        )

        await provider.trigger_write(app_config={"model_config": {}}, app_id=app_id,
                                     user_id=user_id, query="你好", answer="你好！")

        assert len(captured) == 2
        assert all(callable(c) for c in captured), "每个 coro_factory 应为 async callable"
