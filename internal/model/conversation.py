#!/usr/bin/env python
"""
@Time    : 2025/12/13 13:11
@Author  : sunxiaojie
@File    : conversation.py
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from package.database import Base


class Conversation(Base):
    """交流会话模型"""
    __tablename__ = "conversation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_conversation_id"),
        {"comment": "会话表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="更新人ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="会话名称")
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="会话摘要")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否置顶")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
    invoke_from: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="调用来源")
    dialog_round: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="短期记忆窗口轮数（会话级覆盖，NULL=使用应用配置）")


class Message(Base):
    """交流消息模型"""
    __tablename__ = "message"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_message_id"),
        {"comment": "消息表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="更新人ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属会话ID")
    invoke_from: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="调用来源")
    query: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="消息关联的原始问题")
    image_urls: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="用户提问的图片URL列表")
    file_urls: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="用户提问的附件文件列表：[{id, name, size, extension, url}, ...]")
    message: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="消息内容（JSON）")
    message_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="消息token数")
    message_unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="消息单价")
    message_price_unit: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="消息计价单位")
    answer: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="消息关联的答案内容")
    reasoning_content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="assistant 推理过程（DeepSeek thinking reasoning_content），跨轮次重建历史时回传")
    answer_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="答案token数")
    answer_unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="答案单价")
    answer_price_unit: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="答案计价单位")
    latency: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.0"), comment="消息相关统计：总耗时（秒）")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
    status: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="消息状态")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否已归档（压缩出短期记忆窗口，仅保留在滚动摘要与历史查询中）")
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="错误信息")
    feedback: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("''::character varying"), comment="用户反馈：''无反馈 / like点赞 / dislike点踩")
    total_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="总token数")
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="总费用")

    # 智能体推理列表，创建表关联
    agent_thoughts: Mapped[list["MessageAgentThought"]] = relationship(
        back_populates="msg",  # 显式指向子表的属性名
        lazy="selectin",  # 高效加载策略
        cascade="all, delete-orphan",  # 级联删除：删除Message时删除对应的Thought
    )


class MessageAgentThought(Base):
    """智能体消息推理模型，用于记录Agent生成最终消息答案"""
    __tablename__ = "message_agent_thought"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_message_agent_thought_id"),
        {"comment": "智能体推理步骤表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="更新人ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属会话ID")
    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("message.id"), nullable=False, comment="所属消息ID")
    invoke_from: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="调用来源")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="该步骤在消息中执行的位置")
    event: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="事件类型，分别记录LLM和非LLM产生的消息")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="LLM模型名（该步骤调用使用的模型）")
    thought: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="推理内容")
    observation: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="观察内容")
    llm_output: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="LLM完整输出（纯文本回答=全文；工具调用轮=输出文本）")
    tool_calls: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="LLM声明的工具调用列表 [{name,args,id,type}]")
    tool: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="工具名称（调用工具时生成）")
    tool_input: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="工具输入")
    trace: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="Agentic重检轨迹：每轮{round, strategy, query, k, hits, sufficient, score, missing}")
    message: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="推理观察步骤使用的消息列表（传递prompt消息内容）")
    message_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="消息token数")
    message_unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default=text("0.0"), comment="消息单价")
    message_price_unit: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default=text("0.0"), comment="消息计价单位")
    answer: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="LLM生成内容")
    answer_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="答案token数")
    answer_unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default=text("0.0"), comment="答案单价")
    answer_price_unit: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default=text("0.0"), comment="答案计价单位")
    total_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="总token数")
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"), comment="总费用")
    latency: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.0"), comment="推理观察统计：耗时（秒）")
    sub_task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="编排器子任务ID（非编排事件为空）")
    sub_task_title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="子任务标题")
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="任务ID（ask_user 交互式选项提交用，SSE 事件携带；历史回显后仍可提交选择）")
    # 添加反向关系
    msg: Mapped["Message"] = relationship(back_populates="agent_thoughts")
