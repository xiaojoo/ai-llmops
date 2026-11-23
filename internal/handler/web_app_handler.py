#!/usr/bin/env python
"""
@Time    : 2026/2/8 20:31
@author : sunxiaojie
@File   : web_app_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from internal.entity.conversation_entity import InvokeFrom
from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.choice_schema import ChoiceReq
from internal.schema.web_app_schema import (
    CodeActionReq,
    CodeActionResp,
    GetConversationsReq,
    GetConversationsResp,
    GetWebAppResp,
    ToolResultReq,
    UpdateConversationSettingsReq,
    WebAppChatReq,
)
from internal.service import WebAppService
from internal.service.choice_service import ChoiceService
from package.response import (
    compact_generate_response,
    success_json,
    success_message_json,
)


@dataclass
class WebAppHandler:
    """WebApp处理器"""
    web_app_service: WebAppService
    choice_service: ChoiceService

    async def get_web_app(self, user: CurrentUser, token: str) -> None:
        """根据传递的token凭证标识获取WebApp基础信息"""
        app = await self.web_app_service.get_web_app_info(token)
        resp = GetWebAppResp.model_validate(app)
        return success_json(resp.model_dump(mode="json"))

    async def get_default_web_app(self, user: CurrentUser) -> None:
        """获取当前账号的默认 WebApp（Web 端 /web-apps 无 token 入口使用）"""
        app = await self.web_app_service.get_default_web_app(user)
        return success_json(app)

    async def bootstrap(self, user: CurrentUser) -> None:
        """插件兜底：确保当前账号至少有一个已发布的 WebApp（没有则自动创建+发布），
        返回可用 token。插件登录/每次刷新时调用，避免"没有已发布 App 就不可用"。
        """
        info = await self.web_app_service.bootstrap_web_app(user)
        return success_json(info)

    async def web_app_chat(self, user: CurrentUser, token: str, req: WebAppChatReq) -> None:
        """根据传递的token+query等信息与WebApp进行对话"""
        # 先 await prepare（前置校验在流开始前，异常 → 200+JSON 业务错误），
        # 再传流式生成器给 compact_generate_response。
        prepared = await self.web_app_service.prepare_web_app_chat(token, req, user)
        response = self.web_app_service.stream_web_app_chat(token, req, user, prepared)
        return compact_generate_response(response)

    async def web_app_chat_resume(
            self,
            user: CurrentUser,
            token: str,
            run_id: UUID,
            last_event_id: int = 0,
    ) -> None:
        """断流重连续传：按 Last-Event-ID 重放已缓冲帧，再订阅该 run 实时队列。

        插件本地工具运行时在 SSE 长连接被硬断后，携带最后收到的 `id:` 重连到这里补发，
        避免丢失的 local_tool_call 导致服务器 wait_for_tool_result 超时。

        网页端刷新/切会话后重挂同一 run 也走这里，因此必须先校验 run 归属：重放帧里含
        答案正文与工具入参，仅凭 token + 猜不到的 run_id 不构成授权。
        """
        await self.web_app_service.get_web_app(token)
        self.choice_service.assert_task_belong(run_id, user, InvokeFrom.WEB_APP)
        response = self.web_app_service.stream_web_app_chat_resume(token, run_id, last_event_id, user)
        return compact_generate_response(response)

    async def stop_web_app_chat(self, user: CurrentUser, token: str, task_id: UUID) -> None:
        """根据传递的token+task_id停止与WebApp的对话"""
        await self.web_app_service.stop_web_app_chat(token, task_id, user)
        return success_message_json("停止WebApp会话成功")

    async def web_app_chat_choice(self, user: CurrentUser, token: str, task_id: UUID, req: ChoiceReq) -> None:
        """根据传递的token+任务id提交WebApp对话的用户选择"""
        await self.web_app_service.get_web_app(token)
        await self.choice_service.submit(
            task_id, req.choice, req.skip, user, InvokeFrom.WEB_APP,
            req.event_id or None,
            action=req.action, keep_orders=req.keep_orders, custom=req.custom,
        )
        return success_message_json("已提交选择")

    async def web_app_chat_tool_result(self, user: CurrentUser, token: str, task_id: UUID, req: ToolResultReq) -> None:
        """根据传递的token+任务id回传本地工具执行结果（Remote Agent + Local Tool Runtime）"""
        await self.web_app_service.get_web_app(token)
        await self.choice_service.submit_tool_result(
            task_id, req.tool_call_id, req.result, req.error, user, InvokeFrom.WEB_APP,
        )
        return success_message_json("已接收本地工具结果")

    async def get_conversations(self, user: CurrentUser, token: str, req: Annotated[GetConversationsReq, Query()]) -> None:
        """根据传递的token+is_pinned获取指定WebApp下的所有会话列表信息"""
        conversations = await self.web_app_service.get_conversations(token, req.is_pinned, user)
        resp = [
            GetConversationsResp.model_validate(c).model_dump(mode="json")
            for c in conversations
        ]
        return success_json(resp)

    async def update_conversation_settings(
            self,
            user: CurrentUser,
            token: str,
            conversation_id: UUID,
            req: UpdateConversationSettingsReq,
    ) -> None:
        """更新WebApp会话设置（短期记忆窗口轮数）"""
        conversation = await self.web_app_service.update_conversation_settings(
            token, conversation_id, req.dialog_round, user,
        )
        return success_json(GetConversationsResp.model_validate(conversation).model_dump(mode="json"))

    async def code_action(self, user: CurrentUser, token: str, req: CodeActionReq) -> None:
        """编辑器选中代码的 AI 操作（优化/解释/注释）：直接调 LLM，返回纯结果不流式。

        与 web_app_chat 不同：不创建会话/消息记录，供 IDE 右键菜单"选中 → 优化/解释/注释 → 替换"使用。
        """
        result = await self.web_app_service.code_action(token, req, user)
        return success_json(CodeActionResp(**result).model_dump(mode="json"))
