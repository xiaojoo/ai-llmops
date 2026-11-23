#!/usr/bin/env python
"""
@Time    : 2026/2/8 21:48
@author  : sunxiaojie
@File    : conversation_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.conversation_schema import (
    GetConversationMessagesWithPageReq,
    GetConversationMessagesWithPageResp,
    UpdateConversationIsPinnedReq,
    UpdateConversationNameReq,
    UpdateMessageFeedbackReq,
)
from internal.service import ConversationService
from package.paginator import PageModel
from package.response import success_json, success_message_json


@dataclass
class ConversationHandler:
    """会话处理器"""
    conversation_service: ConversationService

    async def get_conversation_messages_with_page(self, user: CurrentUser, conversation_id: UUID, req: Annotated[GetConversationMessagesWithPageReq, Query()]) -> None:
        """根据传递的会话id获取该会话的消息列表分页数据"""
        messages, paginator = await self.conversation_service.get_conversation_messages_with_page(
            conversation_id, req, user,
        )
        resp = [
            GetConversationMessagesWithPageResp.model_validate(m).model_dump(mode="json")
            for m in messages
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def delete_conversation(self, user: CurrentUser, conversation_id: UUID) -> None:
        """根据传递的会话id删除指定的会话"""
        await self.conversation_service.delete_conversation(conversation_id, user)
        return success_message_json("删除会话成功")

    async def delete_message(self, user: CurrentUser, conversation_id: UUID, message_id: UUID) -> None:
        """根据传递的会话id+消息id删除指定的消息"""
        await self.conversation_service.delete_message(conversation_id, message_id, user)
        return success_message_json("删除会话消息成功")

    async def get_conversation_name(self, user: CurrentUser, conversation_id: UUID) -> None:
        """根据传递的会话id获取指定会话的名字"""
        conversation = await self.conversation_service.get_conversation(conversation_id, user)
        return success_json({"name": conversation.name})

    async def update_conversation_name(self, user: CurrentUser, conversation_id: UUID, req: UpdateConversationNameReq) -> None:
        """根据传递的会话id+name更新会话名字"""
        await self.conversation_service.update_conversation(conversation_id, user, name=req.name)
        return success_message_json("修改会话名称成功")

    async def update_conversation_is_pinned(self, user: CurrentUser, conversation_id: UUID, req: UpdateConversationIsPinnedReq) -> None:
        """根据传递的会话id+is_pinned更新会话的置顶状态"""
        await self.conversation_service.update_conversation(conversation_id, user, is_pinned=req.is_pinned)
        return success_message_json("修改会话置顶状态成功")

    async def update_message_feedback(self, user: CurrentUser, conversation_id: UUID, message_id: UUID, req: UpdateMessageFeedbackReq) -> None:
        """根据传递的会话id+消息id+feedback更新指定消息的用户反馈"""
        await self.conversation_service.update_message_feedback(
            conversation_id, message_id, req.feedback, user,
        )
        return success_message_json("更新消息反馈成功")
