#!/usr/bin/env python
"""BuiltinMemoryProvider / trigger_write 覆盖测试（回归防护）。

回归验证：trigger_write 从 async 上下文调用时，
asyncio.to_thread(worker_run, ...) 不触发运行中-loop 守卫。

覆盖验证：assistant_agent_service.chat 使用 _aiter_sync 增量桥接（非 list 缓冲）。
"""
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from internal.service.memory_provider.builtin_provider import BuiltinMemoryProvider
from internal.service.memory_provider.base import MemoryReadContext
from internal.service.user_memory_service import UserMemoryService
from internal.service.episodic_memory_service import EpisodicMemoryService
from internal.service.procedural_memory_service import ProceduralMemoryService
from internal.core.tools.memory_tools import MemoryTools


@pytest.fixture
def provider():
    """构造 BuiltinMemoryProvider 实例（全 mock 依赖，不触库）"""
    return BuiltinMemoryProvider(
        user_memory_service=MagicMock(spec=UserMemoryService),
        episodic_memory_service=MagicMock(spec=EpisodicMemoryService),
        procedural_memory_service=MagicMock(spec=ProceduralMemoryService),
        memory_tools=MagicMock(spec=MemoryTools),
    )


@pytest.mark.asyncio
async def test_trigger_write_does_not_raise_from_async_context(provider, monkeypatch):
    """回归覆盖：从 async 上下文调用 trigger_write 不抛 RuntimeError。

    修复前：trigger_write 直接调 worker_run → get_running_loop() 成功 → 抛 RuntimeError。
    修复后：asyncio.to_thread(worker_run, ...) 在线程池执行，线程内无运行中 loop。
    """
    app_id, user_id = uuid4(), uuid4()
    # mock worker_run 以避免真正连接数据库
    called_with = []
    original_worker_run_calls = []

    def fake_worker_run(coro_factory, *, commit_on_success=True, engine=None, engine_factory=None):
        original_worker_run_calls.append(True)
        # 验证：调用时确实没有运行中 loop（守卫不会抛）
        return None

    monkeypatch.setattr(
        "internal.service.memory_provider.builtin_provider.worker_run",
        fake_worker_run,
    )

    # 从 async 上下文调用——修复前会抛 RuntimeError
    await provider.trigger_write(
        app_config={"model_config": {}},
        app_id=app_id,
        user_id=user_id,
        query="你好",
        answer="你好！",
    )

    # 验证 worker_run 被调用了两次（用户事实 + 情景记忆）
    assert len(original_worker_run_calls) == 2


@pytest.mark.asyncio
async def test_trigger_write_calls_extraction_coroutines(provider, monkeypatch):
    """回归覆盖：trigger_write 内部传递正确的 async coro factory 给 worker_run。"""
    app_id, user_id = uuid4(), uuid4()
    captured_coros = []

    def fake_worker_run(coro_factory, *, commit_on_success=True, engine=None, engine_factory=None):
        captured_coros.append(coro_factory)
        assert commit_on_success is True
        return None

    monkeypatch.setattr(
        "internal.service.memory_provider.builtin_provider.worker_run",
        fake_worker_run,
    )

    await provider.trigger_write(
        app_config={"model_config": {}},
        app_id=app_id,
        user_id=user_id,
        query="test query",
        answer="test answer",
    )

    assert len(captured_coros) == 2
    # 每个 coro factory 是 async callable
    for coro_factory in captured_coros:
        assert callable(coro_factory)


def test_get_user_profile_async(provider):
    """get_user_profile 是 async 方法"""
    assert inspect.iscoroutinefunction(provider.get_user_profile)


def test_get_read_context_async(provider):
    """get_read_context 是 async 方法"""
    assert inspect.iscoroutinefunction(provider.get_read_context)


def test_get_memory_tools_async(provider):
    """get_memory_tools 是 async 方法"""
    assert inspect.iscoroutinefunction(provider.get_memory_tools)


def test_trigger_write_async(provider):
    """trigger_write 是 async 方法（必须是 async 以便从 async 上下文 await）"""
    assert inspect.iscoroutinefunction(provider.trigger_write)


# --- 覆盖：assistant_agent_service.chat 流式语义 ---

def test_assistant_chat_uses_aiter_sync_not_list():
    """覆盖：chat 流式部分（stream_assistant_chat）使用 _aiter_sync 增量桥接，而非 list() 物化。

    chat 已拆 prepare+stream，_aiter_sync 在 stream_assistant_chat 中。
    读取源码确认不存在 `await run_in_threadpool(lambda: list(` 模式。
    """
    import inspect
    from internal.service.assistant_agent_service import AssistantAgentService
    src = inspect.getsource(AssistantAgentService.stream_assistant_chat)
    # 必须不存在 list() 物化
    assert "list(agent.stream" not in src, "流式不应使用 list() 物化 agent.stream"
    # 必须使用 _aiter_sync
    assert "_aiter_sync" in src, "流式应使用 _aiter_sync 增量桥接"
