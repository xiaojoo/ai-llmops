#!/usr/bin/env python
"""
@Time    : 2026/1/25 14:22
@Author  : sunxiaojie
@File    : tool_node.py
"""
import json
import time
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr
from sqlalchemy import select

from internal.core.tools.api_tools.entities import ToolEntity
from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailedException, NotFoundException
from internal.model import ApiTool

from .tool_entity import ToolNodeData


class ToolNode(BaseNode):
    """扩展插件节点"""
    node_data: ToolNodeData
    _tool: BaseTool = PrivateAttr(None)
    _tool_error: str = PrivateAttr("")
    _account_id: UUID = PrivateAttr()

    def __init__(self, *args: Any, account_id: UUID, **kwargs: Any):
        """构造函数：延迟加载工具，避免工具不存在导致整个图构建失败（其他分支仍可运行）

        account_id 为工作流归属账号，API 工具加载时必须按该账号过滤，防止跨租户越权访问他人工具。
        """
        # 1、调用父类构造函数完成数据初始化
        super().__init__(*args, **kwargs)

        # 2、记录账号信息（API 工具租户隔离）
        self._account_id = account_id

        # 3、工具延迟到run阶段加载（_ensure_tool），构造失败仅记录错误
        self._tool = None
        self._tool_error = ""

    def _ensure_tool(self) -> None:
        """惰性加载工具：构造失败时记录错误消息，由run阶段抛出（失败不影响其他分支执行）"""
        # 1、已加载或已记录失败则直接返回
        if self._tool is not None or self._tool_error:
            return

        try:
            # 2、判断是内置插件还是API插件，执行不同的操作
            if self.node_data.tool_type == "builtin_tool":
                from internal.core.tools.builtin_tools.providers import (
                    BuiltinProviderManager,
                )
                builtin_provider_manager = BuiltinProviderManager()

                # 3、调用内置提供者获取内置插件
                _tool = builtin_provider_manager.get_tool(self.node_data.provider_id, self.node_data.tool_id)
                if not _tool:
                    raise NotFoundException("该内置插件扩展不存在，请核实后重试")

                self._tool = _tool

            else:
                # 4、API插件，使用同步会话工厂查询记录并创建API插件
                # 复用 package.database 的同步会话工厂（使用 sqlalchemy_database_uri，含 search_path connect 事件处理）
                from package.database import get_sync_session_factory

                sync_session_factory = get_sync_session_factory()

                # 5、根据传递的提供者名字+工具名字查询工具（必须按当前账号过滤，防止跨租户越权）
                with sync_session_factory() as session:
                    stmt = (
                        select(ApiTool)
                        .where(
                            ApiTool.account_id == self._account_id,
                            ApiTool.provider_id == self.node_data.provider_id,
                            ApiTool.name == self.node_data.tool_id,
                        )
                    )
                    api_tool = session.execute(stmt).scalar_one_or_none()
                    if not api_tool:
                        raise NotImplementedError("该API扩展插件不存在，请核实重试")

                    # 6、导入API插件提供者
                    from internal.core.tools.api_tools.providers import ApiProviderManager
                    api_provider_manager = ApiProviderManager()

                    # 7、创建API工具提供者并赋值
                    self._tool = api_provider_manager.get_tool(ToolEntity(
                        id=str(api_tool.id),
                        name=api_tool.name,
                        url=api_tool.url,
                        method=api_tool.method,
                        description=api_tool.description,
                        headers=api_tool.provider.headers,
                        parameters=api_tool.parameters,
                    ))
        except Exception as e:
            # 8、加载失败不抛出，记录错误消息（CustomException消息在.message属性）
            self._tool_error = (
                str(e)
                or getattr(e, "message", "")
                or getattr(e, "msg", "")
                or repr(e)
            )

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """扩展插件执行节点，根据传递的信息调用预设的插件，涵盖内置插件及API插件"""

        # 1、惰性加载工具，加载失败则直接抛出（由BaseNode统一转为失败节点结果）
        self._ensure_tool()
        if self._tool_error:
            raise FailedException(self._tool_error)

        # 2、提取节点中的输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 3、调用插件并获取结果
        try:
            result = self._tool.invoke(inputs_dict)
        except Exception:
            raise FailedException("扩展插件执行失败，请稍后尝试")

        # 4、检测result是否为字符串，如果不是则转换
        if not isinstance(result, str):
            result = json.dumps(result)

        # 5、提取并构建输出数据结构
        outputs = {}
        if self.node_data.outputs:
            outputs[self.node_data.outputs[0].name] = result
        else:
            outputs["text"] = result

        # 6、构建响应状态并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED,
                    inputs=inputs_dict,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                ),
            ],
        }
