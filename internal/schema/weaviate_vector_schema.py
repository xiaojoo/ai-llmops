#!/usr/bin/env python
"""
@Time    : 2026/3/23 1:01
@Author  : sunxiaojie
@File    : weaviate_vector_schema.py
"""
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WeaviateRecallReq(BaseModel):
    """向量召回请求"""
    dataset_id: str = Field(description="dataset_id格式错误")
    document_id: str | None = Field(default=None, description="document_id格式错误")
    query: str = Field(description="查询文本不能为空")
    top_k: int = Field(default=5, description="top_k范围1-100")
    score_threshold: float = Field(default=0.0, description="score_threshold范围0-1")

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("dataset_id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("dataset_id格式错误")
        return v

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            try:
                UUID(v)
            except ValueError:
                raise ValueError("document_id格式错误")
        return v

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("查询文本不能为空")
        if len(v) > 2000:
            raise ValueError("查询文本长度不能超过2000")
        return v

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("top_k范围1-100")
        return v

    @field_validator("score_threshold")
    @classmethod
    def validate_score_threshold(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("score_threshold范围0-1")
        return v


class WeaviateDeleteDocumentReq(BaseModel):
    """删除文档请求"""
    dataset_id: str = Field(description="dataset_id格式错误")

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("dataset_id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("dataset_id格式错误")
        return v


class WeaviateDeleteMemoryReq(BaseModel):
    """删除记忆集合数据请求（按 app_id 清空，记忆集合无 dataset_id）"""
    collection_name: str = Field(description="集合名称不能为空")
    app_id: str = Field(description="app_id格式错误")

    @field_validator("collection_name")
    @classmethod
    def validate_collection_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("collection_name不能为空")
        return v.strip()

    @field_validator("app_id")
    @classmethod
    def validate_app_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("app_id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("app_id格式错误")
        return v
