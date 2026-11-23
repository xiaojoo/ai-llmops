#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : procedural_memory.py
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Integer, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class ProceduralMemory(Base):
    """程序记忆 —— Agent 做事的规则和人设，靠反馈与反思不断改写。

    按 (app_id, user_id) 隔离；version 乐观锁，每次改写 +1，保留历史由外部审计。
    """
    __tablename__ = "procedural_memory"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_procedural_memory_id"),
        {"comment": "程序记忆表（Agent行为规则与人设）"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="应用命名空间")
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属用户ID")
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="行为规则/人设指令")
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"), comment="来源：reflection/feedback/user_explicit/system")
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"), comment="信任加权 0~1")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), comment="改写版本号（乐观锁，每次改写+1）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
