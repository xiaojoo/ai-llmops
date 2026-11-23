#!/usr/bin/env python
"""
@Time    : 2026/1/25 16:05
@Author  : sunxiaojie
@File    : http_request_entity.py
"""

from pydantic import Field, HttpUrl, field_validator

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import (
    HttpRequestInputType,
    HttpRequestMethod,
    VariableEntity,
    VariableType,
    VariableValueType,
)
from internal.exception import ValidateException


class HttpRequestNodeData(BaseNodeData):
    """HTTP请求节点数据"""
    # url: HttpUrl = ""  # 请求URL地址
    # url: str = ""  # 请求URL地址
    url: HttpUrl | None = None  # 请求URL地址
    method: HttpRequestMethod = HttpRequestMethod.GET
    inputs: list[VariableEntity] = Field(default_factory=list)
    outputs: list[VariableEntity] = Field(
        default_factory=lambda: [
            VariableEntity(
                name="status_code",
                type=VariableType.INT,
                value={"type": VariableValueType.GENERATED, "content": 0},
            ),
            VariableEntity(name="text", value={"type": VariableValueType.GENERATED}),
        ],
    )

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, url: HttpUrl | None):
        return None if url == "" else url

    @field_validator("outputs", mode="before")
    @classmethod
    def validate_outputs(cls, value):
        return [
            VariableEntity(
                name="status_code",
                type=VariableType.INT,
                value={"type": VariableValueType.GENERATED, "content": 0},
            ),
            VariableEntity(name="text", value={"type": VariableValueType.GENERATED}),
        ]

    @field_validator("inputs", mode="after")
    @classmethod
    def validate_inputs(cls, inputs: list[VariableEntity]):
        for input_var in inputs:
            try:
                HttpRequestInputType(input_var.meta.get("type"))
            except ValueError:
                raise ValidateException("Http请求参数结构出错")
        return inputs
