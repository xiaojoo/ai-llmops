#!/usr/bin/env python
"""
@Time    : 2026/1/20 21:10
@Author  : sunxiaojie
@File    : end_user.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    DateTime,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class EndUser(Base):
    """终端用户表模型"""
    __tablename__ = "end_user"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_end_user_id"),
        {"comment": "终端用户表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=True, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=True, server_default=text("''::character varying"), comment="更新人ID")
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属账号/空间ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
