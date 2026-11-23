#!/usr/bin/env python
"""
@Time    : 2026/1/25 23:38
@author  : sunxiaojie
@File    : workflow_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import Request, Query

from typing import Annotated
from internal.server.deps import CurrentUser
from internal.schema.workflow_schema import (
    CreateWorkflowReq,
    GetWorkflowResp,
    GetWorkflowsWithPageReq,
    GetWorkflowsWithPageResp,
    UpdateWorkflowReq,
)
from internal.service import WorkflowService
from package.paginator import PageModel
from package.response import (
    compact_generate_response,
    success_json,
    success_message_json,
)


@dataclass
class WorkflowHandler:
    """工作流处理器"""
    workflow_service: WorkflowService

    async def create_workflow(self, user: CurrentUser, req: CreateWorkflowReq) -> None:
        """新增工作流"""
        workflow = await self.workflow_service.create_workflow(req, user)
        return success_json({"id": workflow.id})

    async def delete_workflow(self, user: CurrentUser, workflow_id: UUID) -> None:
        """根据传递的工作流id删除指定的工作流"""
        await self.workflow_service.delete_workflow(workflow_id, user)
        return success_message_json("删除工作流成功")

    async def update_workflow(self, user: CurrentUser, workflow_id: UUID, req: UpdateWorkflowReq) -> None:
        """根据传递的工作流id获取工作流详情"""
        await self.workflow_service.update_workflow(workflow_id, user, **req.model_dump())
        return success_message_json("修改工作流基础信息成功")

    async def get_workflow(self, user: CurrentUser, workflow_id: UUID) -> None:
        """根据传递的工作流id获取工作流详情"""
        workflow = await self.workflow_service.get_workflow(workflow_id, user)
        resp = GetWorkflowResp.model_validate(workflow)
        return success_json(resp.model_dump(mode="json"))

    async def get_workflows_with_page(self, user: CurrentUser, req: Annotated[GetWorkflowsWithPageReq, Query()]) -> None:
        """获取当前登录账号下的工作流分页列表数据"""
        workflows, paginator = await self.workflow_service.get_workflows_with_page(req, user)
        resp = [
            GetWorkflowsWithPageResp.model_validate(w).model_dump(mode="json")
            for w in workflows
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def update_draft_graph(self, user: CurrentUser, workflow_id: UUID, request: Request) -> None:
        """根据传递的工作流id+请求信息更新工作流草稿配置"""
        try:
            body = await request.json()
        except Exception:
            body = {}
        draft_graph_dict = body if body else {"nodes": [], "edges": []}
        await self.workflow_service.update_draft_graph(workflow_id, draft_graph_dict, user)
        return success_message_json("更新工作流草稿配置成功")

    async def get_draft_graph(self, user: CurrentUser, workflow_id: UUID) -> None:
        """根据传递的工作流id获取该工作流的草稿配置信息"""
        draft_graph = await self.workflow_service.get_draft_graph(workflow_id, user)
        # 图内 dataset.id 等 UUID 由 package/response 的 jsonable_encoder 统一转 str（Flask jsonify 原生支持）
        return success_json(draft_graph)

    async def debug_workflow(self, user: CurrentUser, workflow_id: UUID, request: Request) -> None:
        """根据传递的变量字典+工作流id调试指定的工作流"""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if "node_ids" in body:
            inputs = body.get("inputs", {}) or {}
            node_ids = body.get("node_ids") or None
        else:
            inputs = body
            node_ids = None

        # debug_workflow 为 async generator（SSE 流），不可 await——直接传 compact_generate_response
        response = self.workflow_service.debug_workflow(workflow_id, inputs, user, node_ids=node_ids)
        return compact_generate_response(response)

    async def publish_workflow(self, user: CurrentUser, workflow_id: UUID) -> None:
        """发布指定的工作流"""
        await self.workflow_service.publish_workflow(workflow_id, user)
        return success_message_json("发布工作流成功")

    async def cancel_publish_workflow(self, user: CurrentUser, workflow_id: UUID) -> None:
        """根据传递的工作流id取消发布指定的工作流"""
        await self.workflow_service.cancel_publish_workflow(workflow_id, user)
        return success_message_json("取消发布工作流成功")
