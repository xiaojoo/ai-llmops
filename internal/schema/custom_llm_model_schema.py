from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.core.language_model.providers.custom_api.protocol import ALLOWED_FEATURES, ALL_PROTOCOLS


class _CustomModelMixin:
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("模型名称不能为空")
        if len(v) > 100:
            raise ValueError("模型名称最大100字符")
        return v

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("模型ID不能为空")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v not in ALL_PROTOCOLS:
            raise ValueError("协议必须为 openai / responses / anthropic")
        return v

    @field_validator("features")
    @classmethod
    def validate_features(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ALLOWED_FEATURES
        if unknown:
            raise ValueError(f"能力标记不合法: {sorted(unknown)}")
        return v

    @field_validator("context_window")
    @classmethod
    def validate_ctx(cls, v: int) -> int:
        if v < 0:
            raise ValueError("context_window 不能为负")
        return v

    @field_validator("max_output_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_output_tokens 不能为负")
        return v


class CreateCustomLlmModelReq(_CustomModelMixin, BaseModel):
    name: str = Field(description="模型名称（1-100）")
    protocol: str = Field(description="协议：openai / responses / anthropic")
    model_id: str = Field(description="请求体 model 字段")
    base_url: str = Field(default="", description="端点地址")
    api_key: str = Field(default="", description="API Key")
    features: list[str] = Field(default_factory=list, description="能力标记")
    context_window: int = Field(default=0, ge=0, description="上下文窗口长度")
    max_output_tokens: int = Field(default=0, ge=0, description="最大输出tokens")
    remark: str = Field(default="", description="备注")
    icon: str = Field(default="", description="图标URL")


class UpdateCustomLlmModelReq(_CustomModelMixin, BaseModel):
    name: str = Field(description="模型名称（1-100）")
    protocol: str = Field(description="协议")
    model_id: str = Field(description="请求体 model 字段")
    base_url: str = Field(default="", description="端点地址")
    api_key: str = Field(default="", description="API Key")
    features: list[str] = Field(default_factory=list, description="能力标记")
    context_window: int = Field(default=0, ge=0, description="上下文窗口长度")
    max_output_tokens: int = Field(default=0, ge=0, description="最大输出tokens")
    remark: str = Field(default="", description="备注")
    icon: str = Field(default="", description="图标URL")


class GetCustomLlmModelResp(BaseModel):
    id: UUID | None = None
    name: str = ""
    protocol: str = ""
    model_id: str = ""
    base_url: str = ""
    api_key: str = "********"
    features: list[str] = Field(default_factory=list)
    context_window: int = 0
    max_output_tokens: int = 0
    remark: str = ""
    icon: str = ""
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @field_validator("api_key")
    @classmethod
    def mask_api_key(cls, v: str) -> str:
        return "********"

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "protocol"):
            return {
                "id": data.id,
                "name": data.name,
                "protocol": data.protocol,
                "model_id": data.model_id,
                "base_url": data.base_url,
                "api_key": "********",
                "features": data.features or [],
                "context_window": data.context_window,
                "max_output_tokens": data.max_output_tokens,
                "remark": data.remark,
                "icon": data.icon,
                "created_at": int(data.created_at.timestamp()) if data.created_at else 0,
            }
        return data
