#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 16:24
@Author : sunxiaojie
@File   : upload_file.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class Dataset(Base):
    """知识库表模型"""
    __tablename__ = "dataset"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_dataset_id"),
        {"comment": "知识库表"},
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
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="知识库名称")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="知识库图标")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="知识库描述")


class Document(Base):
    """文档表模型"""
    __tablename__ = "document"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_document_id"),
        {"comment": "文档表"},
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
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属知识库ID")
    upload_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="上传文件ID")
    process_rule_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="处理规则ID")
    batch: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="批次号")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="文档名称")
    title: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="文档元数据：标题（PDF、Word等提取）")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="文档元数据：页数")
    footer: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="文档元数据：页脚")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), comment="排序位置")
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="字符数")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="token数")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="处理开始时间")
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="处理完成时间")
    splitting_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="切分完成时间")
    indexing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="索引完成时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="全部处理完成时间")
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="停止时间")
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="错误信息")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否启用")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="停用时间")
    status: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("'waiting'::character varying"), comment="处理状态（waiting等）")


class Segment(Base):
    """片段表模型"""
    __tablename__ = "segment"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_segment_id"),
        {"comment": "片段表"},
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
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属知识库ID")
    document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属文档ID")
    node_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="关联节点ID")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), comment="排序位置")
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="片段内容")
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="字符数")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="token数")
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="关键词列表")
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="层级化索引：章节摘要（RAPTOR简化版）")
    parent_segment_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="父片段ID（层级化索引）")
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'text'::character varying"), comment="结构感知：内容类型（text/table/image/heading）")
    image_url: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="图片URL")
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="来源定位：页码")
    section_title: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="来源定位：所属章节标题")
    footer: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="来源定位：文档页脚")
    hash: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="内容哈希")
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="命中次数")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否启用")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="停用时间")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="处理开始时间")
    indexing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="索引完成时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="完成时间")
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="错误信息")
    status: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("'waiting'::character varying"), comment="处理状态（waiting等）")


class KeywordTable(Base):
    """关键词表模型"""
    __tablename__ = "keyword_table"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_keyword_table_id"),
        {"comment": "关键词表"},
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
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属知识库ID")
    keyword_table: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="关键词表数据")


class DatasetQuery(Base):
    """知识库查询表模型"""
    __tablename__ = "dataset_query"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_dataset_query_id"),
        {"comment": "知识库查询记录表"},
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
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属知识库ID")
    query: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="查询内容")
    source: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("'HitTesting'::character varying"), comment="查询来源（默认HitTesting命中测试）")
    source_app_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="来源应用ID")
    created_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="创建记录ID")


class ProcessRule(Base):
    """文档处理规则表模型"""
    __tablename__ = "process_rule"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_process_rule_id"),
        {"comment": "文档处理规则表"},
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
    dataset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="所属知识库ID")
    mode: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("'automic'::character varying"), comment="处理模式（automic自动等）")
    rule: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="规则配置")
