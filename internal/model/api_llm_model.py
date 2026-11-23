from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class ApiLlmModel(Base):
    """自定义 API 大语言模型表：用户按账号添加的 OpenAI/Anthropic/Responses 兼容模型。"""
    __tablename__ = "api_llm_model"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_api_llm_model_id"),
        {"comment": "自定义 API 大语言模型表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), comment="更新时间")
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="更新人ID")
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属账号ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="展示名（模型选择器显示）")
    protocol: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("''::character varying"), comment="协议：openai / responses / anthropic")
    model_id: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="请求体 model 字段")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="端点地址（可空）")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="API Key（AES 加密存储）")
    features: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="能力标记：tool_call/agent_thought/image_input")
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="上下文窗口长度")
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="最大输出 tokens")
    remark: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="备注")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="图标URL")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
