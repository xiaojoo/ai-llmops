#!/usr/bin/env python
"""
@Time    : 2026/1/20 21:33
@Author  : sunxiaojie
@File    : api_key_schema.py
"""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.lib.helper import datetime_to_timestamp


class CreateApiKeyReq(BaseModel):
    """创建API秘钥请求"""
    is_active: bool = False
    remark: str = Field(default="", description="秘钥备注不能超过100个字符")

    @field_validator("remark")
    @classmethod
    def validate_remark(cls, v: str) -> str:
        if v and len(v) > 100:
            raise ValueError("秘钥备注不能超过100个字符")
        return v


class UpdateApiKeyReq(BaseModel):
    """更新API秘钥请求"""
    is_active: bool = False
    remark: str = Field(default="", description="秘钥备注不能超过100个字符")

    @field_validator("remark")
    @classmethod
    def validate_remark(cls, v: str) -> str:
        if v and len(v) > 100:
            raise ValueError("秘钥备注不能超过100个字符")
        return v


class UpdateApiKeyIsActiveReq(BaseModel):
    """更新API秘钥激活状态请求"""
    is_active: bool = False


class GetApiKeysWithPageResp(BaseModel):
    """获取API秘钥分页列表数据"""
    id: UUID | None = None
    api_key: str = ""
    is_active: bool = False
    remark: str = ""
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "api_key"):
            return {
                "id": data.id,
                "api_key": data.api_key,
                "is_active": data.is_active,
                "remark": data.remark,
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data
