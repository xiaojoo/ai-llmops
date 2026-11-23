#!/usr/bin/env python
"""
@Time    : 2026/1/24 18:44
@Author  : sunxiaojie
@File    : base_node.py
"""
from abc import ABC
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig, RunnableSerializable
from pydantic import PrivateAttr

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import (
    BaseNodeData,
    NodeResult,
    NodeStatus,
    NodeType,
)
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.utils.subgraph import is_end_reachable
from internal.exception.exception import extract_exception_message


class BaseNode(RunnableSerializable, ABC):
    """工作流节点基类"""
    node_data: BaseNodeData
    _graph_edges: list[BaseEdgeData] = PrivateAttr(default_factory=list)
    _start_node_id: UUID | None = PrivateAttr(default=None)
    _end_node_id: UUID | None = PrivateAttr(default=None)

    def set_graph_context(
            self,
            edges: list[BaseEdgeData],
            start_node_id: UUID,
            end_node_id: UUID,
    ):
        """注入图的静态信息（边列表 + 起点 + 终点），供失败语义判断使用"""
        self._graph_edges = edges
        self._start_node_id = start_node_id
        self._end_node_id = end_node_id

    def invoke(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """统一节点执行入口：前置跳过检查 + 异常捕获，LangGraph调度时调用"""
        # 1、前置检查，命中则跳过
        skip_reason = self._check_skip(state)
        if skip_reason:
            return self._result(NodeStatus.SKIPPED, error=skip_reason)

        # 2、执行节点核心逻辑
        try:
            return self.run(state, config=config, **kwargs)
        except Exception as e:
            # 3、异常不抛出，转为失败节点结果，保证其他分支可以继续执行
            return self._result(NodeStatus.FAILED, error=extract_exception_message(e))

    def _check_skip(self, state: WorkflowState) -> str:
        """返回跳过原因字符串，空字符串代表不跳过"""
        failed_ids = {UUID(str(f)) for f in state.get("failed_nodes", [])}
        if not failed_ids:
            return ""

        # 以下判定仅针对非END节点：
        # - END节点作为终点不跳过：按可用数据产出部分结果（失败引用降级为默认值），
        #   只有所有输出源都失败时才在 EndNode.run 中抛出全局失败；
        # - 非END节点：引用/前驱失败或END不可达 → 跳过。
        if self.node_data.node_type != NodeType.END:
            # 1、REF引用来源失败 → 跳过（数据依赖断裂）
            for variable in self._node_variables():
                if variable.value.type == VariableValueType.REF:
                    ref_node_id = variable.value.content.ref_node_id
                    if ref_node_id and UUID(str(ref_node_id)) in failed_ids:
                        return f"引用节点[{ref_node_id}]执行失败，本节点跳过"

            # 2、任一直接前驱失败 → 跳过（分支断裂）
            for edge in self._graph_edges:
                if edge.target == self.node_data.id and edge.source in failed_ids:
                    return f"上游节点[{edge.source}]执行失败，本节点跳过"

            # 3、全局判定：END不再可达 → 跳过
            if self._end_node_id and not is_end_reachable(
                    self._start_node_id, self._end_node_id, self._graph_edges, list(failed_ids)
            ):
                return "工作流必经路径已失败，本节点跳过"

        return ""

    def _node_variables(self):
        """获取节点用于依赖判定的变量列表（非START用inputs，END用outputs）"""
        if self.node_data.node_type == NodeType.START:
            return []
        if self.node_data.node_type == NodeType.END:
            return getattr(self.node_data, "outputs", [])
        return getattr(self.node_data, "inputs", [])

    def _result(self, status: NodeStatus, error: str = "") -> WorkflowState:
        """构建节点结果 + 失败节点登记"""
        return {
            "node_results": [
                NodeResult(node_data=self.node_data, status=status, error=error)
            ],
            "failed_nodes": (
                [self.node_data.id]
                if status in (NodeStatus.FAILED, NodeStatus.SKIPPED)
                else []
            ),
        }

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """节点核心逻辑，由子类实现（替代原invoke）"""
        raise NotImplementedError
