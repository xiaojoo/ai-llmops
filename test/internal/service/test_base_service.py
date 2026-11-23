#!/usr/bin/env python
"""BaseService 标准 async CRUD——add 不 await、delete await 语义。"""
import inspect

import pytest
import pytest_asyncio
from sqlalchemy import select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from internal.exception import FailedException
from internal.service.base_service import BaseService
from package.database import Base, build_engine, build_sessionmaker


class Widget(Base):
    __tablename__ = "widget"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


def test_async_session_add_is_sync_delete_is_async():
    """核验：AsyncSession.add 是同步方法（不 await）；delete/flush 是协程（必须 await）。"""
    assert not inspect.iscoroutinefunction(AsyncSession.add)
    assert inspect.iscoroutinefunction(AsyncSession.delete)
    assert inspect.iscoroutinefunction(AsyncSession.flush)


@pytest_asyncio.fixture
async def session():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 真实模型已注册到 Base.metadata（PG 专属 DDL 无法在 sqlite 建表），
        # 此处只建本文件局部测试表 Widget
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Widget.__table__]))
    factory = build_sessionmaker(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def db_and_factory():
    """返回 (session, factory)：独立事务/回滚语义测试需新会话验证跨事务持久化。"""
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Widget.__table__]))
    factory = build_sessionmaker(engine)
    async with factory() as s:
        yield s, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_uses_sync_add_and_persists(session):
    """create：add 是同步调用（若误 await 同步方法会 TypeError），提交后可见。"""
    service = BaseService(db=session)
    widget = await service.create(Widget, name="hello")
    assert widget.id is not None
    rows = (await session.execute(select(Widget))).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "hello"


@pytest.mark.asyncio
async def test_create_commits_independent_transaction(db_and_factory):
    """create 为独立事务边界（与旧 auto_commit 语义一致）：块尾真实 commit →
    提交后 DB 生成主键已回填，且新会话可见（跨事务持久化，请求→后台可见性不破坏）。"""
    session, factory = db_and_factory
    service = BaseService(db=session)
    widget = await service.create(Widget, name="committed")
    assert widget.id is not None  # commit 触发 flush，DB 生成主键回填
    async with factory() as fresh:
        rows = (await fresh.execute(select(Widget))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "committed"


@pytest.mark.asyncio
async def test_update_failure_does_not_commit(db_and_factory):
    """回滚路径：update 抛 FailedException（未知字段）→ 块尾 commit 不执行，
    外层可 rollback 兜底，不产生脏数据。"""
    session, factory = db_and_factory
    widget = Widget(name="old")
    session.add(widget)
    await session.commit()
    service = BaseService(db=session)
    with pytest.raises(FailedException):
        await service.update(widget, nonexistent_field=1)
    await session.rollback()  # 外层（get_db/worker_run）兜底回滚
    async with factory() as fresh:
        rows = (await fresh.execute(select(Widget))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "old"


@pytest.mark.asyncio
async def test_get_returns_instance_by_pk(session):
    widget = Widget(name="hello")
    session.add(widget)
    await session.flush()
    service = BaseService(db=session)
    found = await service.get(Widget, widget.id)
    assert found is widget


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(session):
    service = BaseService(db=session)
    assert await service.get(Widget, 9999) is None


@pytest.mark.asyncio
async def test_update_sets_fields(session):
    widget = Widget(name="old")
    session.add(widget)
    await session.flush()
    service = BaseService(db=session)
    updated = await service.update(widget, name="new")
    assert updated is widget
    assert widget.name == "new"
    await session.flush()
    rows = (await session.execute(select(Widget))).scalars().all()
    assert rows[0].name == "new"


@pytest.mark.asyncio
async def test_update_unknown_field_raises(session):
    widget = Widget(name="old")
    session.add(widget)
    await session.flush()
    service = BaseService(db=session)
    # 项目自定义异常把消息存在 .message（str() 为空），按属性断言
    with pytest.raises(FailedException) as exc_info:
        await service.update(widget, nonexistent_field=1)
    assert exc_info.value.message == "更新数据失败"


@pytest.mark.asyncio
async def test_delete_awaits_async_delete(session):
    """delete：AsyncSession.delete 是协程必须 await；flush 后记录真正删除。"""
    widget = Widget(name="bye")
    session.add(widget)
    await session.flush()
    service = BaseService(db=session)
    result = await service.delete(widget)
    assert result is widget
    await session.flush()
    rows = (await session.execute(select(Widget))).scalars().all()
    assert rows == []
