#!/usr/bin/env python
"""
@Time    : 2026/1/24 17:48
@Author  : sunxiaojie
@File    : workflow.py
"""
from collections.abc import Iterator
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.utils import Input, Output
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph, StateGraph
from pydantic import BaseModel, Field, PrivateAttr, create_model

from .entities.node_entity import NodeType
from .entities.variable_entity import VARIABLE_TYPE_MAP
from .entities.workflow_entity import WorkflowConfig, WorkflowState
from .nodes import (
    CodeNode,
    DatasetRetrievalNode,
    EndNode,
    HttpRequestNode,
    LLMNode,
    StartNode,
    TemplateTransformNode,
    ToolNode,
)

# 节点类映射
NodeClasses = {
    NodeType.START: StartNode,
    NodeType.END: EndNode,
    NodeType.LLM: LLMNode,
    NodeType.TEMPLATE_TRANSFORM: TemplateTransformNode,
    NodeType.DATASET_RETRIEVAL: DatasetRetrievalNode,
    NodeType.CODE: CodeNode,
    NodeType.TOOL: ToolNode,
    NodeType.HTTP_REQUEST: HttpRequestNode,
}


class Workflow(BaseTool):
    """工作流LangChain工具类"""
    _workflow_config: WorkflowConfig = PrivateAttr(None)
    _workflow: CompiledStateGraph = PrivateAttr(None)

    def __init__(self, workflow_config: WorkflowConfig, **kwargs: Any):
        """构造函数，完成工作流函数的初始化"""
        # 1、调用父类构造函数完成基础数据初始化
        super().__init__(
            name=workflow_config.name,
            description=workflow_config.description,
            args_schema=self._build_args_schema(workflow_config),
            **kwargs
        )

        # 2、完善工作流配置与工作流图结构程序的初始化
        self._workflow_config = workflow_config
        self._workflow = self._build_workflow()

    @classmethod
    def _build_args_schema(cls, workflow_config: WorkflowConfig) -> type[BaseModel]:
        """构建输入参数结构体"""
        # 1、提取开始节点的输入参数信息
        fields = {}
        inputs = next(
            (node.inputs for node in workflow_config.nodes if node.node_type == NodeType.START),
            []
        )

        # 2、循环遍历所有输入信息并创建字段映射
        for input in inputs:
            field_name = input.name
            field_type = VARIABLE_TYPE_MAP.get(input.type, str)
            field_required = input.required
            field_description = input.description

            if field_required:
                fields[field_name] = (
                    field_type,
                    Field(description=field_description),
                )
            else:
                fields[field_name] = (
                    Optional[field_type],  # noqa: UP045 运行时类型工厂，非注解
                    Field(default=None, description=field_description),
                )

        return create_model("DynamicModel", **fields)

    def _build_workflow(self) -> CompiledStateGraph:
        """构建编译后的工作流图程序"""
        # 1、创建graph图程序结构
        graph = StateGraph(WorkflowState)

        # 2、提取nodes和edges信息
        nodes = self._workflow_config.nodes
        edges = self._workflow_config.edges

        # 3、提取图起点/终点节点（用于注入节点上下文做失败语义判断）
        start_node_data = next(node for node in nodes if node.node_type == NodeType.START)
        end_node_data = next(node for node in nodes if node.node_type == NodeType.END)

        # 4、循环遍历nodes节点信息添加节点
        for node in nodes:
            node_flag = f"{node.node_type.value}_{node.id}"
            if node.node_type in (NodeType.DATASET_RETRIEVAL, NodeType.TOOL):
                # 知识库检索/工具节点需要账号信息（租户隔离：检索本人知识库、加载本人API工具）
                node_instance = NodeClasses[node.node_type](
                    account_id=self._workflow_config.account_id,
                    node_data=node,
                )
            else:
                node_instance = NodeClasses[node.node_type](node_data=node)

            # 5、注入图的静态信息（边列表+起点+终点），供失败语义判断使用
            node_instance.set_graph_context(
                edges=edges,
                start_node_id=start_node_data.id,
                end_node_id=end_node_data.id,
            )
            graph.add_node(node_flag, node_instance)

        # 4、循环遍历edges信息添加边
        parallel_edges = {}  # key：终点，value：起点列表
        start_node = ""
        end_node = ""
        for edge in edges:
            # 5、计算并过期并行边
            source_node = f"{edge.source_type.value}_{edge.source}"
            target_node = f"{edge.target_type.value}_{edge.target}"
            if target_node not in parallel_edges:
                parallel_edges[target_node] = [source_node]
            else:
                parallel_edges[target_node].append(source_node)

            # 6、检测特殊节点（开始节点、结束节点）
            if edge.source_type == NodeType.START:
                start_node = f"{edge.source_type.value}_{edge.source}"
            if edge.target_type == NodeType.END:
                end_node = f"{edge.target_type.value}_{edge.target}"

        # 7、设置开始和终点
        graph.set_entry_point(start_node)
        graph.set_finish_point(end_node)

        # 8、循环遍历合并边
        for target_node, source_nodes in parallel_edges.items():
            graph.add_edge(source_nodes, target_node)

        # 9、构建图程序并编译
        return graph.compile()

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """工作流组件基础run方法"""
        # 1、调用工作流获取结果信息
        result = self._workflow.invoke({"inputs": kwargs, "failed_nodes": []})

        # 2、提取响应结果的outputs内容作为输出
        return result.get("outputs", {})

    def stream(
            self,
            input: Input,
            config: RunnableConfig | None = None,
            *args: Any,
            **kwargs: Any
    ) -> Iterator[Output]:
        """工作流式输出每个节点对应的结果"""
        return self._workflow.stream({"inputs": input, "failed_nodes": []})
