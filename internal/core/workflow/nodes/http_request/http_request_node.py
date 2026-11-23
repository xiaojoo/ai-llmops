#!/usr/bin/env python
"""
@Time    : 2026/1/25 16:08
@Author  : sunxiaojie
@File    : http_request_node.py
"""
import time
from typing import Any

import requests
from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import (
    HttpRequestInputType,
    HttpRequestMethod,
)
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailedException

from .http_request_entity import HttpRequestNodeData


class HttpRequestNode(BaseNode):
    """HTTP请求节点"""
    node_data: HttpRequestNodeData

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """执行HTTP请求"""

        # 1、提取节点输入变量字典
        start_at = time.perf_counter()
        _inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2、提取数据，涵盖params、headers、body的数据
        inputs_dict = {
            HttpRequestInputType.PARAMS: {},
            HttpRequestInputType.HEADERS: {},
            HttpRequestInputType.BODY: {}
        }
        for input in self.node_data.inputs:
            inputs_dict[input.meta.get("type")][input.name] = _inputs_dict.get(input.name)

        # 3、请求方法映射
        request_methods = {
            HttpRequestMethod.GET: requests.get,
            HttpRequestMethod.POST: requests.post,
            HttpRequestMethod.PUT: requests.put,
            HttpRequestMethod.DELETE: requests.delete,
            HttpRequestMethod.PATCH: requests.patch,
            HttpRequestMethod.HEAD: requests.head,
        }

        # 4、获取对应的请求函数
        request_func = request_methods.get(self.node_data.method)
        if not request_func:
            raise FailedException(f"不支持的HTTP请求方法: {self.node_data.method}")

        # 5、组装请求参数
        request_kwargs = {
            "url": self.node_data.url,
            "params": inputs_dict[HttpRequestInputType.PARAMS],
            "headers": inputs_dict[HttpRequestInputType.HEADERS],
            "timeout": getattr(self.node_data, "timeout", 60),  # 默认超时时间60秒
        }

        # 处理Body数据：如果有定义Body类型的输入，且不为空，则作为JSON传递
        # 注意：这里默认将Body部分的输入参数组装成字典发送，适用于application/json
        body_data = inputs_dict[HttpRequestInputType.BODY]
        if body_data:
            request_kwargs["json"] = body_data

        # 6、发起请求并处理响应
        try:
            response = request_func(**request_kwargs)
            # 自动检测编码，防止中文乱码
            response.encoding = response.apparent_encoding
        except Exception as e:
            raise FailedException(f"HTTP请求执行失败: {e!s}")

        # 7、构建输出数据
        outputs = {
            "status_code": response.status_code,
            "text": response.text,
        }

        # 8、构建并返回节点执行结果
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    # 根据状态码判断节点状态，200-299视为成功
                    status=NodeStatus.SUCCEEDED if response.ok else NodeStatus.FAILED,
                    inputs=_inputs_dict,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                ),
            ],
        }
