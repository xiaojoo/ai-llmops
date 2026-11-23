#!/usr/bin/env python
"""
@Time    : 2026/3/22 22:01
@Author  : sunxiaojie
@File    : chroma_vector_schema.py
"""
from pydantic import BaseModel, Field, field_validator


class ListVectorsReq(BaseModel):
    """分页查询向量列表请求"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")


class AddVectorReq(BaseModel):
    """新增向量记录请求"""
    id: str = Field(..., min_length=1, description="文档 ID")
    content: str = Field(..., min_length=1, description="文档内容")
    metadata: dict = Field(default_factory=dict, description="元数据")

    @field_validator("id", "content", mode="before")
    @classmethod
    def strip_str(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v


class UpdateVectorReq(BaseModel):
    """更新向量记录请求"""
    content: str = Field(..., min_length=1, description="文档内容")
    metadata: dict = Field(default_factory=dict, description="元数据")

    @field_validator("content", mode="before")
    @classmethod
    def strip_str(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v


class RecallTestReq(BaseModel):
    """召回测试请求"""
    query: str = Field(..., min_length=1, description="查询语句")
    top_k: int = Field(default=5, ge=1, le=10, description="返回条数，范围 1~10")

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v
