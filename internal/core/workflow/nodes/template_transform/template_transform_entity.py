#!/usr/bin/env python
"""
@Time    : 2026/1/24 23:49
@Author  : sunxiaojie
@File    : template_transform_entity.py
"""
from pydantic import Field, field_validator

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import (
    VariableEntity,
    VariableValueType,
)


class TemplateTransformNodeData(BaseNodeData):
    """模板转换节点数据"""
    template: str = ""  # 需要拼接转换的字符串模板
    inputs: list[VariableEntity] = Field(default_factory=list)  # 输入列表信息
    outputs: list[VariableEntity] = Field(
        default_factory=lambda: [
            VariableEntity(name="output", value={"type": VariableValueType.GENERATED})
        ]
    )

    @field_validator("outputs", mode="before")
    @classmethod
    def validate_outputs(cls, value):
        return [
            VariableEntity(
                name="output",
                value={"type": VariableValueType.GENERATED},
            )
        ]
