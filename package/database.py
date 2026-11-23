import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from typing import TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import event, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from internal.config.settings import get_settings

# psycopg2 专用、asyncpg 不接受的查询参数（.env 的 postgresql:// URI 会携带）
_PSYCOPG2_ONLY_QUERY_PARAMS = {"client_encoding", "options"}

# options=-csearch_path=X（可带空格/等号/引号），多个 -c 选项以空白分隔
_OPTIONS_SEARCH_PATH_RE = re.compile(r'-c\s*search_path\s*=\s*(?:"([^"]*)"|([^;\s]+))')


def _extract_search_path(url: str) -> str | None:
    """从剥离前的 URI query 的 options 参数中提取 -csearch_path=X 的值；无则 None。"""
    if not url:
        return None
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    for key, value in query:
        if key == "options":
            m = _OPTIONS_SEARCH_PATH_RE.search(value)
            if m:
                return m.group(1) if m.group(1) is not None else m.group(2)
    return None


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        parts = urlsplit(url)
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k not in _PSYCOPG2_ONLY_QUERY_PARAMS
        ]
        # 注意：不要在此追加 search_path 之类参数——SQLAlchemy asyncpg 方言会把
        # URL query 参数原样作为 asyncpg.connect 的 kwargs 传入（未知参数抛
        # TypeError）。search_path 由 build_engine 的 connect 事件应用。
        return urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=urlencode(query)))
    return url


def _search_path_set_statement(search_path: str, dialect) -> str:
    """SET search_path TO X 的安全渲染：X 以字符串字面量渲染（单引号转义，防注入）。"""
    return str(
        text("SET search_path TO :sp")
        .bindparams(sp=search_path)
        .compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    )


class Base(DeclarativeBase):
    """全量 async 后所有 ORM model 的统一基类。"""


def build_engine(url: str | None = None, **opts) -> AsyncEngine:
    settings = get_settings()
    raw_url = url or settings.sqlalchemy_database_uri
    engine_url = _async_url(raw_url)
    kwargs: dict = dict(opts)
    kwargs.setdefault("echo", settings.sqlalchemy_echo)
    # sqlite（含 aiosqlite）默认用 StaticPool/QueuePool，不接受 pool_size/pool_recycle；
    # 仅对 postgres 等池化方言注入连接池参数（显式 opts 优先于 settings 默认值）。
    if not engine_url.startswith("sqlite"):
        kwargs.setdefault("pool_size", settings.sqlalchemy_pool_size)
        kwargs.setdefault("pool_recycle", settings.sqlalchemy_pool_recycle)
        # pool_pre_ping：检出连接前 SELECT 1 探活，死连接（强杀/跨 loop 毒化）直接丢弃重建，
        # 避免后续请求拿到已关闭连接报 "connection is closed"。
        kwargs.setdefault("pool_pre_ping", True)
        # search_path 可靠性：options=-csearch_path=X 用 asyncpg server_settings 在
        # 每次连接启动时应用。connect 事件（旧方案）只在首个连接触发（SQLAlchemy asyncpg 适配的
        # 连接复用路径不再触发事件），后续连接 search_path 回退 "$user", public → create_all/
        # 业务查询看不见 llmops schema。sync 引擎（get_sync_engine）走 psycopg2 原始 URL，
        # options 参数由 psycopg2 应用，无需此处处理。
        search_path = _extract_search_path(raw_url)
        if search_path is not None:
            connect_args = dict(kwargs.get("connect_args") or {})
            server_settings = dict(connect_args.get("server_settings") or {})
            server_settings.setdefault("search_path", search_path)
            connect_args["server_settings"] = server_settings
            kwargs["connect_args"] = connect_args

    engine = create_async_engine(engine_url, **kwargs)

    return engine


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# --- 同步引擎/会话工厂（Critical 2 修复：供 FullTextRetriever 等同步检索器使用） ---

_SYNC_ENGINE = None
_SYNC_SESSION_FACTORY = None


def get_sync_engine():
    """获取同步 SQLAlchemy 引擎（惰性创建，复用 async URL 的 search_path 逻辑）。

    用途：FullTextRetriever 等纯同步检索器在 async 服务内经 run_in_threadpool 调用，
    需要同步 Session 而非 AsyncSession。
    """
    global _SYNC_ENGINE
    if _SYNC_ENGINE is not None:
        return _SYNC_ENGINE
    settings = get_settings()
    raw_url = settings.sqlalchemy_database_uri
    # 同步引擎用原始 URL（postgresql:// 即 psycopg2），无需 async 转换
    kwargs = {"echo": settings.sqlalchemy_echo}
    if not raw_url.startswith("sqlite"):
        kwargs["pool_size"] = settings.sqlalchemy_pool_size
        kwargs["pool_recycle"] = settings.sqlalchemy_pool_recycle
    _SYNC_ENGINE = create_engine(raw_url, **kwargs)

    search_path = _extract_search_path(raw_url)
    if search_path is not None:
        @event.listens_for(_SYNC_ENGINE, "connect")
        def _apply_search_path_sync(dbapi_connection, connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute(_search_path_set_statement(search_path, _SYNC_ENGINE.dialect))
            cursor.close()

    return _SYNC_ENGINE


def get_sync_session_factory() -> sessionmaker[Session]:
    """获取同步 Session 工厂（惰性创建）。"""
    global _SYNC_SESSION_FACTORY
    if _SYNC_SESSION_FACTORY is not None:
        return _SYNC_SESSION_FACTORY
    _SYNC_SESSION_FACTORY = sessionmaker(bind=get_sync_engine(), expire_on_commit=False)
    return _SYNC_SESSION_FACTORY


_REQUEST_SESSION: ContextVar[AsyncSession | None] = ContextVar("_request_session", default=None)


def get_request_session() -> AsyncSession:
    """获取当前请求的 AsyncSession（由 get_db 依赖设置）。"""
    session = _REQUEST_SESSION.get()
    if session is None:
        raise RuntimeError("当前请求无 AsyncSession：请确保路由经 Depends(get_db)（app 级或路由级依赖）")
    return session


class RequestSessionProxy:
    """请求期会话代理：handler/服务构造时静态持有本代理，
    调用时通过 __getattr__ 转发到当前请求的 AsyncSession（get_db 设置的 contextvar）。

    背景：register_routes_from_container 在 lifespan 用一次性 session 构造 handler，
    注册后 session 即关闭——handler 的 db 必须改为请求期解析，而非持有关闭的会话。
    """

    def __getattr__(self, name: str):
        return getattr(get_request_session(), name)


async def get_db() -> AsyncIterator[AsyncSession]:
    """请求作用域会话：成功统一 commit，异常统一 rollback（替代旧 auto_commit）。

    设置 _REQUEST_SESSION contextvar，供 RequestSessionProxy 转发。
    `except BaseException`——SSE 流式期间客户端断开时 FastAPI 取消生成器，
    CancelledError/GeneratorExit 是 BaseException 而非 Exception，旧 `except Exception`
    会跳过显式回滚（仅靠 finally close() 兜底）；显式回滚避免连接以未提交事务状态归还池。
    """
    factory = get_default_session_factory()
    session = factory()
    token = _REQUEST_SESSION.set(session)
    try:
        yield session
        await session.commit()
    except BaseException:
        try:
            await session.rollback()
        except BaseException:
            # 连接可能已被取消/毒化（asyncpg 取消进行中操作会关闭连接），回滚失败静默——
            # finally 的 close() 与池的 pool_pre_ping 兜底，异常本体照常向上传播
            pass
        raise
    finally:
        await session.close()
        _REQUEST_SESSION.reset(token)


# lifespan 启动后注入；未注入时访问抛明确错误
_DEFAULT_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = None


def set_default_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _DEFAULT_SESSION_FACTORY
    _DEFAULT_SESSION_FACTORY = factory


def get_default_session_factory() -> async_sessionmaker[AsyncSession]:
    if _DEFAULT_SESSION_FACTORY is None:
        raise RuntimeError("会话工厂未初始化：请先在 lifespan 中调用 set_default_session_factory()")
    return _DEFAULT_SESSION_FACTORY


_T = TypeVar("T")


async def _run_worker(
    coro_factory: Callable[[AsyncSession], Awaitable[_T]],
    *,
    commit_on_success: bool = True,
    engine: AsyncEngine | None = None,
    engine_factory: Callable[[], AsyncEngine] | None = None,
) -> _T:
    """worker_run 的 loop 内实现：loop 内创建/使用 AsyncSession（禁止会话逃逸 loop）。

    Worker Transaction（事务模型）：默认成功后 commit；异常 rollback；内部可再显式 commit。

    engine 参数：Celery threads 池下每个任务线程各自 asyncio.run 新事件循环，
    若共享全局 engine（连接池），asyncpg 连接跨 loop 复用抛
    "cannot perform operation: another operation is in progress"——必须每任务独立 engine。

    engine_factory：更优——engine 的创建与 dispose 都发生在同一 loop 内
    （连接绑定 loop，跨 loop dispose 会抛 'NoneType' has no attribute 'send'）。
    """
    if engine_factory is not None:
        loop_engine = engine_factory()
        try:
            factory = build_sessionmaker(loop_engine)
            async with factory() as session:
                try:
                    result = await coro_factory(session)
                    if commit_on_success:
                        await session.commit()
                    return result
                except Exception:
                    await session.rollback()
                    raise
        finally:
            await loop_engine.dispose()

    factory = build_sessionmaker(engine) if engine is not None else get_default_session_factory()
    async with factory() as session:
        try:
            result = await coro_factory(session)
            if commit_on_success:
                await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


def worker_run(
    coro_factory: Callable[[AsyncSession], Awaitable[_T]],
    *,
    commit_on_success: bool = True,
    engine: AsyncEngine | None = None,
    engine_factory: Callable[[], AsyncEngine] | None = None,
) -> _T:
    """后台线程/Celery 任务体内调用（同步入口）：asyncio.run 独立事件循环 + 循环内 AsyncSession。

    P2.1.1-3：禁止从运行中的事件循环调用（asyncio.run 会抛难懂的错误）——显式守卫：

    engine/engine_factory 参数（Celery threads 池场景必传其一）：任务线程各自 asyncio.run 新 loop，
    共享全局 engine 会跨 loop 复用 asyncpg 连接报 InterfaceError；engine_factory 让 engine 的创建与
    dispose 同 loop（推荐），engine 则需调用方在任务结束 finally 中（新 loop）dispose。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # 无运行中 loop（线程/同步入口）——预期路径
    else:
        raise RuntimeError(
            "worker_run 只能从同步入口（线程/Celery）调用；当前处于运行中的事件循环，请直接 await 协程"
        )
    return asyncio.run(
        _run_worker(coro_factory, commit_on_success=commit_on_success, engine=engine, engine_factory=engine_factory)
    )


def run_sync_bridge(fn: Callable[[], _T]) -> _T:
    """同步桥接：无运行中 loop 时直接执行 fn（预期路径）；有运行中 loop 时（如工作流子图
    调试在主事件循环 inline 执行节点——langgraph 单任务 fast path 不走线程池）把 fn 丢到
    新线程执行，避免 asyncio.run/worker_run 在运行中 loop 内抛错。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()

    import threading

    result_box: list = []
    error_box: list = []

    def _target() -> None:
        try:
            result_box.append(fn())
        except BaseException as e:  # noqa: BLE001 桥接边界：异常原样上抛
            error_box.append(e)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if error_box:
        raise error_box[0]
    return result_box[0]
