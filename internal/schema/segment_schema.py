#!/usr/bin/env python
"""
@Time    : 2025/12/8 18:51
@Author  : sunxiaojie
@File    : segment_schema.py
"""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class GetSegmentsWithPageReq(PaginatorReq):
    """获取文档片段列表请求"""
    search_word: str = ""


class GetSegmentsWithPageResp(BaseModel):
    """获取文档片段列表响应结构"""
    id: UUID | None = None
    document_id: UUID | None = None
    dataset_id: UUID | None = None
    position: int = 0
    content: str = ""
    content_type: str = "text"
    image_url: str = ""
    page_number: int = 0
    section_title: str = ""
    footer: str = ""
    keywords: list[str] = Field(default_factory=list)
    character_count: int = 0
    token_count: int = 0
    hit_count: int = 0
    enabled: bool = False
    disabled_at: int = 0
    status: str = ""
    error: str = ""
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "content_type"):
            return {
                "id": data.id,
                "document_id": data.document_id,
                "dataset_id": data.dataset_id,
                "position": data.position,
                "content": data.content,
                "content_type": data.content_type or "text",
                "image_url": data.image_url or "",
                "page_number": data.page_number or 0,
                "section_title": data.section_title or "",
                "footer": data.footer or "",
                "keywords": data.keywords,
                "character_count": data.character_count,
                "token_count": data.token_count,
                "hit_count": data.hit_count,
                "enabled": data.enabled,
                "disabled_at": datetime_to_timestamp(data.disabled_at),
                "status": data.status,
                "error": data.error,
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class GetSegmentResp(BaseModel):
    """获取文档片段详情响应结构"""
    id: UUID | None = None
    document_id: UUID | None = None
    dataset_id: UUID | None = None
    position: int = 0
    content: str = ""
    content_type: str = "text"
    image_url: str = ""
    page_number: int = 0
    section_title: str = ""
    footer: str = ""
    keywords: list[str] = Field(default_factory=list)
    character_count: int = 0
    token_count: int = 0
    hit_count: int = 0
    hash: str = ""
    enabled: bool = False
    disabled_at: int = 0
    status: str = ""
    error: str = ""
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "content_type"):
            return {
                "id": data.id,
                "document_id": data.document_id,
                "dataset_id": data.dataset_id,
                "position": data.position,
                "content": data.content,
                "content_type": data.content_type or "text",
                "image_url": data.image_url or "",
                "page_number": data.page_number or 0,
                "section_title": data.section_title or "",
                "footer": data.footer or "",
                "keywords": data.keywords,
                "character_count": data.character_count,
                "token_count": data.token_count,
                "hit_count": data.hit_count,
                "hash": data.hash,
                "enabled": data.enabled,
                "disabled_at": datetime_to_timestamp(data.disabled_at),
                "status": data.status,
                "error": data.error,
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class UpdateSegmentEnabledReq(BaseModel):
    """更新文档启用状态请求"""
    enabled: bool = Field(description="enabled状态不能为空且必须为布尔值")


class CreateSegmentReq(BaseModel):
    """创建文档片段请求结构"""
    content: str = Field(description="片段内容不能为空")
    keywords: list[str] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("片段内容不能为空")
        return v

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, v: list[str]) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("关键词列表格式必须为数组")
        if len(v) > 10:
            raise ValueError("关键词长度范围数量在1-10")
        for keyword in v:
            if not isinstance(keyword, str):
                raise ValueError("关键词必须是字符串")
        # 删除重复数据并保持顺序
        return list(dict.fromkeys(v))
