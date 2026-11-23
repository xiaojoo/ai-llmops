#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/28 16:37
@Author : sunxiaojie
@File   : paginator.py
"""
import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class PaginatorReq(BaseModel):
    """分页请求及处理，涵盖当前页数、每页条数，如果接口请求需要携带分页信息，可直接继承该类"""
    current_page: int = Field(default=1, description="每页数据的条数范围在1-9999")
    page_size: int = Field(default=20, description="每页数据的条数范围在1-50")

    @field_validator("current_page")
    @classmethod
    def validate_current_page(cls, v: int) -> int:
        if v < 1 or v > 9999:
            raise ValueError("每页数据的条数范围在1-9999")
        return v

    @field_validator("page_size")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        if v < 1 or v > 50:
            raise ValueError("每页数据的条数范围在1-50")
        return v


@dataclass
class Paginator:
    """分页器：count + offset/limit 分页（替代 Flask-SQLAlchemy db.paginate）"""
    total_page: int = 0
    total_record: int = 0
    current_page: int = 1
    page_size: int = 20

    def __init__(self, db: AsyncSession | None = None, req: PaginatorReq = None):
        if req is not None:
            self.current_page = req.current_page
            self.page_size = req.page_size
        self.db = db

    async def paginate(self, stmt) -> list[Any]:
        """对传入的查询进行分页（async 版）。

        语义与旧 `db.paginate(select, page=..., per_page=..., error_out=False)` 保持一致：
        - total_record/total_page 形状不变（total_page = math.ceil(total_record / page_size)）；
        - 页码越界（current_page 超过总页数）时返回空列表（error_out=False 行为），
          由 offset 越过末尾行自然得到；
        - db 未注入时抛明确错误（如 ApiKeyService 仅用 req 解析分页参数，不调用 paginate）。
        """
        if self.db is None:
            raise RuntimeError("Paginator.paginate 需要 AsyncSession（db 未注入）")

        # 计数：与旧 page.total 语义一致（同一过滤条件）。
        # count 子查询加 .order_by(None) 避免不必要的 ORDER BY。
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        self.total_record = await self.db.scalar(count_stmt) or 0
        self.total_page = math.ceil(self.total_record / self.page_size)

        # 数据行：LIMIT/OFFSET 分页。
        # 注意：joined eager load 集合（如 joinedload(Message.agent_thoughts)）要求 .unique()，
        # 否则 InvalidRequestError；普通查询下 unique() 为无害 no-op。
        rows = (
            await self.db.execute(
                stmt.offset((self.current_page - 1) * self.page_size).limit(self.page_size)
            )
        ).scalars().unique().all()
        return list(rows)


@dataclass
class PageModel:
    list: list[Any]
    paginator: Paginator
