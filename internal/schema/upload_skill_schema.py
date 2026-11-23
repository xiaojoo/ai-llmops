#!/usr/bin/env python
"""
@Time    : 2026/3/20 18:35
@Author  : sunxiaojie
@File    : upload_skill_schema.py
"""
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from internal.model import Skill
from package.paginator import PaginatorReq


class UploadSkillSchema(BaseModel):
    """上传 Skill 文件的请求校验"""
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def name_format(cls, name: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
            raise ValueError("name只允许字母、数字、下划线")
        return name

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, description: str) -> str:
        if not description.strip():
            raise ValueError("description 不能为空字符串")
        return description.strip()


def datetime_to_timestamp(dt: datetime | None) -> int:
    return int(dt.timestamp()) if dt else 0


class SkillResp(BaseModel):
    """技能详情响应结构"""
    id: UUID | None = None
    name: str = ""
    description: str = ""
    icon: str = ""
    visibility: str = "private"
    is_owner: bool = False
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if isinstance(data, Skill):
            return {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "icon": data.icon or "",
                "visibility": data.visibility or "private",
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class GetSkillListWithPageReq(PaginatorReq):
    """获取技能分页列表请求"""
    search_word: str = Field(default="", max_length=60)
