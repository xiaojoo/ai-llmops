#!/usr/bin/env python
"""TencentMemoryProvider 测试：配置缺失/客户端不可用回退、假客户端读写调用、session 映射、
测试连通 overrides、写侧 worker 独立 session 执行

provider 经 container 工厂构造（db 为 MagicMock），get_config 为 AsyncMock，
方法全 await；trigger_write 经 asyncio.to_thread(worker_run) 在子线程新 loop +
独立 session 里读配置并执行同步 SDK 写入（配置服务以 worker session 重建）。
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.container import create_tencent_memory_provider
from internal.service.memory_provider import TencentMemoryProvider
from internal.service.memory_provider.base import MemoryReadContext
from internal.service.memory_provider.tencent_provider import (
    API_KEY_KEY, ENDPOINT_KEY, SERVICE_ID_KEY,
)


class FakeClient:
    """假腾讯记忆客户端：不依赖真实 SDK"""
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.recalled = []
        self.written = []

    def recall(self, query, top_k=5):
        self.recalled.append((query, top_k))
        return [
            {"type": "core", "content": "用户喜欢简洁回复", "score": 0.9},
            {"type": "scene", "content": "用户准备搬家到北京", "score": 0.8},
        ]

    def write_round(self, query, answer):
        self.written.append((query, answer))


def _make_provider(monkeypatch, *, client=None, configs=None) -> TencentMemoryProvider:
    provider = create_tencent_memory_provider(MagicMock())

    def _get_config(key: str) -> str:
        return (configs or {}).get(key, "")

    monkeypatch.setattr(
        provider.system_config_service, "get_config",
        AsyncMock(side_effect=_get_config),
    )
    if client is not None:
        monkeypatch.setattr(
            provider, "_build_client",
            AsyncMock(return_value=client),
        )
    return provider


class TestTencentMemoryProvider:
    @pytest.mark.asyncio
    async def test_client_unavailable_falls_back_empty(self, monkeypatch):
        """_build_client 返回 None（SDK 缺失/配置不全）时：空上下文/空画像/空工具"""
        provider = _make_provider(monkeypatch)
        monkeypatch.setattr(provider, "_build_client", AsyncMock(return_value=None))
        app_id, user_id = uuid4(), uuid4()
        ctx = await provider.get_read_context({"model_config": {}}, app_id, user_id, "q")
        assert isinstance(ctx, MemoryReadContext)
        assert ctx.episodic_memory == ""
        assert await provider.get_user_profile({"model_config": {}}, app_id, user_id) == ""
        assert await provider.get_memory_tools({"model_config": {}}, app_id, user_id) == []

    @pytest.mark.asyncio
    async def test_read_context_renders_core_and_scene(self, monkeypatch):
        provider = _make_provider(monkeypatch, client=FakeClient())
        app_id, user_id = uuid4(), uuid4()
        fake = provider._build_client.return_value
        ctx = await provider.get_read_context({"model_config": {}}, app_id, user_id, "搬家")
        assert "用户准备搬家到北京" in ctx.episodic_memory
        assert "用户喜欢简洁回复" in ctx.procedural_instructions
        assert fake.recalled[-1][0] == "搬家"

    @pytest.mark.asyncio
    async def test_user_profile_from_core_memory(self, monkeypatch):
        provider = _make_provider(monkeypatch, client=FakeClient())
        profile = await provider.get_user_profile({"model_config": {}}, uuid4(), uuid4())
        assert "用户喜欢简洁回复" in profile

    @pytest.mark.asyncio
    async def test_build_client_reads_config_and_maps_session(self, monkeypatch):
        provider = _make_provider(monkeypatch, configs={
            ENDPOINT_KEY: "http://127.0.0.1:8420",
            API_KEY_KEY: "sk-test",
            SERVICE_ID_KEY: "mem-1",
        })
        built = {}

        class FakeSdkClient:
            def __init__(self, endpoint, api_key, service_id, *, session_id="default",
                         team_id=None, agent_id=None, user_id=None):
                built["endpoint"] = endpoint
                built["api_key"] = api_key
                built["service_id"] = service_id
                built["session_id"] = session_id

        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SdkTencentMemoryClient",
            FakeSdkClient,
        )
        app_id, user_id = uuid4(), uuid4()
        client = await provider._build_client({"model_config": {}}, app_id, user_id)
        assert client is not None
        assert built["endpoint"] == "http://127.0.0.1:8420"
        assert built["api_key"] == "sk-test"
        assert built["service_id"] == "mem-1"
        assert built["session_id"] == f"{app_id}:{user_id}"

    @pytest.mark.asyncio
    async def test_build_client_missing_config_returns_none(self, monkeypatch):
        provider = _make_provider(monkeypatch)
        assert await provider._build_client({"model_config": {}}, uuid4(), uuid4()) is None

    @pytest.mark.asyncio
    async def test_trigger_write_writes_round_in_worker_session(self, monkeypatch):
        """trigger_write：worker 线程独立 session 读配置并 write_round（回归防护）。

        修复史（两个已踩过的坑，均不得回归）：
        a) 修复前 trigger_write 在 worker 子线程里用请求 loop 的 system_config_service
           读配置 → 跨 loop RuntimeError，写侧从未到达 MemoryCore（面板无 L0）；
        b) 中间版在请求 loop 的后台任务里读请求共享 session → asyncpg
           "cannot use Connection.transaction() in a manually started transaction"，
           毒化池连接，后续请求随机报"数据库操作失败"。
        正确形态：worker_run + engine_factory=build_engine 独立 session，
           配置读取绑定 worker session（SystemConfigService(db=session)）。
        """
        provider = _make_provider(monkeypatch)
        calls = []

        class FakeSdk:
            def __init__(self, **kwargs):
                calls.append(("init", kwargs))

            def write_round(self, query, answer):
                calls.append(("write", query, answer))

        class FakeCfgService:
            """替代 SystemConfigService：绑定 worker session（dummy），返回测试配置"""

            def __init__(self, db):
                self.db = db

            async def get_config(self, key: str) -> str:
                return {
                    ENDPOINT_KEY: "http://127.0.0.1:8420",
                    API_KEY_KEY: "sk-test",
                    SERVICE_ID_KEY: "mem-1",
                }.get(key, "")

        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SdkTencentMemoryClient",
            FakeSdk,
        )
        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SystemConfigService",
            FakeCfgService,
        )

        captured = []

        def fake_worker_run(coro_factory, *, commit_on_success=True, engine=None, engine_factory=None):
            import asyncio
            captured.append(coro_factory)
            asyncio.run(coro_factory(MagicMock()))  # session 为 dummy，由 FakeCfgService 消费

        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.worker_run",
            fake_worker_run,
        )
        app_id, user_id = uuid4(), uuid4()
        await provider.trigger_write(app_config={"model_config": {}}, app_id=app_id,
                                     user_id=user_id, query="你好", answer="你好！")
        assert len(captured) == 1
        assert calls and calls[0][0] == "init"
        assert calls[0][1]["session_id"] == f"{app_id}:{user_id}"
        assert ("write", "你好", "你好！") in calls

    @pytest.mark.asyncio
    async def test_trigger_write_skips_when_config_missing(self, monkeypatch):
        """配置不全时 trigger_write 在 worker 内解析后跳过（不构造 SDK、不写）"""
        provider = _make_provider(monkeypatch)

        class FakeCfgService:
            def __init__(self, db):
                self.db = db

            async def get_config(self, key: str) -> str:
                return ""

        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SystemConfigService",
            FakeCfgService,
        )
        called = []
        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SdkTencentMemoryClient",
            lambda **kwargs: called.append(kwargs),
        )

        def fake_worker_run(coro_factory, *, commit_on_success=True, engine=None, engine_factory=None):
            import asyncio
            asyncio.run(coro_factory(MagicMock()))

        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.worker_run",
            fake_worker_run,
        )
        await provider.trigger_write(app_config={"model_config": {}}, app_id=uuid4(),
                                     user_id=uuid4(), query="q", answer="a")
        assert called == []

    # ---- 测试连通 overrides：请求携带的连接配置（非空）覆盖已保存配置 ----

    @staticmethod
    def _install_fake_sdk(monkeypatch) -> dict:
        """把 SdkTencentMemoryClient 换成捕获构造参数的 FakeSdkClient，返回捕获桶"""
        built = {}

        class FakeSdkClient:
            def __init__(self, endpoint, api_key, service_id, *, session_id="default",
                         team_id=None, agent_id=None, user_id=None):
                built["endpoint"] = endpoint
                built["api_key"] = api_key
                built["service_id"] = service_id
                built["session_id"] = session_id

        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SdkTencentMemoryClient",
            FakeSdkClient,
        )
        return built

    @pytest.mark.asyncio
    async def test_build_client_overrides_beat_saved_config(self, monkeypatch):
        """请求 overrides 全非空时完全覆盖已保存配置"""
        provider = _make_provider(monkeypatch, configs={
            ENDPOINT_KEY: "http://saved:8420",
            API_KEY_KEY: "sk-saved",
            SERVICE_ID_KEY: "mem-saved",
        })
        built = self._install_fake_sdk(monkeypatch)
        overrides = {
            "endpoint": "http://override:8420",
            "api_key": "sk-override",
            "service_id": "mem-override",
        }
        client = await provider._build_client({"model_config": {}}, uuid4(), uuid4(),
                                              overrides=overrides)
        assert client is not None
        assert built["endpoint"] == "http://override:8420"
        assert built["api_key"] == "sk-override"
        assert built["service_id"] == "mem-override"

    @pytest.mark.asyncio
    async def test_build_client_overrides_partial_fallback(self, monkeypatch):
        """overrides 只给部分字段时：给出者用请求值，其余回退已保存配置"""
        provider = _make_provider(monkeypatch, configs={
            ENDPOINT_KEY: "http://saved:8420",
            API_KEY_KEY: "sk-saved",
            SERVICE_ID_KEY: "mem-saved",
        })
        built = self._install_fake_sdk(monkeypatch)
        client = await provider._build_client({"model_config": {}}, uuid4(), uuid4(),
                                              overrides={"service_id": "mem-request"})
        assert client is not None
        assert built["endpoint"] == "http://saved:8420"
        assert built["api_key"] == "sk-saved"
        assert built["service_id"] == "mem-request"

    @pytest.mark.asyncio
    async def test_build_client_overrides_fill_missing_config(self, monkeypatch):
        """系统配置全空但请求带全三件时也能构建客户端（保存前可测）"""
        provider = _make_provider(monkeypatch)
        built = self._install_fake_sdk(monkeypatch)
        overrides = {
            "endpoint": "http://127.0.0.1:8420",
            "api_key": "sk-request",
            "service_id": "default",
        }
        client = await provider._build_client({"model_config": {}}, uuid4(), uuid4(),
                                              overrides=overrides)
        assert client is not None
        assert built["endpoint"] == "http://127.0.0.1:8420"
        assert built["api_key"] == "sk-request"
        assert built["service_id"] == "default"

    @pytest.mark.asyncio
    async def test_connection_forwards_overrides_and_succeeds(self, monkeypatch):
        """test_connection 把 overrides 透传给 _build_client；探活成功返回 (True, ...)"""
        provider = _make_provider(monkeypatch)
        build_spy = AsyncMock(return_value=FakeClient())
        monkeypatch.setattr(provider, "_build_client", build_spy)
        overrides = {
            "endpoint": "http://127.0.0.1:8420",
            "api_key": "sk-request",
            "service_id": "default",
        }
        ok, message = await provider.test_connection(
            {"model_config": {}}, uuid4(), uuid4(), overrides=overrides,
        )
        assert ok is True
        assert "连接正常" in message
        assert build_spy.await_args.kwargs["overrides"] == overrides

    @pytest.mark.asyncio
    async def test_connection_missing_without_overrides_reports_keys(self, monkeypatch):
        """无任何配置且无 overrides：报出缺少的配置键（诊断不误报）"""
        provider = _make_provider(monkeypatch)
        ok, message = await provider.test_connection({"model_config": {}}, uuid4(), uuid4())
        assert ok is False
        assert "endpoint" in message and "api_key" in message and "service_id" in message
