#!/usr/bin/env python
"""request_context（ContextVar）set/get/reset 语义测试。"""
import asyncio

import pytest

from internal.core.request_context import (
    RequestContext,
    get_request_context,
    reset_request_context,
    set_request_context,
)


def test_get_default_when_unset():
    """未 set 时 get 返回全空字段的默认上下文。"""
    ctx = get_request_context()
    assert ctx.remote_addr is None
    assert ctx.scheme is None
    assert ctx.host is None


def test_get_returns_fresh_instance_when_unset():
    """未 set 时每次 get 都是新实例：修改返回值不污染后续读取（防共享可变默认值）。"""
    ctx = get_request_context()
    ctx.remote_addr = "1.2.3.4"
    assert get_request_context().remote_addr is None


def test_set_get_roundtrip():
    token = set_request_context(RequestContext(remote_addr="1.2.3.4", scheme="https", host="example.com"))
    try:
        ctx = get_request_context()
        assert ctx.remote_addr == "1.2.3.4"
        assert ctx.scheme == "https"
        assert ctx.host == "example.com"
    finally:
        reset_request_context(token)
    # reset 后回到默认
    assert get_request_context().remote_addr is None


def test_nested_reset_restores_previous():
    """嵌套 set/reset：reset 内层 token 后恢复外层上下文。"""
    token_a = set_request_context(RequestContext(remote_addr="a"))
    token_b = set_request_context(RequestContext(remote_addr="b"))
    assert get_request_context().remote_addr == "b"
    reset_request_context(token_b)
    assert get_request_context().remote_addr == "a"
    reset_request_context(token_a)
    assert get_request_context().remote_addr is None


@pytest.mark.asyncio
async def test_contextvar_isolation_between_tasks():
    """ContextVar 语义：并发任务各持自己的上下文，互不干扰。"""

    async def worker(addr: str) -> str | None:
        token = set_request_context(RequestContext(remote_addr=addr))
        await asyncio.sleep(0)
        try:
            return get_request_context().remote_addr
        finally:
            reset_request_context(token)

    results = await asyncio.gather(worker("a"), worker("b"))
    assert results == ["a", "b"]
