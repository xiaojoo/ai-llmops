import asyncio
import threading

import pytest
from sqlalchemy import select, String
from sqlalchemy.orm import Mapped, mapped_column

import package.database as db_module
from package.database import (
    Base,
    build_engine,
    build_sessionmaker,
    get_db,
    set_default_session_factory,
    worker_run,
)


class Item(Base):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


@pytest.mark.asyncio
async def test_session_commit_and_query():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 真实模型已注册到 Base.metadata（PG 专属 DDL 无法在 sqlite 建表），
        # 此处只建本文件局部测试表 Item
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Item.__table__]))
    Session = build_sessionmaker(engine)

    async with Session() as s:
        s.add(Item(name="hello"))
        await s.commit()

    async with Session() as s:
        rows = (await s.execute(select(Item))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "hello"
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_error():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Item.__table__]))
    Session = build_sessionmaker(engine)

    async def consume():
        # get_db 不再接受 session_factory 参数，使用默认工厂
        # 测试需要先注入 session factory
        set_default_session_factory(Session)
        gen = get_db()
        s = await gen.__anext__()
        s.add(Item(name="ghost"))
        await s.flush()
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("boom"))
        await gen.aclose()

    await consume()

    async with Session() as s:
        rows = (await s.execute(select(Item))).scalars().all()
        assert rows == []
    await engine.dispose()


def test_asyncpg_url_rewrite():
    from package.database import _async_url
    assert _async_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _async_url("sqlite+aiosqlite:///:memory:") == "sqlite+aiosqlite:///:memory:"


def test_asyncpg_url_strips_psycopg2_query_params():
    """psycopg2 专用参数（client_encoding/options）必须剥离，其他参数保留。"""
    from package.database import _async_url
    url = (
        "postgresql://u:p@h/db"
        "?client_encoding=utf8&options=-csearch_path=llmops&search_path=public"
    )
    result = _async_url(url)
    assert result == "postgresql+asyncpg://u:p@h/db?search_path=public"
    assert "client_encoding" not in result
    assert "options" not in result


def test_asyncpg_url_without_psycopg2_params_only_swaps_driver():
    """无 psycopg2 专用参数时，仅替换驱动前缀，查询串原样保留。"""
    from package.database import _async_url
    assert (
        _async_url("postgresql://u:p@h/db?search_path=llmops")
        == "postgresql+asyncpg://u:p@h/db?search_path=llmops"
    )


def test_asyncpg_url_strips_options_without_adding_search_path():
    """options 剥离后 URL 不追加参数（SQLAlchemy asyncpg 方言会把 URL 参数当 kwargs 传，
    search_path 需经 build_engine 的 connect 事件应用，而不是 URL）。"""
    from package.database import _async_url
    url = "postgresql://u:p@h/db?client_encoding=utf8&options=-csearch_path=llmops"
    result = _async_url(url)
    assert result == "postgresql+asyncpg://u:p@h/db"
    assert "client_encoding" not in result
    assert "options" not in result
    assert "search_path" not in result


def test_extract_search_path_from_options():
    from package.database import _extract_search_path
    assert _extract_search_path("postgresql://u:p@h/db?options=-csearch_path=llmops") == "llmops"
    # -c 与 search_path 之间允许空格
    assert _extract_search_path("postgresql://u:p@h/db?options=-c search_path=llmops") == "llmops"


def test_extract_search_path_absent():
    from package.database import _extract_search_path
    assert _extract_search_path("postgresql://u:p@h/db") is None
    # 仅 URL 级 search_path 参数（非 options）不提取
    assert _extract_search_path("postgresql://u:p@h/db?search_path=public") is None


def test_extract_search_path_variants():
    from package.database import _extract_search_path
    # options 里是其他 -c 参数（无 search_path）→ None
    assert _extract_search_path("postgresql://u:p@h/db?options=-cfoo=1&search_path=bar") is None
    # 多 -c 选项（空白分隔），search_path 位于其中
    assert _extract_search_path("postgresql://u:p@h/db?options=-csearch_path=llmops -cfoo=1") == "llmops"
    # 值含空格/等号（双引号包裹）
    assert _extract_search_path(
        'postgresql://u:p@h/db?options=-csearch_path="llmops, public"'
    ) == "llmops, public"


def test_search_path_set_statement_quotes_safely():
    """SET search_path 语句按字符串字面量渲染：正常值与注入尝试都被安全转义。"""
    from package.database import _search_path_set_statement
    from sqlalchemy.dialects import postgresql
    dialect = postgresql.dialect()
    assert _search_path_set_statement("llmops", dialect) == "SET search_path TO 'llmops'"
    malicious = "public'; DROP TABLE x; --"
    stmt = _search_path_set_statement(malicious, dialect)
    assert stmt == "SET search_path TO 'public''; DROP TABLE x; --'"


def test_build_engine_with_search_path_uses_server_settings(monkeypatch):
    """含 options search_path 的 URL 建引擎时把 search_path 注入 connect_args.server_settings
    （417db55：asyncpg server_settings 方案替代 connect 事件——后者只在首个连接触发）。"""
    import package.database as db_module
    from sqlalchemy.ext.asyncio import create_async_engine as real_create_async_engine

    captured: dict = {}

    def _fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return real_create_async_engine("sqlite+aiosqlite:///:memory:")

    monkeypatch.setattr(db_module, "create_async_engine", _fake_create_async_engine)

    build_engine("postgresql://u:p@h/db?options=-csearch_path=llmops")
    sp_settings = (captured["kwargs"].get("connect_args") or {}).get("server_settings", {})
    assert sp_settings.get("search_path") == "llmops"

    # 无 search_path 的 URL 不注入 server_settings
    captured.clear()
    build_engine("postgresql://u:p@h/db")
    plain_settings = (captured["kwargs"].get("connect_args") or {}).get("server_settings", {})
    assert "search_path" not in plain_settings


# --- worker_run / _run_worker ---


@pytest.fixture
def worker_engine(monkeypatch):
    """内存 sqlite 引擎 + 默认会话工厂注入；测试结束恢复原工厂并释放引擎。"""
    engine = build_engine("sqlite+aiosqlite:///:memory:")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Item.__table__]))

    asyncio.run(_create())
    monkeypatch.setattr(db_module, "_DEFAULT_SESSION_FACTORY", build_sessionmaker(engine))
    yield engine
    engine.sync_engine.dispose()


def _count_items() -> int:
    async def _count():
        factory = db_module.get_default_session_factory()
        async with factory() as s:
            return len((await s.execute(select(Item))).scalars().all())

    return asyncio.run(_count())


def test_worker_run_commits_on_success(worker_engine):
    """默认 commit_on_success=True：协程成功 → 提交落库。"""

    async def add_item(session):
        session.add(Item(name="worker"))
        return "ok"

    assert worker_run(add_item) == "ok"
    assert _count_items() == 1


def test_worker_run_rolls_back_on_error(worker_engine):
    """协程抛异常 → rollback，不留脏数据。"""

    async def fail(session):
        session.add(Item(name="ghost"))
        await session.flush()
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        worker_run(fail)
    assert _count_items() == 0


def test_worker_run_commit_on_success_false(worker_engine):
    """commit_on_success=False：成功也不提交（独立事务交给内部显式 commit）。"""

    async def add_item(session):
        session.add(Item(name="no-commit"))

    worker_run(add_item, commit_on_success=False)
    assert _count_items() == 0


@pytest.mark.asyncio
async def test_worker_run_guard_rejects_running_loop():
    """防护：运行中事件循环内调用 worker_run 必须抛清晰 RuntimeError。"""

    async def noop(session):
        return None

    with pytest.raises(RuntimeError, match="运行中的事件循环"):
        worker_run(noop)


def test_worker_run_works_from_plain_thread(worker_engine):
    """普通线程（无运行中 loop）内调用 worker_run 成功，独立 loop 内提交落库。"""
    result_box: dict = {}

    async def add_item(session):
        session.add(Item(name="thread"))
        return "thread-ok"

    def target():
        result_box["result"] = worker_run(add_item)

    t = threading.Thread(target=target)
    t.start()
    t.join()
    assert result_box["result"] == "thread-ok"
    assert _count_items() == 1
