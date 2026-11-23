#!/usr/bin/env python
"""
@Time    : 2026/1/18 17:46
@Author  : sunxiaojie
@File    : assistant_agent_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from internal.entity.conversation_entity import InvokeFrom
from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.assistant_agent_schema import (
    AssistantAgentChat,
    GetAssistantAgentMessagesWithPageReq,
    GetAssistantAgentMessagesWithPageResp,
)
from internal.schema.choice_schema import ChoiceReq
from internal.service import AssistantAgentService
from internal.service.choice_service import ChoiceService
from package.paginator import PageModel
from package.response import (
    compact_generate_response,
    success_json,
    success_message_json,
)


@dataclass
class AssistantAgentHandler:
    """辅助智能体处理器"""
    assistant_agent_service: AssistantAgentService
    choice_service: ChoiceService

    async def assistant_agent_chat(self, user: CurrentUser, req: AssistantAgentChat) -> None:
        """与辅助智能体进行对话聊天"""
        # 先 await prepare（校验/建消息/建 Agent + 前置 commit 在流开始前完成，
        # 异常 → 200+JSON 业务错误），再传流式生成器给 compact_generate_response。
        prepared = await self.assistant_agent_service.prepare_assistant_chat(req, user)
        response = self.assistant_agent_service.stream_assistant_chat(req, user, prepared)
        return compact_generate_response(response)

    async def stop_assistant_agent_chat(self, user: CurrentUser, task_id: UUID) -> None:
        """停止与辅助智能体的对话聊天"""
        # stop_chat 为同步 classmethod（无 IO，写 Redis），不可 await
        self.assistant_agent_service.stop_chat(task_id, user)
        return success_message_json("停止辅助Agent会话成功")

    async def assistant_agent_chat_choice(self, user: CurrentUser, task_id: UUID, req: ChoiceReq) -> None:
        """根据传递的任务id提交辅助Agent对话的用户选择"""
        await self.choice_service.submit(
            task_id, req.choice, req.skip, user, InvokeFrom.ASSISTANT_AGENT,
            req.event_id or None,
            action=req.action, keep_orders=req.keep_orders, custom=req.custom,
        )
        return success_message_json("已提交选择")

    async def get_assistant_agent_messages_with_page(self, user: CurrentUser, req: Annotated[GetAssistantAgentMessagesWithPageReq, Query()]) -> None:
        """获取与辅助智能体的消息分页列表"""
        messages, paginator = await self.assistant_agent_service.get_conversation_messages_with_page(req, user)
        resp = [
            GetAssistantAgentMessagesWithPageResp.model_validate(m).model_dump(mode="json")
            for m in messages
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def delete_assistant_agent_conversation(self, user: CurrentUser) -> None:
        """清空/删除与辅助智能体的聊天会话记录"""
        await self.assistant_agent_service.delete_conversation(user)
        return success_message_json("清空辅助Agent会话成功")
