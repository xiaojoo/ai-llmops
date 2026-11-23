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
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class UploadFile(Base):
    """上传文件模型类"""
    __tablename__ = "upload_file"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_upload_file_id"),
        Index("idx_upload_file_account_id_name", "account_id", "name"),
        {"comment": "上传文件表"},
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
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="文件名")
    key: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="存储对象路径（COS为对象路径，MinIO为文件访问URL）")
    size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="文件大小（字节）")
    extension: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="文件扩展名")
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="MIME类型")
    hash: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="文件内容哈希")
