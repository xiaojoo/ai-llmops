#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 23:53
@Author : sunxiaojie
@File   : dataset_schema.py
"""
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.entity.dataset_entity import RetrievalStrategy
from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class CreateOrUpdateDatasetReq(BaseModel):
    """创建/更新知识库请求"""
    name: str = Field(max_length=100, description="知识库名称长度不能超过100字符")
    icon: str = Field(description="知识库图标必须是图片URL地址")
    description: str = Field(default="", max_length=2000, description="知识库描述长度不能超过2000字符")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("知识库名称不能为空")
        return v

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("知识库图标不能为空")
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("知识库图标必须是图片URL地址")
        return v


class GetDatasetResp(BaseModel):
    """获取知识库详情响应结构"""
    id: UUID | None = None
    name: str = ""
    icon: str = ""
    description: str = ""
    document_count: int = 0
    hit_count: int = 0
    related_app_count: int = 0
    character_count: int = 0
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "document_count"):
            return {
                "id": data.id,
                "name": data.name,
                "icon": data.icon,
                "description": data.description,
                "document_count": data.document_count,
                "hit_count": data.hit_count,
                "related_app_count": data.related_app_count,
                "character_count": data.character_count,
                "updated_at": int(data.updated_at.timestamp()),
                "created_at": int(data.created_at.timestamp()),
            }
        return data


class GetDatasetsWithPageReq(PaginatorReq):
    """获取知识库分页列表请求数据"""
    search_word: str = ""


class GetDatasetsWithPageResp(BaseModel):
    """获取知识库分页列表响应数据"""
    id: UUID | None = None
    name: str = ""
    icon: str = ""
    description: str = ""
    document_count: int = 0
    related_app_count: int = 0
    character_count: int = 0
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "document_count"):
            return {
                "id": data.id,
                "name": data.name,
                "icon": data.icon,
                "description": data.description,
                "document_count": data.document_count,
                "related_app_count": data.related_app_count,
                "character_count": data.character_count,
                "updated_at": int(data.updated_at.timestamp()),
                "created_at": int(data.created_at.timestamp()),
            }
        return data


class HitReq(BaseModel):
    """知识库召回测试请求"""
    query: str = Field(description="查询语句最大长度不能超过200")
    retrieval_strategy: str = Field(description="检索策略格式错误")
    k: int = Field(description="最大召回数量的范围在1-10")
    score: float = Field(default=0.0, description="最小匹配度范围在0-0.99")
    agentic_enable: bool = False
    max_rounds: int = Field(default=2, description="agentic 重检轮数范围在1-3")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("查询语句不能为空")
        if len(v) > 200:
            raise ValueError("查询语句最大长度不能超过200")
        return v

    @field_validator("retrieval_strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        valid_values = [item.value for item in RetrievalStrategy]
        if v not in valid_values:
            raise ValueError("检索策略格式错误")
        return v

    @field_validator("k")
    @classmethod
    def validate_k(cls, v: int) -> int:
        if v is None:
            raise ValueError("最大召回数量不能为空")
        if v < 1 or v > 10:
            raise ValueError("最大召回数量的范围在1-10")
        return v

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        if v < 0 or v > 0.99:
            raise ValueError("最小匹配度范围在0-0.99")
        return v

    @field_validator("max_rounds")
    @classmethod
    def validate_max_rounds(cls, v: int) -> int:
        if v < 1 or v > 3:
            raise ValueError("agentic 重检轮数范围在1-3")
        return v


class GetDatasetQueriesResp(BaseModel):
    """获取知识库最近查询响应结构"""
    id: UUID | None = None
    dataset_id: UUID | None = None
    query: str = ""
    source: str = ""
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "dataset_id"):
            return {
                "id": data.id,
                "dataset_id": data.dataset_id,
                "query": data.query,
                "source": data.source,
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data
