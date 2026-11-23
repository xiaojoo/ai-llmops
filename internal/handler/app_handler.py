#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/15 14:18
@author : sunxiaojie
@File   : app_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import Request, Query

from internal.entity.app_entity import AppStatus
from internal.entity.conversation_entity import InvokeFrom
from internal.lib.helper import datetime_to_timestamp
from typing import Annotated
from internal.server.deps import CurrentUser
from internal.schema.app_schema import (
    CreateAppReq,
    DebugChatReq,
    FallbackHistoryToDraftReq,
    GetAppResp,
    GetAppsWithPageReq,
    GetAppsWithPageResp,
    GetDebugConversationMessagesWithPageReq,
    GetDebugConversationMessagesWithPageResp,
    GetPublishHistoriesWithPageReq,
    GetPublishHistoriesWithPageResp,
    UpdateAppReq,
    UpdateDebugConversationSummaryReq,
)
from internal.schema.user_memory_schema import (
    EpisodicMemoryResp,
    GetUserMemoryFactsAtReq,
    GetUserMemoryFactsWindowReq,
    ProceduralMemoryResp,
    TestMemoryConfigReq,
    UserMemoryFactResp,
)
from internal.schema.choice_schema import ChoiceReq
from internal.service import (
    AppConfigService,
    AppService,
    AssistantAgentService,
    EpisodicMemoryService,
    LanguageModelManager,
    ProceduralMemoryService,
    RetrievalService,
    UserMemoryService,
)
from internal.service.choice_service import ChoiceService
from internal.service.memory_provider.tencent_provider import TencentMemoryProvider
from package.paginator import PageModel
from package.response import (
    compact_generate_response,
    success_json,
    success_message_json,
)


@dataclass
class AppHandler:
    """应用控制器"""
    app_service: AppService
    retrieval_service: RetrievalService
    language_model_manager: LanguageModelManager
    assistant_agent_service: AssistantAgentService
    user_memory_service: UserMemoryService
    episodic_memory_service: EpisodicMemoryService
    procedural_memory_service: ProceduralMemoryService
    app_config_service: AppConfigService
    tencent_provider: TencentMemoryProvider
    choice_service: ChoiceService

    async def create_app(self, user: CurrentUser, req: CreateAppReq) -> None:
        """调用服务创建新的APP记录"""
        app = await self.app_service.create_app(req, user)
        return success_json({"id": app.id})

    async def update_app(self, user: CurrentUser, app_id: UUID, req: UpdateAppReq) -> None:
        """根据传递的信息更新指定的应用"""
        await self.app_service.update_app(app_id, user, **req.model_dump())
        return success_message_json("修改Agent智能体应用成功")

    async def copy_app(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id快速拷贝该应用"""
        app = await self.app_service.copy_app(app_id, user)
        return success_json({"id": app.id})

    async def delete_app(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的信息删除指定的应用"""
        await self.app_service.delete_app(app_id, user)
        return success_message_json("删除Agent智能体应用成功")

    async def get_apps_with_page(self, user: CurrentUser, req: Annotated[GetAppsWithPageReq, Query()]) -> None:
        """获取当前登录账号的应用分页列表数据"""
        apps, paginator = await self.app_service.get_apps_with_page(req, user)
        # App.app_config/draft_app_config 已上移为服务方法，由 handler 按状态取配置并组装 dict
        # （published → app_config；否则 → draft_app_config）。
        resp = []
        for app in apps:
            if app.status == AppStatus.PUBLISHED.value:
                app_config = await self.app_service.get_app_config(app)
            else:
                app_config = await self.app_service.get_or_create_draft_app_config(app)
            model_config = dict(app_config.model_config) if app_config else {}
            labels = self.language_model_manager.resolve_model_config_display(
                model_config.get("provider", ""),
                model_config.get("model", ""),
            )
            model_config_display = {
                "provider": model_config.get("provider", ""),
                "model": model_config.get("model", ""),
            }
            if labels:
                model_config_display.update(labels)
            resp.append(GetAppsWithPageResp.model_validate({
                "id": str(app.id),
                "name": app.name,
                "icon": app.icon,
                "description": app.description,
                "preset_prompt": app_config.preset_prompt if app_config else "",
                "model_config": model_config_display,
                "status": app.status,
                "updated_at": datetime_to_timestamp(app.updated_at),
                "created_at": datetime_to_timestamp(app.created_at),
                "token": app.token or "",
            }).model_dump(mode="json", by_alias=True))
        return success_json(PageModel(list=resp, paginator=paginator))

    async def get_app(self, user: CurrentUser, app_id: UUID) -> None:
        app = await self.app_service.get_app(app_id, user)
        resp = GetAppResp.model_validate(app)
        return success_json(resp.model_dump(mode="json"))

    async def get_draft_app_config(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取应用的最新草稿配置"""
        draft_config = await self.app_service.get_draft_app_config(app_id, user)
        return success_json(draft_config)

    async def update_draft_app_config(self, user: CurrentUser, app_id: UUID, request: Request) -> None:
        """根据传递的应用id + 草稿配置更新应用的最新草稿配置"""
        try:
            draft_app_config = await request.json()
        except Exception:
            draft_app_config = {}
        await self.app_service.update_draft_app_config(app_id, draft_app_config, user)
        return success_message_json("更新应用草稿配置成功")

    async def publish_draft_app_config(self, user: CurrentUser, app_id: UUID) -> None:
        """"根据传递的应用id发布/更新特定的草稿配置信息"""
        await self.app_service.publish_draft_app_config(app_id, user)
        return success_message_json("发布/更新应用配置成功")

    async def cancel_publish(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id，取消发布指定的应用配置信息"""
        await self.app_service.cancel_publish_app_config(app_id, user)
        return success_message_json("取消发布应用配置成功")

    async def get_publish_histories_with_page(self, user: CurrentUser, app_id: UUID, req: Annotated[GetPublishHistoriesWithPageReq, Query()]) -> None:
        """根据传递的应用id，获取应用发布历史列表"""
        app_config_versions, paginator = await self.app_service.get_publish_histories_with_page(app_id, req, user)
        resp = [
            GetPublishHistoriesWithPageResp.model_validate(item).model_dump(mode="json")
            for item in app_config_versions
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def fallback_history_to_draft(self, user: CurrentUser, app_id: UUID, req: FallbackHistoryToDraftReq) -> None:
        """根据传递的应用id+历史配置版本id，退回指定版本到草稿中"""
        await self.app_service.fallback_history_to_draft(app_id, req.app_config_version_id, user)
        return success_message_json("回退历史配置至草稿成功")

    async def get_debug_conversation_summary(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取调试会话长期记忆"""
        summary = await self.app_service.get_debug_conversation_summary(app_id, user)
        return success_json({"summary": summary})

    async def update_debug_conversation_summary(self, user: CurrentUser, app_id: UUID, req: UpdateDebugConversationSummaryReq) -> None:
        """根据传递的应用id+摘要信息更新调试会话长期记忆"""
        await self.app_service.update_debug_conversation_summary(app_id, req.summary, user)
        return success_message_json("更新AI应用长期记忆成功")

    async def delete_debug_conversation(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id，清空该应用的调试会话记录"""
        await self.app_service.delete_debug_conversation(app_id, user)
        return success_message_json("清空应用调试会话记录成功")

    async def debug_chat(self, user: CurrentUser, app_id: UUID, req: DebugChatReq) -> None:
        """根据传递的应用id+query，发起调试对话"""
        # 先 await prepare_debug_chat——SSE 的 async generator 惰性执行，若业务异常在
        # 流开始后才抛会得到 "response already started" 而非 200+not_found。前置校验/副作用
        # 在流开始前完成，异常由普通异常处理器输出 JSON 业务错误。
        prepared = await self.app_service.prepare_debug_chat(app_id, req, user)
        response = self.app_service.stream_debug_chat(app_id, req, user, prepared)
        return compact_generate_response(response)

    async def stop_debug_chat(self, user: CurrentUser, app_id: UUID, task_id: UUID) -> None:
        """根据传递的应用id+任务id停止某个应用的指定调试会话"""
        await self.app_service.stop_debug_chat(app_id, task_id, user)
        return success_message_json("停止应用调试会话成功")

    async def debug_chat_choice(self, user: CurrentUser, app_id: UUID, task_id: UUID, req: ChoiceReq) -> None:
        """根据传递的应用id+任务id提交调试对话的用户选择"""
        await self.choice_service.submit(
            task_id, req.choice, req.skip, user, InvokeFrom.DEBUGGER,
            req.event_id or None,
            action=req.action, keep_orders=req.keep_orders, custom=req.custom,
        )
        return success_message_json("已提交选择")

    async def get_debug_conversation_messages_with_page(self, user: CurrentUser, app_id: UUID, req: Annotated[GetDebugConversationMessagesWithPageReq, Query()]) -> None:
        """根据传递的应用id，获取该应用的调试会话分页列表记录"""
        messages, paginator = await self.app_service.get_debug_conversation_messages_with_page(app_id, req, user)
        resp = [
            GetDebugConversationMessagesWithPageResp.model_validate(m).model_dump(mode="json")
            for m in messages
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def get_published_config(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取应用的发布配置信息"""
        published_config = await self.app_service.get_published_config(app_id, user)
        return success_json(published_config)

    async def regenerate_web_app_token(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id重新生成WebApp凭证标识"""
        token = await self.app_service.regenerate_web_app_token(app_id, user)
        return success_json({"token": token})

    async def ping(self, user: CurrentUser) -> None:
        return success_json({"pong": "success"})

    async def test_memory_config(self, user: CurrentUser, req: TestMemoryConfigReq) -> None:
        """测试腾讯记忆连通性：合并系统配置 + 可选应用作用域覆盖，做一次检索探活"""
        app_config = {"long_term_memory": {}}
        if req.app_id:
            try:
                app = await self.app_service.get_app(UUID(req.app_id), user)
                app_config = await self.app_config_service.get_app_config(app)
            except Exception:
                app_config = {"long_term_memory": {}}

        ltm = dict(app_config.get("long_term_memory") or {})
        for key in ("team_id", "agent_id", "user_id"):
            value = getattr(req, key, "")
            if value:
                ltm[key] = str(value)
        app_config["long_term_memory"] = ltm

        app_id = UUID(req.app_id) if req.app_id else UUID(int=0)
        # 系统设置页保存前测试：把当前表单的连接配置（非空字段）带上来覆盖已保存配置
        overrides = {
            field: value for field, value in (
                ("endpoint", req.endpoint),
                ("api_key", req.api_key),
                ("service_id", req.service_id),
                ("admin_key", req.admin_key),
            ) if value
        }
        ok, message = await self.tencent_provider.test_connection(
            app_config, app_id, user.id, overrides=overrides,
        )
        return success_json({"ok": ok, "message": message})

    async def get_user_memory_facts(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取当前用户在当前应用下的有效事实（用户卡片）"""
        facts = await self.user_memory_service.get_current_facts(app_id, user.id, min_trust=0.0)
        resp = [UserMemoryFactResp.model_validate(f).model_dump(mode="json") for f in facts]
        return success_json({"facts": resp})

    async def get_user_memory_facts_history(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取当前用户在当前应用下的事实历史（审计）"""
        facts = await self.user_memory_service.get_facts_history(app_id, user.id)
        resp = [UserMemoryFactResp.model_validate(f).model_dump(mode="json") for f in facts]
        return success_json({"facts": resp})

    async def get_user_memory_facts_at(self, user: CurrentUser, app_id: UUID, req: Annotated[GetUserMemoryFactsAtReq, Query()]) -> None:
        """按时间点检索（现实视角）：获取 at 时刻有效的事实（通告类按生效时间查询）"""
        from datetime import datetime
        at = datetime.fromtimestamp(req.at)
        facts = await self.user_memory_service.get_facts_at(app_id, user.id, at)
        resp = [UserMemoryFactResp.model_validate(f).model_dump(mode="json") for f in facts]
        return success_json({"facts": resp})

    async def get_user_memory_facts_in_window(self, user: CurrentUser, app_id: UUID, req: Annotated[GetUserMemoryFactsWindowReq, Query()]) -> None:
        """按时间窗口检索（现实视角）：获取与 [start, end] 重叠的事实（通告类）"""
        from datetime import datetime
        start = datetime.fromtimestamp(req.start)
        end = datetime.fromtimestamp(req.end)
        facts = await self.user_memory_service.get_facts_in_window(app_id, user.id, start, end)
        resp = [UserMemoryFactResp.model_validate(f).model_dump(mode="json") for f in facts]
        return success_json({"facts": resp})

    async def get_episodic_memories(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取当前用户在当前应用下的情景记忆记录（调试/审计）"""
        episodes = await self.episodic_memory_service.get_episodes(app_id, user.id)
        resp = [EpisodicMemoryResp.model_validate(e).model_dump(mode="json") for e in episodes]
        return success_json({"episodes": resp})

    async def get_procedural_memories(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取当前用户在当前应用下的程序记忆记录（调试/审计）"""
        instructions = await self.procedural_memory_service.get_instruction_records(app_id, user.id)
        resp = [ProceduralMemoryResp.model_validate(i).model_dump(mode="json") for i in instructions]
        return success_json({"instructions": resp})
