#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : user_memory.py
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class UserMemoryFact(Base):
    """用户事实记忆（语义记忆）—— 用户画像卡片，双时间机制。

    有效区间（valid_from/valid_to）：事实在现实世界何时为真；
    事务时间（tx_created_at/tx_invalidated_at）：系统何时写入/作废。
    旧事实失效不删除，保留历史以支持时间点回溯与审计。
    """
    __tablename__ = "user_memory_fact"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_user_memory_fact_id"),
        {"comment": "用户事实记忆表（用户画像，语义记忆）"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="应用命名空间")
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属用户ID（按用户隔离）")
    fact_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="事实键：location/occupation/preference:xxx")
    fact_value: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="结构化事实值")
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"), comment="来源：user_explicit/llm_inferred/tool/system")
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"), comment="信任加权 0~1")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"), comment="LLM提取置信度 0~1")
    is_implicit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="是否隐式推断")
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="有效区间开始（现实世界生效时间）")
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="有效区间结束，NULL=当前有效")
    tx_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="事务写入时间")
    tx_invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="事务作废时间，NULL=未作废")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        comment="更新时间",
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
