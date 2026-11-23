#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/16 19:42
@Author : sunxiaojie
@File   : app.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from internal.entity.app_entity import AppStatus
from package.database import Base


class App(Base):
    """AI应用基础模型类"""
    __tablename__ = "app"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_app_id"),
        Index("idx_app_account_id", "account_id"),
        {"comment": "AI应用表"},
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
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="创建账号ID")
    app_config_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="发布配置ID，为空表示没有发布")
    draft_app_config_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="关联的草稿配置ID")
    debug_conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True, comment="应用调试会话ID，为None则代表没有会话消息")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="应用名称")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="应用图标")
    description: Mapped[Text] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="应用描述")
    token: Mapped[str] = mapped_column(String(255), nullable=True, server_default=text("''::character varying"), comment="应用访问凭证")
    status: Mapped[str] = mapped_column(
        String(255), nullable=False,
        server_default=text("''::character varying"), comment="应用状态（draft草稿/published已发布）")
    app_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        server_default=text("'agent'::character varying"), comment="应用类型：agent / orchestrator")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")


class AppConfig(Base):
    """应用配置模型类"""
    __tablename__ = "app_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_app_config_id"),
        {"comment": "应用配置表"},
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
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
    model_config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="模型配置")
    dialog_round: Mapped[Integer] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="携带上下文轮数")
    preset_prompt: Mapped[Text] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="预设提示词")
    tools: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="应用关联工具列表")
    skills: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="skill配置")
    workflows: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="应用关联工作流列表")
    retrieval_config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="检索配置")
    long_term_memory: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="长期记忆配置")
    opening_statement: Mapped[Text] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="开场白文案")
    opening_questions: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="开场白建议问题")
    speech_to_text: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="语音转文本配置")
    text_to_speech: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="文本转语音配置")
    suggested_after_answer: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{\"enable\": true}'::jsonb"), comment="回答后生成建议问题")
    review_config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="审核配置")
    orchestrator_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="编排器配置（任务分解）")


class AppConfigVersion(Base):
    """应用配置版本历史表，用于存储草稿配置+历史发布配置"""
    __tablename__ = "app_config_version"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_app_config_version_id"),
        {"comment": "应用配置版本表（草稿配置+历史发布配置）"},
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
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联应用ID")
    model_config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="模型配置")
    dialog_round: Mapped[Integer] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="携带上下文轮数")
    preset_prompt: Mapped[Text] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="预设提示词")
    tools: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="应用关联工具列表")
    skills: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="skill配置")
    workflows: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="应用关联工作流列表")
    datasets: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="应用关联的知识库列表")
    retrieval_config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="检索配置")
    long_term_memory: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="长期记忆配置")
    opening_statement: Mapped[Text] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="开场白文案")
    opening_questions: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="开场白建议问题")
    speech_to_text: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="语音转文本配置")
    text_to_speech: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="文本转语音配置")
    suggested_after_answer: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text(
        "'{\"enable\": true}'::jsonb"), comment="回答后生成建议问题")
    review_config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="审核配置")
    orchestrator_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="编排器配置（任务分解）")
    version: Mapped[Integer] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="发布版本号")
    config_type: Mapped[str] = mapped_column(String(255), nullable=False,
                                             server_default=text("''::character varying"), comment="版本类型（draft草稿/published已发布）")


class AppDatasetJoin(Base):
    """应用知识库关联表模型"""
    __tablename__ = "app_dataset_join"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_app_dataset_join_id"),
        {"comment": "应用-知识库关联表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                      server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                      server_default=text("''::character varying"), comment="更新人ID")
    app_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="关联应用ID")
    dataset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="关联知识库ID")
