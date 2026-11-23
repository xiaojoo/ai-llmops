#!/usr/bin/env python
"""
@Time    : 2026/1/25 0:11
@Author  : sunxiaojie
@File    : dataset_retrieval_entity.py
"""
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from internal.core.workflow.entities.node_entity import BaseNodeData
from internal.core.workflow.entities.variable_entity import (
    VariableEntity,
    VariableType,
    VariableValueType,
)
from internal.entity.dataset_entity import RetrievalStrategy
from internal.exception import FailedException


class RerankConfig(BaseModel):
    """Rerank 精排配置"""
    enable: bool = False  # 是否启用 rerank
    top_n: int = 20  # 召回候选数（rerank 前先取 top_n 候选）


class QueryRewriteConfig(BaseModel):
    """查询改写配置"""
    enable: bool = False  # 是否启用查询改写


class RetrievalConfig(BaseModel):
    """检索配置"""
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.SEMANTIC  # 检索策略
    k: int = 4  # 最大召回数量
    score: float = 0  # 得分阈值
    rerank: RerankConfig = RerankConfig()  # rerank 配置
    query_rewrite: QueryRewriteConfig = QueryRewriteConfig()  # 查询改写配置


class DatasetRetrievalNodeData(BaseNodeData):
    """知识库检索节点数据"""
    dataset_ids: list[UUID]  # 关联的知识库id列表
    retrieval_config: RetrievalConfig = RetrievalConfig()  # 检索配置
    inputs: list[VariableEntity] = Field(default_factory=list)  # 输入变量信息
    outputs: list[VariableEntity] = Field(
        default_factory=lambda: [
            VariableEntity(name="combine_documents", value={"type": VariableValueType.GENERATED})
        ]
    )

    @field_validator("outputs", mode="before")
    @classmethod
    def validate_outputs(cls, value):
        return [
            VariableEntity(
                name="combine_documents",
                value={"type": VariableValueType.GENERATED},
            )
        ]

    @field_validator("inputs", mode="after")
    @classmethod
    def validate_inputs(cls, value: list[VariableEntity]):
        """校验输入变量信息"""

        # 1、判断是否只有一个输入变量
        if len(value) != 1:
            raise ValueError("知识库节点输入变量信息出错")

        # 2、校验输入变量的类型及字段名称
        query_input: VariableEntity = value[0]
        if (
                query_input.name != "query"
                or query_input.type != VariableType.STRING
                or query_input.required is False
        ):
            raise FailedException("知识库节点输入变量名字/变量类型/必填属性出错")

        return value
