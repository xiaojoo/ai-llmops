#!/usr/bin/env python
"""MemoryProviderResolver 优先级测试：应用覆盖 > 系统默认 > builtin

resolve/get_config 均为 async；provider 经 container 工厂构造（db 为
MagicMock，resolve 只依赖 system_config_service.get_config）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.container import create_memory_provider_resolver
from internal.service.memory_provider import (
    BuiltinMemoryProvider, MemoryProviderResolver, TencentMemoryProvider,
)
from internal.service.memory_provider.resolver import BUILTIN, TENCENT

BASE_CONFIG = {"long_term_memory": {"enable": True}}


def _make_resolver(monkeypatch, system_value="") -> MemoryProviderResolver:
    resolver = create_memory_provider_resolver(MagicMock())

    def _get_config(key: str) -> str:
        return system_value if key == "MEMORY_PROVIDER" else ""

    monkeypatch.setattr(
        resolver.system_config_service, "get_config",
        AsyncMock(side_effect=_get_config),
    )
    return resolver


class TestResolver:
    @pytest.mark.asyncio
    async def test_defaults_to_builtin(self, monkeypatch):
        resolver = _make_resolver(monkeypatch)
        assert isinstance(await resolver.resolve(BASE_CONFIG), BuiltinMemoryProvider)

    @pytest.mark.asyncio
    async def test_system_tencent(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=TENCENT)
        assert isinstance(await resolver.resolve(BASE_CONFIG), TencentMemoryProvider)

    @pytest.mark.asyncio
    async def test_app_override_tencent_beats_system_builtin(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=BUILTIN)
        config = {"long_term_memory": {"enable": True, "provider": TENCENT}}
        assert isinstance(await resolver.resolve(config), TencentMemoryProvider)

    @pytest.mark.asyncio
    async def test_app_default_follows_system(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=TENCENT)
        config = {"long_term_memory": {"enable": True, "provider": "default"}}
        assert isinstance(await resolver.resolve(config), TencentMemoryProvider)

    @pytest.mark.asyncio
    async def test_invalid_system_value_falls_back_to_builtin(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value="unknown")
        assert isinstance(await resolver.resolve(BASE_CONFIG), BuiltinMemoryProvider)

    @pytest.mark.asyncio
    async def test_invalid_app_provider_falls_back_to_system(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=TENCENT)
        config = {"long_term_memory": {"enable": True, "provider": "bad"}}
        assert isinstance(await resolver.resolve(config), TencentMemoryProvider)

    @pytest.mark.asyncio
    async def test_missing_long_term_memory_config(self, monkeypatch):
        resolver = _make_resolver(monkeypatch)
        assert isinstance(await resolver.resolve({}), BuiltinMemoryProvider)
