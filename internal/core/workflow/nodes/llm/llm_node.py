#!/usr/bin/env python
"""
@Time    : 2026/1/24 22:45
@Author  : sunxiaojie
@File    : llm_node.py
"""
import asyncio
import time

from jinja2 import Template
from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state

from .llm_entity import LLMNodeData


class LLMNode(BaseNode):
    """大语言模型节点"""
    node_data: LLMNodeData

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs) -> WorkflowState:
        """大语言模型节点调用工具，根据输入字段+预设prompt生成对应内容后输出"""

        # 1、提取节点中的输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2、使用jinja2格式模板信息
        template = Template(self.node_data.prompt)
        prompt_value = template.render(**inputs_dict)

        # 3、根据配置创建LLM实例，等待多LLM接入时需要完善
        # 直接构造 LanguageModelService（db 仅占位，load_language_model 不触库）。
        from internal.core.language_model import LanguageModelManager
        from internal.service.language_model_service import LanguageModelService

        language_model_service = LanguageModelService(
            db=None,
            language_model_manager=LanguageModelManager(),
        )
        # 子图调试（node_ids → 线性子图）时 langgraph 单任务 fast path 在主事件循环
        # inline 执行节点 → asyncio.run 抛 "cannot be called from a running event loop"；
        # run_sync_bridge 在运行中 loop 内丢新线程执行。
        from package.database import run_sync_bridge

        llm = run_sync_bridge(
            lambda: asyncio.run(
                language_model_service.load_language_model(self.node_data.language_model_config)
            )
        )

        # 4、调用LLM并传递prompt后提取数据
        content = ""
        for chunk in llm.stream(prompt_value):
            content += chunk.content

        # 5、提取并构建输出数据结构
        outputs = {}
        if self.node_data.outputs:
            outputs[self.node_data.outputs[0].name] = content
        else:
            outputs["output"] = content

        # 6、构建响应状态并返回
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
