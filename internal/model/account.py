#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 16:24
@Author : sunxiaojie
@File   : account.py
"""
from datetime import datetime

from sqlalchemy import UUID, DateTime, Index, PrimaryKeyConstraint, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class Account(Base):
    """账号模型"""
    __tablename__ = "account"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_account_id"),
        Index("account_email_idx", "email"),
        {"comment": "账号表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                 server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="更新人ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="账号名称")
    email: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="邮箱")
    avatar: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="头像URL")
    password: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                    server_default=text("''::character varying"), comment="密码（加密存储）")
    password_salt: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                         server_default=text("''::character varying"), comment="密码盐值")
    assistant_agent_conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=True, comment="助手智能体会话ID")
    last_login_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                    server_default=text("CURRENT_TIMESTAMP(0)"), comment="最后登录时间")
    last_login_ip: Mapped[str] = mapped_column(String(255), nullable=False,
                                               server_default=text("''::character varying"), comment="最后登录IP")

    @property
    def is_password_set(self) -> bool:
        """只读属性，获取当前账号的密码是否设置"""
        return bool(self.password)


class AccountOAuth(Base):
    __tablename__ = "account_oauth"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_account_oauth"),
        Index("account_oauth_id_idx", "account_id"),
        Index("account_op_idx", "openid", "provider"),
        {"comment": "账号第三方登录绑定表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="更新人ID")
    account_id: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="关联账号ID")
    provider: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="第三方登录提供商（如 github）")
    openid: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="第三方平台用户唯一标识")
    encrypted_token: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                        server_default=text("''::character varying"), comment="加密的第三方访问令牌")
