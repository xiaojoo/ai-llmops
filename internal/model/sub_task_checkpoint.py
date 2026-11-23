#!/usr/bin/env python
"""子任务断点模型：中断续跑 + 结果缓存"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime, Index, Integer, Numeric, PrimaryKeyConstraint, String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class SubTaskCheckpoint(Base):
    """子任务断点：按 (message_id, position) 定位，query 校验有效性

    断点归属到具体消息（message_id）而非会话（conversation_id）：
    同一会话内多轮编排消息不会互相覆盖断点，中断后可按消息精确续跑。
    """
    __tablename__ = "sub_task_checkpoint"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_sub_task_checkpoint_id"),
        # （message_id, position）唯一索引——断点定位键，支撑原子 upsert
        Index("idx_sub_task_checkpoint_msg_pos", "message_id", "position", unique=True),
        {"comment": "子任务断点表（中断续跑+结果缓存）"},
    )

    id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        # ORM 侧 onupdate（数据库缺 ON UPDATE，Python 侧保证更新时刷新）
        onupdate=datetime.now,
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="更新人ID")
    app_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="应用命名空间")
    conversation_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属会话ID")
    message_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属消息ID")
    position: Mapped[int] = mapped_column(Integer, nullable=False, comment="断点在会话中的位置")
    plan_id: Mapped[object | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="计划身份（plan 代际；replan/regenerate 重拆时旧断点失效，防错误复用）")
    query: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="子任务原始问题（校验断点有效性）")
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="子任务标题")
    role_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="子任务角色提示词")
    expect_output: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="期望输出说明")
    required_tools: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="需要的工具列表")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'running'::character varying"), comment="断点状态（running等）")
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="已执行消息列表")
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="已迭代轮次")
    partial_answer: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="部分回答内容")
    total_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="总token数")
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="总费用")
