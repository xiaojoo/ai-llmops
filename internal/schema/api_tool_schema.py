#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/27 15:36
@Author : sunxiaojie
@File   : api_tool_schema.py
"""
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.exception import ValidateException
from package.paginator import PaginatorReq


class ValidateOpenAPISchemaReq(BaseModel):
    """校验OpenAPI规范字符串请求"""
    openapi_schema: str = Field(description="openapi_schema字符串不能为空")

    @field_validator("openapi_schema")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("openapi_schema字符串不能为空")
        return v


class DebugApiToolReq(BaseModel):
    """调试API工具请求"""
    arguments: dict = Field(default_factory=dict)


class GetApiToolProvidersWithPageReq(PaginatorReq):
    """获取API工具提供者分页列表请求"""
    search_word: str = ""


class _ApiToolProviderMixin:
    """CreateApiToolReq / UpdateApiToolProviderReq 共享校验逻辑"""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工具提供者名字不能为空")
        if len(v) > 30:
            raise ValueError("工具提供者名字为1-30")
        return v

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工具提供者图标不能为空")
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("工具提供者的图标必须是URL链接")
        return v

    @field_validator("openapi_schema")
    @classmethod
    def validate_openapi_schema(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("openapi_schema字符串不能为空")
        return v

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, v: list[dict]) -> list[dict]:
        for header in v:
            if not isinstance(header, dict):
                raise ValueError("headers里的每一个元素都必须是字典")
            if set(header.keys()) != {"key", "value"}:
                raise ValueError("headers里的每一个元素都必须包含key/value两个属性，不允许有其他属性")
        return v


class CreateApiToolReq(_ApiToolProviderMixin, BaseModel):
    """创建自定义API工具请求"""
    name: str = Field(description="工具提供者名字为1-30")
    icon: str = Field(description="工具提供者图标必须是URL链接")
    openapi_schema: str = Field(description="openapi_schema字符串不能为空")
    headers: list[dict] = Field(default_factory=list)


class UpdateApiToolProviderReq(_ApiToolProviderMixin, BaseModel):
    """更新API工具提供者请求"""
    name: str = Field(description="工具提供者名字为1-30")
    icon: str = Field(description="工具提供者图标必须是URL链接")
    openapi_schema: str = Field(description="openapi_schema字符串不能为空")
    headers: list[dict] = Field(default_factory=list)


class GetApiToolProviderResp(BaseModel):
    """获取API工具提供者响应信息"""
    id: UUID | None = None
    name: str = ""
    icon: str = ""
    openapi_schema: str = ""
    headers: list[dict] = Field(default_factory=list)
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "openapi_schema"):
            return {
                "id": data.id,
                "name": data.name,
                "icon": data.icon,
                "openapi_schema": data.openapi_schema,
                "headers": data.headers,
                "created_at": int(data.created_at.timestamp()),
            }
        return data


class GetApiToolResp(BaseModel):
    """获取API工具参数详情响应"""
    id: UUID | None = None
    name: str = ""
    description: str = ""
    inputs: list[dict] = Field(default_factory=list)
    provider: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "parameters"):
            provider = data.provider
            return {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "inputs": [{k: v for k, v in parameter.items() if k != "in"} for parameter in data.parameters],
                "provider": {
                    "id": provider.id,
                    "name": provider.name,
                    "icon": provider.icon,
                    "description": provider.description,
                    "headers": provider.headers,
                }
            }
        return data


class GetApiToolProvidersWithPageResp(BaseModel):
    """获取API工具提供者分页列表数据响应"""
    id: UUID | None = None
    name: str = ""
    icon: str = ""
    description: str = ""
    headers: list[dict] = Field(default_factory=list)
    tools: list[dict] = Field(default_factory=list)
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "tools"):
            tools = data.tools
            return {
                "id": data.id,
                "name": data.name,
                "icon": data.icon,
                "description": data.description,
                "headers": data.headers,
                "tools": [{
                    "id": tool.id,
                    "description": tool.description,
                    "name": tool.name,
                    "inputs": [{k: v for k, v in parameter.items() if k != "in"} for parameter in tool.parameters]
                } for tool in tools],
                "created_at": int(data.created_at.timestamp())
            }
        return data
