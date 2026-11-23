#!/usr/bin/env python
"""Paginator async 化测试——count + offset/limit 语义与旧 db.paginate(error_out=False) 一致。

使用 sqlite 内存引擎 + 局部测试表（真实模型含 PG 专属 DDL，无法在 sqlite 建表）。
"""
import pytest
import pytest_asyncio
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base, build_engine, build_sessionmaker
from package.paginator import Paginator


class Item(Base):
    __tablename__ = "pg_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


@pytest_asyncio.fixture
async def session():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Item.__table__]))
    Session = build_sessionmaker(engine)
    async with Session() as s:
        s.add_all([Item(name=f"item-{i}") for i in range(25)])
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_paginate_first_page_shape(session: AsyncSession):
    """total_record/total_page/current_page/page_size 形状与旧公式一致"""
    p = Paginator(db=session)
    p.current_page = 1
    p.page_size = 10

    items = await p.paginate(select(Item).order_by(Item.id))

    assert len(items) == 10
    assert p.total_record == 25
    assert p.total_page == 3, "math.ceil(25/10) == 3"
    assert p.current_page == 1
    assert p.page_size == 10


@pytest.mark.asyncio
async def test_paginate_middle_and_last_page(session: AsyncSession):
    p = Paginator(db=session)
    p.current_page = 2
    p.page_size = 10
    items = await p.paginate(select(Item).order_by(Item.id))
    assert len(items) == 10
    assert items[0].name == "item-10"

    p.current_page = 3
    items = await p.paginate(select(Item).order_by(Item.id))
    assert len(items) == 5
    assert items[-1].name == "item-24"


@pytest.mark.asyncio
async def test_paginate_out_of_range_returns_empty(session: AsyncSession):
    """页码越界（error_out=False 行为）：返回空列表而非 404"""
    p = Paginator(db=session)
    p.current_page = 99
    p.page_size = 10

    items = await p.paginate(select(Item).order_by(Item.id))

    assert items == []
    assert p.total_record == 25
    assert p.total_page == 3


@pytest.mark.asyncio
async def test_paginate_empty_table(session: AsyncSession):
    await session.execute(Item.__table__.delete())
    await session.commit()

    p = Paginator(db=session)
    items = await p.paginate(select(Item).order_by(Item.id))

    assert items == []
    assert p.total_record == 0
    assert p.total_page == 0


@pytest.mark.asyncio
async def test_paginate_requires_db():
    """db 未注入（如 ApiKeyService 仅解析 req）时调用 paginate 抛明确错误"""
    p = Paginator(db=None)
    with pytest.raises(RuntimeError, match="AsyncSession"):
        await p.paginate(select(Item))
