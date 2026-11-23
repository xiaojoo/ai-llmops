#!/usr/bin/env python
"""
@Time    : 2026/1/24 18:09
@Author  : sunxiaojie
@File    : node_entity.py
"""
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny


class NodeType(str, Enum):
    """节点类型枚举"""
    START = "start"
    LLM = "llm"
    TOOL = "tool"
    CODE = "code"
    DATASET_RETRIEVAL = "dataset_retrieval"
    HTTP_REQUEST = "http_request"
    TEMPLATE_TRANSFORM = "template_transform"
    END = "end"


class BaseNodeData(BaseModel):
    """基础节点数据"""
    # 允许通过字段名进行赋值
    model_config = ConfigDict(
        validate_by_name=True,
    )

    class Position(BaseModel):
        """节点坐标基础模型"""
        x: float = 0
        y: float = 0

    id: UUID  # 节点id，数值必须唯一
    node_type: NodeType  # 节点类型
    title: str = ""  # 节点标题，数据也必须唯一
    description: str = ""  # 节点描述信息
    position: Position = Field(default_factory=lambda: {"x": 0, "y": 0})  # 节点对应坐标信息


class NodeStatus(str, Enum):
    """节点状态"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeResult(BaseModel):
    """节点运行结果"""
    # node_data: BaseNodeData  # 节点基础数据
    node_data: SerializeAsAny[BaseNodeData]  # 节点基础数据
    status: NodeStatus = NodeStatus.RUNNING  # 节点运行状态
    inputs: dict[str, Any] = Field(default_factory=dict)  # 节点的输入数据
    outputs: dict[str, Any] = Field(default_factory=dict)  # 节点的输出数据
    latency: float = 0  # 节点响应耗时
    error: str = ""  # 节点运行错误信息
