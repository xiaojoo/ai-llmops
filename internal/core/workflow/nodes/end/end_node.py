#!/usr/bin/env python
"""
@Time    : 2026/1/24 19:20
@Author  : sunxiaojie
@File    : end_node.py
"""
import time
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailedException

from .end_entity import EndNodeData


class EndNode(BaseNode):
    """结束节点"""
    node_data: EndNodeData

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs) -> WorkflowState:
        """结束节点执行函数：按可用数据产出部分结果（失败引用降级为默认值）。

        仅当所有输出引用源都执行失败时，才抛出全局失败（此时无法产出任何结果）。
        """
        # 1、提取节点中需要输出的数据
        start_at = time.perf_counter()

        # 2、检测是否所有输出引用源都失败（全部失败则视为全局失败，无法产出结果）
        failed_ids = {UUID(str(f)) for f in state.get("failed_nodes", [])}
        if failed_ids:
            ref_sources = [
                variable.value.content.ref_node_id
                for variable in self.node_data.outputs
                if variable.value.type == VariableValueType.REF
                and variable.value.content.ref_node_id
            ]
            if ref_sources and all(UUID(str(source)) in failed_ids for source in ref_sources):
                raise FailedException("工作流所有输出数据源执行失败，无法产出结果")

        # 3、提取输出数据：健康引用正常取值，失败引用在 helper 中降级为类型默认值
        outputs_dict = extract_variables_from_state(self.node_data.outputs, state)

        # 4、组装状态并返回
        return {
            "outputs": outputs_dict,
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED,
                    inputs={},
                    outputs=outputs_dict,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }
