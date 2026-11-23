#!/usr/bin/env python
"""
系统级配置表模型：存储 /settings 页面管理的部署与第三方配置。

- key：配置项名（如 OPENAI_API_KEY / WEAVIATE_HTTP_HOST）
- value：配置值；敏感项（is_encrypted=True）保存时用主密钥 AES 加密
- 运行时读取优先级：system_config（DB）> 环境变量 > 默认值
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class SystemConfig(Base):
    """系统配置表模型"""
    __tablename__ = "system_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_system_config_id"),
        {"comment": "系统配置表（存储部署与第三方配置）"},
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
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, comment="配置项名（如 OPENAI_API_KEY），唯一")
    value: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="配置值，敏感项为AES密文")
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否加密存储（敏感值true，读接口脱敏返回）")
    group: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("''::character varying"), comment="分组：llm / oss / database / redis / vector / third / feishu")
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="配置描述")
