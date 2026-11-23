#!/usr/bin/env python
"""请求上下文（ContextVar）：替代 flask.request。

由 FastAPI 依赖写入；服务层读取统一走 get_request_context()。
"""
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class RequestContext:
    """请求上下文：服务层可读的请求级信息（remote_addr/scheme/host）。"""

    remote_addr: str | None = None
    scheme: str | None = None
    host: str | None = None


# 未 set 时返回全新默认实例（每次 get 独立，避免共享可变默认值）
_context: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def get_request_context() -> RequestContext:
    """获取当前请求上下文；未设置时返回全空默认实例。"""
    ctx = _context.get()
    return ctx if ctx is not None else RequestContext()


def set_request_context(ctx: RequestContext) -> Token[RequestContext | None]:
    """写入当前请求上下文，返回 ContextVar token 供 reset 使用。"""
    return _context.set(ctx)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    """按 token 恢复上一请求上下文（嵌套 set/reset 安全）。"""
    _context.reset(token)
