#!/usr/bin/env python
"""Agent 运行（Run）模型：一次执行的持久化实体

Run = 一次完整 Agent 执行（顶层对话轮 / 编排器父 run / 子任务 run）。
message.status 收窄为该消息"最新 run 状态的投影"（project_message_status）。
run 状态机由 Runtime 驱动：pending → running → (awaiting_input ⇄ running) → 终态。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class AgentRun(Base):
    """Agent 运行表：一次执行（顶层 run 或子任务 run）的生命周期与统计"""
    __tablename__ = "agent_run"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_agent_run_id"),
        # （message_id, version）唯一：同一消息的第 N 次 run（stop→resume→新 run 递增）
        UniqueConstraint("message_id", "version", name="uq_agent_run_message_version"),
        # 编排器子任务 run 按父 run 归组（级联取消/按树聚合计费）
        Index("idx_agent_run_parent", "parent_run_id"),
        Index("idx_agent_run_conversation", "conversation_id"),
        {"comment": "Agent 运行表（run 生命周期/统计）"},
    )

    id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID（= run_id）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建人ID（账号/终端用户）")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        onupdate=datetime.now,
        comment="更新时间",
    )
    updated_by: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="更新人ID")

    # 归属（与 Message 对齐）
    app_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
    conversation_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属会话ID")
    message_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属消息ID")
    parent_run_id: Mapped[object | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_run.id"), nullable=True, comment="父 run_id（编排器主 run → 子任务 run；普通对话为 NULL）")
    invoke_from: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="调用来源")

    # run 语义
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"), comment="Agent 类型（function_call/react/orchestrator/…）")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), comment="该消息第几次 run（stop→resume 递增）")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'::character varying"), comment="run 状态（RunStatus）")
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="错误信息（failed 时）")
    resume_trigger: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None, comment="是否显式恢复触发（manual 模式）")

    # 统计（可投影）
    total_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="总token数")
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="总费用")
    latency: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.0"), comment="总耗时（秒）")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="开始执行时间")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")
