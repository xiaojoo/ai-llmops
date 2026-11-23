#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/25 21:12
@Author : sunxiaojie
@File   : tool_entity.py
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ToolParamType(str, Enum):
    """工具参数类型枚举类"""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"


class ToolParam(BaseModel):
    """工具参数类型"""
    name: str  # 参数的实际名字
    label: str  # 参数的展示标签
    type: ToolParamType  # 参数类型
    required: bool = False  # 是否必填
    default: Any | None = None  # 默认值
    min: float | None = None  # 最小值
    max: float | None = None  # 最大值
    options: list[dict[str, Any]] = Field(default_factory=list)  # 下拉菜单选项列表


class ToolEntity(BaseModel):
    """工具实体类，存储的信息映射是工具名.yaml的数据"""
    name: str
    label: str
    description: str
    params: list[ToolParam] = Field(default_factory=list)  # 工具参数信息
