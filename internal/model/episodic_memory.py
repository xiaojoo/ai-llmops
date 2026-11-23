#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : episodic_memory.py
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class EpisodicMemory(Base):
    """情景记忆 —— 一次完整经历的记录（事件/情景/思路），配合向量检索召回。

    按 (app_id, user_id) 命名空间隔离，防止多用户记忆混乱。
    """
    __tablename__ = "episodic_memory"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_episodic_memory_id"),
        {"comment": "情景记忆表（事件/情景/思路记录）"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="应用命名空间")
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属用户ID")
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="经历内容")
    importance: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"), comment="重要性 0~1（写入时LLM打分）")
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"), comment="来源：llm_inferred/user_explicit/tool/system")
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"), comment="信任加权 0~1")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="过期时间（TTL）")
    embedding_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"), comment="向量对象ID（Weaviate）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
