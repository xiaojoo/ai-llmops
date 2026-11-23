#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
lifespan-aware 测试设施。

- 兼容旧行为：app.http.app 导入链曾触发 dotenv.load_dotenv() 把 .env 写入 os.environ，
  服务层仍有 os.getenv 读取点（如 LLM API key）——此处显式加载，保持测试环境一致。
- _engine/_factory 模块级创建一次（避免每测试重建引擎；engine 创建是惰性的，
  不连接 DB，直到首次使用）。
- db_session：connection + begin + rollback 隔离（沿用旧 conftest 语义，真实 Postgres）。
- 新增 client（httpx.AsyncClient + ASGITransport）和 auth_headers fixture。
- 新增 live_server / live_client（uvicorn 真实 TCP，触发 lifespan）。
"""
import asyncio
import socket
import threading

import dotenv

dotenv.load_dotenv()

import pytest
import pytest_asyncio
import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model import Account
from internal.service import JwtService
from package.database import build_engine, build_sessionmaker, set_default_session_factory

_engine = build_engine()
_factory = build_sessionmaker(_engine)

# app 级 Depends(get_db) 需要默认会话工厂——无 lifespan 的测试（test_app 临时路由等）同样需要。
# 模块级注入（lifespan 内会再次 set 为同一工厂，幂等）。
set_default_session_factory(_factory)


def _free_port() -> int:
    """获取一个可用端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture
async def db_session():
    """真实 Postgres 会话：单连接 + 事务回滚隔离，测试不落库。

    teardown 追加 `await _engine.dispose()`——asyncpg 连接绑定事件循环，
    pytest-asyncio 默认 function 级 loop 下，模块级 `_engine` 连接池会把上一测试（loop N）
    的连接复用给下一测试（loop N+1），导致 "another operation is in progress" /
    "NoneType has no attribute 'send'"（跨 loop 复用）。dispose 清空池，每测试新建连接。
    """
    conn = await _engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await _engine.dispose()


@pytest_asyncio.fixture
async def access_token(db_session):
    """真实库账号 + JwtService.generate_token 生成 access_token（返回 token 字符串）。

    - 账号取 DB 现有账号；空库时现场创建（真实 Postgres 事务内，测试结束回滚不落库），
      比计划示例的 `scalar_one()` 更健壮（示例假定 DB 恒有账号）。
    """
    account = (await db_session.execute(select(Account).limit(1))).scalars().first()
    if account is None:
        account = Account(name="access-token-fixture", email="access-token-fixture@llmops.local")
        db_session.add(account)
        await db_session.flush()
    return JwtService.generate_token({"sub": str(account.id), "iss": "llmops", "exp": 4102444800})


@pytest_asyncio.fixture
async def client():
    """httpx AsyncClient + ASGITransport（FastAPI app）。

    ASGITransport 不自动触发 lifespan，handler 路由在 lifespan 中注册。
    此 fixture 不触发 lifespan——测试仅验证静态路由（/healthz 等）。
    handler 路由的集成测试需要 lifespan 触发（uvicorn 或 asgi-lifespan），
    标记 @pytest.mark.skip 并登记原因。
    """
    from app.http.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers(access_token):
    """Bearer 认证请求头（依赖 access_token fixture）。"""
    return {"Authorization": f"Bearer {access_token}"}


# --- lifespan-aware 测试设施（uvicorn 真实 TCP） ---


class _UvicornTestServer:
    """在后台线程运行 uvicorn，触发 FastAPI lifespan。

    用法：
        server = _UvicornTestServer(app)
        await server.start()
        # ... httpx.AsyncClient(base_url=server.url) 直连 TCP ...
        await server.stop()
    """

    def __init__(self, app, host="127.0.0.1", port=None):
        self.app = app
        self.host = host
        self.port = port or _free_port()
        self._server = None
        self._thread = None
        self._started = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def start(self, timeout=30):
        """启动 uvicorn server（后台线程），等待就绪。"""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        def _run():
            # uvicorn.Server.run 是协程，需要用 asyncio.run
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._server.serve())
            except Exception:
                pass
            finally:
                self._started.set()
                loop.close()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        # 在 async 上下文中等待 server 就绪（通过尝试连接判断）
        import time
        import httpx
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # 先检查线程是否已退出（启动失败）
            if self._started.is_set():
                raise RuntimeError("uvicorn server exited before becoming ready")
            # 尝试连接
            try:
                async with httpx.AsyncClient(base_url=self.url, timeout=2.0) as probe:
                    resp = await probe.get("/healthz")
                    if resp.status_code in (200, 404, 204):
                        return  # server is ready
            except Exception:
                pass
            await asyncio.sleep(0.2)
        raise TimeoutError(f"uvicorn did not start within {timeout}s")

    async def stop(self):
        """优雅关闭 uvicorn server。"""
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=10)


@pytest_asyncio.fixture
async def live_server():
    """uvicorn TestServer（真实 TCP，触发 lifespan）。

    真实路由注册发生在 lifespan 中——handler 集成测试依赖此 fixture。
    每次 session 开启一次（module 级可优化为 session 级）。
    """
    from app.http.app import app as fastapi_app
    server = _UvicornTestServer(fastapi_app)
    await server.start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def live_client(live_server):
    """httpx AsyncClient 直连 uvicorn（真实 TCP，lifespan 已触发）。

    用于 153 路由冒烟、认证验证、SSE 全链路。
    """
    async with AsyncClient(base_url=live_server.url, timeout=60.0) as ac:
        yield ac


@pytest_asyncio.fixture
async def live_auth_headers(access_token):
    """真实 TCP 客户端的 Bearer 认证头。"""
    return {"Authorization": f"Bearer {access_token}"}


# --- 旧 Flask fixture 废弃：过渡期统一 skip（测试待 async 化） ---


@pytest.fixture
def app():
    pytest.skip("旧 Flask fixture 废弃，测试待 async 化")


@pytest.fixture
def db():
    pytest.skip("旧 Flask fixture 废弃，测试待 async 化")
