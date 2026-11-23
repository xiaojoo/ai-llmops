#!/usr/bin/env python
"""
@Time    : 2026/1/25 23:50
@Author  : sunxiaojie
@File    : workflow_schema.py
"""
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.core.workflow.entities.workflow_entity import WORKFLOW_CONFIG_NAME_PATTERN
from internal.entity.workflow_entity import WorkflowStatus
from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class CreateWorkflowReq(BaseModel):
    """创建工作流基础请求"""
    name: str = Field(max_length=50, description="工作流名称长度不能超过50")
    tool_call_name: str = Field(max_length=50, description="英文名称不能超过50个字符")
    icon: str = Field(description="工作流图标必须是图片URL地址")
    description: str = Field(max_length=255, description="工作流长度不能超过255个字符")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工作流名称不能为空")
        return v

    @field_validator("tool_call_name")
    @classmethod
    def validate_tool_call_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("英文名称不能为空")
        if not re.match(WORKFLOW_CONFIG_NAME_PATTERN, v):
            raise ValueError("英文名称仅支持字母、数字和下划线，且以字母/下划线为开头")
        return v

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工作流图标不能为空")
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("工作流图标必须是图片URL地址")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工作流描述不能为空")
        return v


class UpdateWorkflowReq(BaseModel):
    """更新工作流基础请求"""
    name: str = Field(max_length=50, description="工作流名称长度不能超过50")
    tool_call_name: str = Field(max_length=50, description="英文名称不能超过50个字符")
    icon: str = Field(description="工作流图标必须是图片URL地址")
    description: str = Field(max_length=255, description="工作流长度不能超过255个字符")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工作流名称不能为空")
        return v

    @field_validator("tool_call_name")
    @classmethod
    def validate_tool_call_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("英文名称不能为空")
        if not re.match(WORKFLOW_CONFIG_NAME_PATTERN, v):
            raise ValueError("英文名称仅支持字母、数字和下划线，且以字母/下划线为开头")
        return v

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工作流图标不能为空")
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("工作流图标必须是图片URL地址")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("工作流描述不能为空")
        return v


class GetWorkflowResp(BaseModel):
    """获取工作流详情响应结构"""
    id: UUID | None = None
    name: str = ""
    tool_call_name: str = ""
    icon: str = ""
    description: str = ""
    status: str = ""
    is_debug_passed: bool = False
    node_count: int = 0
    published_at: int = 0
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "tool_call_name"):
            return {
                "id": data.id,
                "name": data.name,
                "tool_call_name": data.tool_call_name,
                "icon": data.icon,
                "description": data.description,
                "status": data.status,
                "is_debug_passed": data.is_debug_passed,
                "node_count": len(data.draft_graph.get("nodes", [])),
                "published_at": datetime_to_timestamp(data.published_at),
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class GetWorkflowsWithPageReq(PaginatorReq):
    """获取工作流分页列表数据请求结构"""
    status: str = ""
    search_word: str = ""

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v and v not in WorkflowStatus.__members__.values():
            raise ValueError("工作流状态格式错误")
        return v


class GetWorkflowsWithPageResp(BaseModel):
    """获取工作流分页列表数据响应结构"""
    id: UUID | None = None
    name: str = ""
    tool_call_name: str = ""
    icon: str = ""
    description: str = ""
    status: str = ""
    is_debug_passed: bool = False
    node_count: int = 0
    published_at: int = 0
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "tool_call_name"):
            return {
                "id": data.id,
                "name": data.name,
                "tool_call_name": data.tool_call_name,
                "icon": data.icon,
                "description": data.description,
                "status": data.status,
                "is_debug_passed": data.is_debug_passed,
                "node_count": len(data.graph.get("nodes", [])),
                "published_at": datetime_to_timestamp(data.published_at),
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data
