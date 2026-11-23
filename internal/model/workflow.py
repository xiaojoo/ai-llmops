#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2026/01/25 21:06
@Author : sunxiaojie
@File   : workflow.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    Float,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class Workflow(Base):
    """工作流模型"""
    __tablename__ = "workflow"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_id"),
        {"comment": "工作流表"},
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
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建账号ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="工作流名称")
    tool_call_name: Mapped[str] = mapped_column(String(255), nullable=False,
                                                server_default=text("''::character varying"), comment="工具调用名称")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="工作流图标")
    description: Mapped[Text] = mapped_column(String(255), nullable=False, server_default=text("''::text"), comment="工作流描述")
    graph: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="工作流图配置")
    draft_graph: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="草稿图配置")
    is_debug_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否调试通过")
    status: Mapped[Text] = mapped_column(String(255), nullable=False, server_default=text("''::text"), comment="工作流状态")
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="发布时间")


class WorkflowResult(Base):
    """工作流存储结果模型"""
    __tablename__ = "workflow_result"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_result_id"),
        {"comment": "工作流运行结果表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="更新人ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="调用工作流的应用ID，为空代表非应用调用")
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建账号ID")
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="结果关联的工作流ID")
    graph: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="运行时图配置")
    state: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="工作流最终状态")
    latency: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.0"), comment="消息总耗时（秒）")
    status: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="运行状态")
