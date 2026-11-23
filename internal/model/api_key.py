#!/usr/bin/env python
"""
@Time    : 2026/1/20 21:10
@Author  : sunxiaojie
@File    : api_key.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class ApiKey(Base):
    """API秘钥模型"""
    __tablename__ = "api_key"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_api_key_id"),
        Index("api_key_api_key_idx", "api_key"),
        {"comment": "API密钥表"},
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
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联账号ID")
    api_key: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="API密钥")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否启用")
    remark: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="备注")
