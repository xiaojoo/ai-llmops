#!/usr/bin/env python
"""MemoryProvider 抽象契约测试：ABC 方法签名 + MemoryReadContext 默认值"""
import pytest

from internal.service.memory_provider.base import MemoryProvider, MemoryReadContext


def test_read_context_defaults_empty():
    ctx = MemoryReadContext()
    assert ctx.episodic_memory == ""
    assert ctx.procedural_instructions == ""


def test_provider_abstract_cannot_instantiate():
    with pytest.raises(TypeError):
        MemoryProvider()


def test_provider_requires_all_four_methods():
    """缺一个抽象方法就实例化失败（契约完整性的守卫）"""
    class Partial(MemoryProvider):
        def get_user_profile(self, app_config, app_id, user_id):
            return ""

    with pytest.raises(TypeError):
        Partial()
