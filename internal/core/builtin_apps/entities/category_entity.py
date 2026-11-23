#!/usr/bin/env python
"""
@Time    : 2026/1/22 23:17
@Author  : sunxiaojie
@File    : category_entity.py
"""
from pydantic import BaseModel, Field


class CategoryEntity(BaseModel):
    """内置工具分类实体"""
    category: str = Field(default="")  # 分类唯一标识
    name: str = Field(default="")  # 分类对应的名称
