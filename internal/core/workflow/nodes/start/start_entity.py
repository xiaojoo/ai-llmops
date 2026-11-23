#!/usr/bin/env python
"""
@Time    : 2026/1/24 18:56
@Author  : sunxiaojie
@File    : start_entity.py
"""
from pydantic import Field

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import VariableEntity


class StartNodeData(BaseNodeData):
    """开始节点数据"""
    inputs: list[VariableEntity] = Field(default_factory=list)  # 开始节点的输入变量信息
