#!/usr/bin/env python
"""
@Time    : 2026/1/24 23:50
@Author  : sunxiaojie
@File    : template_transform_node.py
"""
import time

from jinja2 import Template
from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state

from .template_transform_entity import TemplateTransformNodeData


class TemplateTransformNode(BaseNode):
    """模板转换节点，将多个变量信息合并成一个"""
    node_data: TemplateTransformNodeData

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs) -> WorkflowState:
        """模板转换节点执行函数，将传递的多个变量合并成字符串后返回"""
        # 1、提取节点中的输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2、使用jinja2格式模板信息
        template = Template(self.node_data.template)
        template_value = template.render(**inputs_dict)

        # 3、提取并构建输出数据结构
        outputs = {"output": template_value}

        # 4、构建响应状态并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }
