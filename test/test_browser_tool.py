#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""browser 工具（进程级单例 worker）行为测试：不启动真实浏览器，只验证调度/退避/回收逻辑。"""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

import importlib

import browser_use

# __init__.py 的 `from .browser import browser` 把子模块名覆盖成了工具函数，
# `import ... as` 会取到被覆盖的属性，必须经 importlib 从 sys.modules 取真实模块
browser_mod = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.browser.browser"
)


@pytest.fixture
def worker(monkeypatch):
    """独立 _BrowserWorker 实例，_run_impl 替换为假实现（不触碰 browser_use/浏览器）。"""
    w = browser_mod._BrowserWorker()
    monkeypatch.setattr(browser_mod, "_worker", w)
    state = {"calls": 0, "created": 0}

    async def fake_run(task):
        state["calls"] += 1
        if w._session is None:
            state["created"] += 1
            w._session = object()  # 哨兵 session，验证"只创建一次"
        return f"ok:{task}"

    monkeypatch.setattr(w, "_run_impl", fake_run)
    yield w, state
    w.shutdown()


def test_reuses_single_session_across_calls(worker):
    """连续成功调用复用同一个 session（同一进程只创建一个浏览器）。"""
    w, state = worker
    assert w.run("a").startswith("ok:")
    assert w.run("b").startswith("ok:")
    assert state["calls"] == 2
    assert state["created"] == 1  # 关键：多次调用只创建一次会话


def test_backoff_after_failure(worker, monkeypatch):
    """失败后进入退避窗口：窗口内调用直接拒绝，不再执行浏览器任务。"""
    w, state = worker
    monkeypatch.setattr(browser_mod, "_BACKOFF", 60)

    async def failing(task):
        state["calls"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(w, "_run_impl", failing)
    assert "[错误]" in w.run("x")
    assert w._session is None  # 失败后会话被丢弃
    assert "[退避]" in w.run("x")  # 窗口内直接拒绝
    assert state["calls"] == 1  # 拒绝调用未执行浏览器任务


def test_outer_timeout_drops_session_and_backs_off(worker, monkeypatch):
    """外层超时（fut 未在时限内返回）后：放弃执行、丢弃会话、进入退避。"""
    w, state = worker
    monkeypatch.setattr(browser_mod, "_TIMEOUT", 1)
    monkeypatch.setattr(browser_mod, "_BACKOFF", 60)

    async def slow(task):
        state["calls"] += 1
        w._session = object()
        await asyncio.sleep(30)  # 模拟卡死，run() 外层时限 1+10=11s 先触发

    monkeypatch.setattr(w, "_run_impl", slow)
    result = w.run("x")
    assert "[超时]" in result
    assert w._session is None  # 卡死会话被回收
    assert "[退避]" in w.run("x")


def test_idle_reap_closes_session(worker):
    """空闲超过 _IDLE_TTL：回收器关闭会话（任务结束后浏览器不常驻）。"""
    w, state = worker
    assert w.run("a").startswith("ok:")
    assert w._session is not None
    w._last_used = time.time() - browser_mod._IDLE_TTL - 10  # 拨老时间戳模拟空闲
    w._reap_once()
    assert w._session is None  # 空闲会话已被强制关闭


def test_browser_requires_explicit_domain_allowlist(monkeypatch):
    monkeypatch.delenv("BROWSER_ALLOWED_DOMAINS", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    monkeypatch.setattr(browser_use, "ChatOpenAI", MagicMock())
    browser = MagicMock()
    monkeypatch.setattr(browser_use, "Browser", browser)
    w = browser_mod._BrowserWorker()
    with pytest.raises(RuntimeError, match="BROWSER_ALLOWED_DOMAINS"):
        asyncio.run(w._run_impl("open example.com"))
    browser.assert_not_called()


def test_drop_session_waits_for_async_browser_kill():
    w = browser_mod._BrowserWorker()
    w._ensure_running()
    killed = asyncio.Event()

    class Session:
        user_data_dir = None

        async def kill(self):
            killed.set()

    w._session = Session()
    try:
        w._drop_session()
        assert killed.is_set()
        assert w._session is None
    finally:
        w.shutdown()


def test_retry_after_backoff_window(worker, monkeypatch):
    """退避窗口过后可再次执行（恢复服务，而非永久禁用）。"""
    w, state = worker
    monkeypatch.setattr(browser_mod, "_BACKOFF", 1)

    async def failing(task):
        state["calls"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(w, "_run_impl", failing)
    assert "[错误]" in w.run("x")
    assert "[退避]" in w.run("x")
    time.sleep(1.2)  # 越过 1s 退避窗口
    assert "[错误]" in w.run("x")  # 再次执行（仍失败但未被退避拦截）
    assert state["calls"] == 2
