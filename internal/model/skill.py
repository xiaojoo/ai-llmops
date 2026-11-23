#!/usr/bin/env python
"""
@Time    : 2026/3/20 18:06
@Author  : sunxiaojie
@File    : skills.py
"""
from datetime import datetime

from sqlalchemy import (
    UUID,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class Skill(Base):
    """技能表模型"""
    __tablename__ = "skill"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_skill_id"),
        Index("idx_skill_account_visibility", "account_id", "visibility"),
        {"comment": "技能表"},
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
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属用户ID，用于用户隔离")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="技能名称")
    description: Mapped[str] = mapped_column(Text, nullable=True, comment="技能描述")
    icon: Mapped[str] = mapped_column(String(500), nullable=True, server_default=text("''::character varying"), comment="技能图标")
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'private'::character varying"),
        comment="可见性：private=独占，public=分享（所有用户可见）",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="入口SKILL.md正文内容")
    archive_url: Mapped[str] = mapped_column(
        String(1000), nullable=True, server_default=text("''::character varying"),
        comment="MinIO归档文件URL（原始上传的md/zip）",
    )
