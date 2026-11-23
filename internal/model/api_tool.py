#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/27 14:52
@Author : sunxiaojie
@File   : api_tool.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from package.database import Base


class ApiToolProvider(Base):
    """API工具提供者模型类"""
    __tablename__ = "api_tool_provider"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_api_tool_provider_id"),
        # UniqueConstraint("account_id", "name", name="uq_api_tool_provider_account_id_name"),
        Index("idx_api_tool_provider_account_id_name", "account_id", "name"),
        {"comment": "API工具提供者表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=True, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=True, server_default=text("''::character varying"), comment="更新人ID")
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属账号ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="提供者名称")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="图标URL")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="提供者描述")
    openapi_schema: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="OpenAPI schema定义")
    headers: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="请求头配置列表")

    tools: Mapped[list["ApiTool"]] = relationship(
        "ApiTool",
        lazy="selectin",  # 默认 selectin 预加载——所有访问点免显式 selectinload，防 MissingGreenlet
        viewonly=True,
    )


class ApiTool(Base):
    """API工具模型"""
    __tablename__ = "api_tool"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_api_tool_id"),
        {"comment": "API工具表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="更新人ID")
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属账号ID")
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True),ForeignKey("api_tool_provider.id"),nullable=False, comment="关联提供者ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="工具名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="工具描述")
    url: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="接口URL")
    method: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="HTTP请求方法")
    parameters: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="参数定义列表")

    provider: Mapped["ApiToolProvider"] = relationship(
        "ApiToolProvider",
        lazy="selectin",
        viewonly=True,
    )
