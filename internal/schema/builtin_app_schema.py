#!/usr/bin/env python
"""
@Time    : 2026/1/23 20:47
@Author  : sunxiaojie
@File    : builtin_app_schema.py
"""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.core.builtin_apps.entities.builtin_app_entity import BuiltinAppEntity
from internal.core.builtin_apps.entities.category_entity import CategoryEntity


class GetBuiltinAppCategoriesResp(BaseModel):
    """获取内置应用分类列表响应"""
    category: str = ""
    name: str = ""

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if isinstance(data, CategoryEntity):
            return data.model_dump()
        return data


class GetBuiltinAppsResp(BaseModel):
    """获取内置应用实体列表响应"""
    id: str = ""
    category: str = ""
    name: str = ""
    icon: str = ""
    description: str = ""
    model_config_data: dict = Field(default_factory=dict, alias="model_config")
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if isinstance(data, BuiltinAppEntity):
            return {
                **data.model_dump(include={"id", "category", "name", "icon", "description", "created_at"}),
                "model_config": {
                    "provider": data.language_model_config.get("provider", ""),
                    "model": data.language_model_config.get("model", "")
                }
            }
        return data


class AddBuiltinAppToSpaceReq(BaseModel):
    """添加内置应用到个人空间请求"""
    builtin_app_id: str = Field(description="内置工具id格式必须为UUID")

    @field_validator("builtin_app_id")
    @classmethod
    def validate_builtin_app_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("内置应用id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("内置工具id格式必须为UUID")
        return v
