#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/16 20:04
@Author : sunxiaojie
@File   : app_service.py
"""
import io
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from redis import Redis
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.language_model import LanguageModelManager
from internal.core.language_model.entities.model_entity import ModelParameterType
from internal.core.language_model.providers.custom_api.models import CUSTOM_API_PROVIDER
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.entity.ai_entity import OPTIMIZE_PROMPT_TEMPLATE
from internal.entity.app_entity import (
    DEFAULT_APP_CONFIG,
    AppConfigType,
    AppStatus,
)
from internal.entity.audio_entity import ALLOWED_AUDIO_VOICES
from internal.entity.conversation_entity import (
    LIVE_RUN_STATUSES,
    LIVE_RUN_VISIBLE_SECONDS,
    InvokeFrom,
    MessageStatus,
)
from internal.entity.workflow_entity import WorkflowStatus
from internal.exception import (
    FailedException,
    ForbiddenException,
    NotFoundException,
    ValidateException,
)
from internal.lib.helper import generate_random_string, get_value_type, remove_fields
from internal.model import (
    Account,
    AgentRun,
    ApiTool,
    App,
    AppConfig,
    AppConfigVersion,
    AppDatasetJoin,
    Conversation,
    Dataset,
    Message,
    Skill,
    Workflow,
)
from internal.schema.app_schema import (
    CreateAppReq,
    DebugChatReq,
    GetAppsWithPageReq,
    GetDebugConversationMessagesWithPageReq,
    GetPublishHistoriesWithPageReq,
)
from package.paginator import Paginator

from .app_config_service import AppConfigService
from .attachment_service import AttachmentService
from .base_service import BaseService
from .chat_runner import ChatRunner
from .conversation_service import ConversationService
from .cos_service import CosService
from .language_model_service import LanguageModelService
from .memory_provider import MemoryProviderResolver
from .retrieval_service import RetrievalService
from .sub_task_service import SubTaskService

logger = logging.getLogger(__name__)

async def _infer(sync_fn, *args):
    """同步模型调用经线程池桥接。"""
    import asyncio
    return await asyncio.to_thread(sync_fn, *args)


@dataclass
class AppService(BaseService):
    """应用服务逻辑"""
    db: AsyncSession
    conversation_service: ConversationService
    builtin_provider_manager: BuiltinProviderManager
    api_provider_manager: ApiProviderManager
    retrieval_service: RetrievalService
    redis_client: Redis
    cos_service: CosService
    app_config_service: AppConfigService
    language_model_service: LanguageModelService
    language_model_manager: LanguageModelManager
    chat_runner: ChatRunner
    memory_provider_resolver: MemoryProviderResolver
    attachment_service: AttachmentService | None = None

    async def get_app_config(self, app: App) -> AppConfig | None:
        """根据应用获取其运行配置。"""
        if app.app_config_id is None:
            return None
        return await self.db.get(AppConfig, app.app_config_id)

    async def get_or_create_draft_app_config(self, app: App) -> AppConfigVersion:
        """查询草稿配置，缺失时创建默认草稿并提交。"""
        stmt = (
            select(AppConfigVersion)
            .where(
                AppConfigVersion.app_id == app.id,
                AppConfigVersion.config_type == AppConfigType.DRAFT,
            )
        )
        app_config_version = (await self.db.execute(stmt)).scalar_one_or_none()
        # 检测配置是否存在，不存在则创建一个默认值
        if not app_config_version:
            app_config_version = AppConfigVersion(
                app_id=app.id,
                version=0,
                config_type=AppConfigType.DRAFT,
                **DEFAULT_APP_CONFIG,
            )
            self.db.add(app_config_version)
            await self.db.commit()  # 独立事务边界
        return app_config_version

    async def get_debug_conversation(self, app: App) -> Conversation | None:
        """根据应用查询调试会话（只读）。"""
        if app.debug_conversation_id is None:
            return None
        stmt = (
            select(Conversation)
            .where(
                Conversation.id == app.debug_conversation_id,
                Conversation.invoke_from == InvokeFrom.DEBUGGER,
            )
        )
        return await self.db.scalar(stmt)

    async def get_token_with_default(self, app: App) -> str:
        """按发布状态清空或生成应用 token。"""
        # 1、判断状态是否为已发布
        if app.status != AppStatus.PUBLISHED:
            # 2、非发布的情况下需要清空数据，并提交更新
            if app.token is not None or app.token != "":
                app.token = None
                await self.db.commit()  # 独立事务边界
            return ""
        # 3、已发布状态需要判断token是否存在，不存在则生成
        if app.token is None or app.token == "":
            app.token = generate_random_string(16)
            await self.db.commit()  # 独立事务边界

        return app.token

    async def get_app_dataset_joins(self, app_config: AppConfig) -> list[AppDatasetJoin]:
        """查询应用配置关联的知识库记录。"""
        stmt = select(AppDatasetJoin).where(AppDatasetJoin.app_id == app_config.app_id)
        return list((await self.db.scalars(stmt)).all())

    @staticmethod
    def _default_icon_bytes() -> bytes:
        """内置默认应用图标（与 /default-app-icon 端点同一文件，见 app/http/app.py）。

        直接读本地文件，避免经"请求上下文 URL → requests.get 自访问下载"的环——
        celery 后台任务无请求上下文，会拼出 None://None/default-app-icon 导致 InvalidSchema。
        """
        icon_path = Path(__file__).resolve().parents[2] / "internal" / "core" / "builtin_apps" / "default-user-icon.png"
        return icon_path.read_bytes()

    async def auto_create_app(self, name: str, description: str, account_id: UUID, app_type: str = "agent") -> None:
        """根据传递的应用名称、描述、账号id利用AI创建一个Agent智能体"""
        # 1.创建LLM，用于生成预设提示词
        llm = ChatDeepSeek(model="deepseek-v4-flash", temperature=0.8)

        # 2.生成预设prompt链（langchain 链 invoke 为同步模型调用 → 线程池桥接）
        generate_preset_prompt_chain = ChatPromptTemplate.from_messages([
            ("system", OPTIMIZE_PROMPT_TEMPLATE),
            ("human", "应用名称: {name}\n\n应用描述: {description}")
        ]) | llm | StrOutputParser()
        preset_prompt = await _infer(generate_preset_prompt_chain.invoke, {"name": name, "description": description})

        # 3.图标：内置默认图本地读取后上传腾讯云cos（不再走 icon 生成链/网络下载）
        icon_content = self._default_icon_bytes()
        account = await self.db.get(Account, account_id)
        upload_file = await self.cos_service.upload_file(
            io.BytesIO(icon_content),
            "icon.png",
            only_image=True,
            account=account,
        )
        icon = self.cos_service.get_fresh_file_url(upload_file.key)

        # 4. 创建应用记录并刷新数据，从而可以拿到应用id（独立事务边界）
        app = App(
            account_id=account.id,
            name=name,
            icon=icon,
            description=description,
            app_type=app_type,
        )
        self.db.add(app)
        await self.db.flush()

        # 5. 创建草稿记录
        app_config_version = AppConfigVersion(
            app_id=app.id,
            version=0,
            config_type=AppConfigType.DRAFT,
            **{
                **DEFAULT_APP_CONFIG,
                "preset_prompt": preset_prompt
            }
        )
        self.db.add(app_config_version)
        await self.db.flush()

        # 6. 更新应用配置id
        app.draft_app_config_id = app_config_version.id
        await self.db.commit()  # 独立事务边界

    async def create_app(self, req: CreateAppReq, account: Account) -> App:
        """创建Agent应用服务（独立事务边界）"""
        app = App(
            account_id=account.id,
            name=req.name,
            icon=req.icon,
            description=req.description,
            app_type=req.app_type,
            status=AppStatus.DRAFT
        )
        # 将实体类添加到session会话中
        self.db.add(app)
        await self.db.flush()

        # 添加草稿记录
        app_config_version = AppConfigVersion(
            app_id=app.id,
            version=0,
            config_type=AppConfigType.DRAFT,
            **DEFAULT_APP_CONFIG,
        )
        self.db.add(app_config_version)
        await self.db.flush()

        # 添加草稿配置id
        app.draft_app_config_id = app_config_version.id
        await self.db.commit()  # 独立事务边界

        return app

    async def get_app(self, app_id: UUID, account: Account) -> App:
        app = await self.get(App, app_id)
        # 判断应用是否存在
        if app is None or app.is_deleted:
            raise NotFoundException("该应用不存在，请核实后重试")

        # 判断是否用访问权限
        if app.account_id != account.id:
            raise ForbiddenException("当前账号没有权限访问，请联系管理员")
        return app

    async def delete_app(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id+账号，逻辑删除指定的应用（is_deleted=True，保留关联数据便于追溯/恢复）"""
        app = await self.get_app(app_id, account)
        await self.update(app, is_deleted=True)
        return app

    async def update_app(self, app_id: UUID, account: Account, **kwargs) -> App:
        """根据传递的应用id+账号+信息，更新指定的应用"""
        app = await self.get_app(app_id, account)
        await self.update(app, **kwargs)
        return app

    async def copy_app(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id，拷贝Agent相关信息并创建一个新Agent"""
        # 1、获取App+草稿配置，并校验权限
        app = await self.get_app(app_id, account)
        draft_app_config = await self.get_or_create_draft_app_config(app)

        # 2、将数据转换为字典并删除无用数据
        app_dict = app.__dict__.copy()
        draft_app_config_dict = draft_app_config.__dict__.copy()

        # 3、删除无用字段
        app_remove_fields = [
            "id", "app_config_id", "draft_app_config_id", "debug_conversation_id",
            "status", "updated_at", "created_at", "_sa_instance_state",
        ]

        draft_app_config_remove_fields = [
            "id", "app_id", "version", "updated_at", "created_at", "_sa_instance_state",
        ]

        remove_fields(app_dict, app_remove_fields)
        remove_fields(draft_app_config_dict, draft_app_config_remove_fields)

        # 4、创建一个新的应用记录（独立事务边界）
        new_app = App(**app_dict, status=AppStatus.DRAFT)
        self.db.add(new_app)
        await self.db.flush()

        # 5、添加草稿配置
        new_draft_app_config = AppConfigVersion(
            **draft_app_config_dict,
            app_id=new_app.id,
            version=0,
        )

        self.db.add(new_draft_app_config)
        await self.db.flush()

        # 6、更新应用的草稿配置id
        new_app.draft_app_config_id = new_draft_app_config.id
        await self.db.commit()  # 独立事务边界

        return new_app

    async def get_apps_with_page(self, req: GetAppsWithPageReq, account: Account) -> tuple[list[App], Paginator]:
        """根据传递的分页参数获取当前登录账号下的应用分页列表数据"""
        # 1、构建分页器
        paginator = Paginator(db=self.db, req=req)

        # 2、构建筛选条件
        filters = [App.account_id == account.id]
        if req.search_word:
            filters.append(App.name.ilike(f"%{req.search_word}%"))

        # 3、执行分页操作（过滤逻辑删除的应用）
        stmt = (
            select(App)
            .where(App.is_deleted.is_(False), *filters)
            .order_by(desc(App.created_at))
        )
        apps = await paginator.paginate(stmt)

        return apps, paginator

    async def get_draft_app_config(self, app_id: UUID, account: Account) -> dict[str, Any]:
        """根据传递的应用id，获取指定的应用草稿配置信息"""
        app = await self.get_app(app_id, account)
        draft_app_config = await self.app_config_service.get_draft_app_config(app)
        # 编排器配置：与其他配置块保持一致，透传草稿配置值（为空时默认空字典）
        draft_record = await self.get_or_create_draft_app_config(app)
        draft_app_config["orchestrator_config"] = draft_record.orchestrator_config or {}
        return draft_app_config

    async def update_draft_app_config(
            self, app_id: UUID,
            draft_app_config: dict[str, Any],
            account: Account
    ) -> AppConfigVersion:
        """根据传递的应用id+草稿配置修改指定应用的最新草稿"""
        # 1、获取应用信息并校验
        app = await self.get_app(app_id, account)
        # 2、校验传递的草稿配置信息
        draft_app_config = await self._validate_draft_app_config(draft_app_config, account)
        # 3、获取当前应用的最新草稿信息
        draft_app_config_record = await self.get_or_create_draft_app_config(app)
        await self.update(
            draft_app_config_record,
            # TODO：目前使用server_onupdate,所以该字段暂时需要手动传递
            updated_at=datetime.now(),
            **draft_app_config
        )
        return draft_app_config_record

    async def publish_draft_app_config(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id+账号，发布/更新指定的应用草稿配置为运行时配置"""
        # 1、获取应用的信息以及草稿信息
        app = await self.get_app(app_id, account)
        draft_app_config = await self.get_draft_app_config(app_id, account)

        # 2、创建应用运行配置（在这里暂时不刷除历史的运行配置）
        app_config = await self.create(
            AppConfig,
            app_id=app_id,
            model_config=draft_app_config["model_config"],
            dialog_round=draft_app_config["dialog_round"],
            preset_prompt=draft_app_config["preset_prompt"],
            tools=[
                {
                    "type": tool["type"],
                    "provider_id": tool["provider"]["id"],
                    "tool_id": tool["tool"]["name"],
                    "params": tool["tool"]["params"]
                }
                for tool in draft_app_config["tools"]
            ],
            skills=[skill["id"] for skill in draft_app_config["skills"]],
            workflows=[workflow["id"] for workflow in draft_app_config["workflows"]],
            retrieval_config=draft_app_config["retrieval_config"],
            long_term_memory=draft_app_config["long_term_memory"],
            opening_statement=draft_app_config["opening_statement"],
            opening_questions=draft_app_config["opening_questions"],
            speech_to_text=draft_app_config["speech_to_text"],
            text_to_speech=draft_app_config["text_to_speech"],
            suggested_after_answer=draft_app_config["suggested_after_answer"],
            review_config=draft_app_config["review_config"],
            orchestrator_config=draft_app_config["orchestrator_config"],
        )

        # 3、更新应用关联的运行时配置以及状态
        await self.update(app, app_config_id=app_config.id, status=AppStatus.PUBLISHED, )

        # 4、先删除原有的知识库关联记录（独立事务边界）
        stmt = (
            delete(AppDatasetJoin)
            .where(AppDatasetJoin.app_id == app_id)
        )
        await self.db.execute(stmt)
        await self.db.commit()  # 独立事务边界

        # 5、新增新的知识库关联记录
        for dataset in draft_app_config["datasets"]:
            await self.create(
                AppDatasetJoin,
                app_id=app_id,
                dataset_id=dataset["id"],
            )

        # 6、获取应用草稿记录，并移除 id、version、config_type、updated_at、created_at 字段
        draft_record = await self.get_or_create_draft_app_config(app)
        draft_app_config_copy = draft_record.__dict__.copy()
        remove_fields(draft_app_config_copy, [
            "id", "version", "config_type", "updated_at", "created_at", "_sa_instance_state"
        ])

        # 7、获取当前最大的发布版本
        stmt = (
            select(func.coalesce(func.max(AppConfigVersion.version), 0))
            .where(
                AppConfigVersion.app_id == app_id,
                AppConfigVersion.config_type == AppConfigType.PUBLISHED
            )
        )
        max_version = (await self.db.execute(stmt)).scalar_one()

        # 8、新增发布历史配置
        await self.create(
            AppConfigVersion,
            version=max_version + 1,
            config_type=AppConfigType.PUBLISHED,
            **draft_app_config_copy,
        )
        return app

    async def cancel_publish_app_config(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id+账号，取消发布指定的应用配置"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、检测下当前应用的状态是否为已发布
        if app.status != AppStatus.PUBLISHED.value:
            raise FailedException("当前应用未发布，请核实后重试")

        # 3、修改账号的发布状态，并清空关联配置id
        await self.update(app, status=AppStatus.DRAFT, app_config_id=None)

        # 4、删除应用关联的知识库信息（独立事务边界）
        stmt = (
            delete(AppDatasetJoin)
            .where(AppDatasetJoin.app_id == app_id)
        )
        await self.db.execute(stmt)
        await self.db.commit()  # 独立事务边界

        return app

    async def get_publish_histories_with_page(
            self,
            app_id: UUID,
            req: GetPublishHistoriesWithPageReq,
            account: Account
    ) -> tuple[list[AppConfigVersion], Paginator]:
        """根据传递的应用id+请求数据，获取指定应用的发布历史配置列表信息"""
        # 1、获取应用信息并校验权限
        await self.get_app(app_id, account)

        # 2、构建分页器
        paginator = Paginator(db=self.db, req=req)

        # 3、执行分页并获取数据
        stmt = (
            select(AppConfigVersion)
            .where(
                AppConfigVersion.app_id == app_id,
                AppConfigVersion.config_type == AppConfigType.PUBLISHED,
            )
            .order_by(desc(AppConfigVersion.version))
        )

        app_config_versions = await paginator.paginate(stmt)

        return app_config_versions, paginator

    async def get_debug_conversation_summary(self, app_id: UUID, account: Account) -> str:
        """根据传递的应用id+账号获取指定应用的调试会话长期记忆"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、获取应用的草稿配置，并校验长期记忆是否启用
        draft_app_config = await self.get_draft_app_config(app_id, account)
        if draft_app_config["long_term_memory"]["enable"] is False:
            raise FailedException("该应用并未开启长期记忆，无法获取")

        # 3、获取当前账号在该应用下的调试会话长期记忆
        debug_conversation = await self.get_or_create_debug_conversation(app, account)
        return debug_conversation.summary

    async def update_debug_conversation_summary(self, app_id: UUID, summary: str, account: Account) -> Conversation:
        """根据传递的应用id+总结更新指定应用的调试长期记忆"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、获取应用的草稿配置，并校验长期记忆是否启用
        draft_app_config = await self.get_draft_app_config(app_id, account)
        if draft_app_config["long_term_memory"]["enable"] is False:
            raise FailedException("该应用并未开启长期记忆，无法获取")

        # 3、更新当前账号的调试会话长期记忆
        debug_conversation = await self.get_or_create_debug_conversation(app, account)
        await self.update(debug_conversation, summary=summary)

        return debug_conversation

    async def delete_debug_conversation(self, app_id: UUID, account: Account) -> App:
        """根据传递的应用id，删除当前账号在该应用下的调试会话"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、查询当前账号在该应用下的调试会话，存在则软删除
        stmt = (
            select(Conversation)
            .where(
                Conversation.app_id == app.id,
                Conversation.created_by == account.id,
                Conversation.invoke_from == InvokeFrom.DEBUGGER,
                Conversation.is_deleted.is_(False),
            )
            .order_by(desc(Conversation.created_at))
            .limit(1)
        )
        conversation = (await self.db.scalars(stmt)).first()
        if conversation:
            await self.update(conversation, is_deleted=True)

        return app

    async def fallback_history_to_draft(
            self,
            app_id: UUID,
            app_config_version_id: UUID,
            account: Account,
    ) -> AppConfigVersion:
        """根据传递的应用id、历史配置版本id、账号信息，回退特定配置到草稿"""
        # 1、校验应用权限并获取信息
        app = await self.get_app(app_id, account)

        # 2、查询指定的历史版本配置id
        app_config_version = await self.get(AppConfigVersion, app_config_version_id)
        if app_config_version is None:
            raise NotFoundException("该历史版本配置不存在，请核实后重试")

        # 3、校验历史版本配置信息（剔除已删除的工具、知识库、工作流）
        draft_app_config_dict = app_config_version.__dict__.copy()
        remove_fields(draft_app_config_dict, [
            "id", "app_id", "version", "config_type", "updated_at", "created_at", "updated_by", "created_by",
            "_sa_instance_state"
        ])

        # 4、检验历史版本配置信息
        draft_app_config_dict = await self._validate_draft_app_config(draft_app_config_dict, account)
        # 5、更新草稿配置信息
        draft_app_config_record = await self.get_or_create_draft_app_config(app)
        await self.update(
            draft_app_config_record,
            # TODO：更新时间
            updated_at=datetime.now(),
            **draft_app_config_dict,
        )

        return draft_app_config_record

    async def prepare_debug_chat(
            self,
            app_id: UUID,
            req: DebugChatReq,
            account: Account,
    ) -> dict:
        """SSE 流式输出的前置准备：在流开始前完成全部校验与副作用。"""
        app = await self.get_app(app_id, account)
        draft_app_config = await self.get_draft_app_config(app_id, account)
        # 1、获取当前账号在该应用下的调试会话信息（按账号隔离，避免多用户串话）
        debug_conversation = await self.get_or_create_debug_conversation(app, account)

        # 2、新建消息
        file_infos, attachments_text = await self.attachment_service.load_attachments(
            req.file_ids or [], account
        )
        message = await self.create(
            Message,
            app_id=app_id,
            conversation_id=debug_conversation.id,
            invoke_from=InvokeFrom.DEBUGGER,
            created_by=account.id,
            updated_by=account.id,
            query=req.query,
            image_urls=req.image_urls,
            file_urls=file_infos,
            status=MessageStatus.NORMAL,
        )
        # 附件文本注入 LLM（临时属性，不落库到 query；ChatRunner 读取）
        message.attachment_text = attachments_text
        # 2.1、透传恢复标记（临时属性，Message 模型无此列；ChatRunner 读取 resume_trigger 决定是否断点续跑）
        message.resume_trigger = req.resume
        # 2.2、透传被恢复的原始消息 id（断点按 message_id 定位；ChatRunner 注入编排器 state 用于读断点）
        message.resume_message_id = req.resume_message_id or None

        # 3、加载用户画像（语义记忆：当前有效事实 -> 画像文本；长期记忆未开启时不读取）
        user_profile = ""
        if draft_app_config.get("long_term_memory", {}).get("enable"):
            provider = await self.memory_provider_resolver.resolve(draft_app_config)
            user_profile = await provider.get_user_profile(
                draft_app_config, app_id, account.id,
            )

        return {
            "app": app,
            "app_config": draft_app_config,
            "conversation": debug_conversation,
            "message": message,
            "user_profile": user_profile,
        }

    def stream_debug_chat(
            self,
            app_id: UUID,
            req: DebugChatReq,
            account: Account,
            prepared: dict,
    ) -> AsyncGenerator:
        """SSE 流式（prepared 由 prepare_debug_chat 产出——流开始前校验/副作用已完成，
        生成器内不再抛业务前置异常）。"""
        # 4、委托统一对话执行器（async for 迭代流式事件）
        async def _stream():
            async for event in self.chat_runner.run(
                app=prepared["app"],
                app_config=prepared["app_config"],
                conversation=prepared["conversation"],
                message=prepared["message"],
                account=account,
                invoke_from=InvokeFrom.DEBUGGER,
                user_profile=prepared["user_profile"],
            ):
                yield event

        return _stream()

    async def debug_chat(self, app_id: UUID, req: DebugChatReq, account: Account, flask_app=None) -> AsyncGenerator:
        """根据传递的应用id+提问query向特定的应用发起会话调试"""
        prepared = await self.prepare_debug_chat(app_id, req, account)
        async for event in self.stream_debug_chat(app_id, req, account, prepared):
            yield event

    async def stop_debug_chat(self, app_id: UUID, task_id: UUID, account: Account) -> None:
        """根据传递的应用id+任务id+账号，停止某个应用的调试会话，中断流式事件"""
        await self.get_app(app_id, account)
        AgentQueueManager.set_stop_flag(task_id, InvokeFrom.DEBUGGER, account.id)

    async def get_debug_conversation_messages_with_page(
            self,
            app_id: UUID,
            req: GetDebugConversationMessagesWithPageReq,
            account: Account
    ) -> tuple[list[Message], Paginator]:
        """根据传递的应用id + 请求数据，获取调试会话消息列表分页数据"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、获取当前账号在该应用下的调试会话
        debug_conversation = await self.get_or_create_debug_conversation(app, account)

        # 3、构建分页器并构建游标条件
        paginator = Paginator(db=self.db, req=req)
        filters = []
        if req.created_at:
            # 4、将时间戳转换成DateTime
            created_at_datetime = datetime.fromtimestamp(req.created_at)
            filters.append(Message.created_at <= created_at_datetime)

        # 5、执行分页并查询数据
        # 仍在进行中（running / awaiting_input）的这一轮 answer 还是空串，必须豁免下面
        # "normal 且 answer 为空则隐藏"，否则刷新后这条消息查不到、前端拿不到 run_id 重连。
        # 时间窗限定同 conversation_service：无人接手的孤儿 running run 不复活成空气泡消息。
        # 锚必须用服务端 now()：created_at 由 DB 的 CURRENT_TIMESTAMP(UTC) 写入，
        # 和本机 Python 的 datetime.now()(UTC+8) 差 8 小时，用后者会把全部行静默排除。
        live_run_message_ids = (
            select(AgentRun.message_id)
            .where(
                AgentRun.status.in_(list(LIVE_RUN_STATUSES)),
                AgentRun.parent_run_id.is_(None),
                AgentRun.created_at >= func.now() - timedelta(seconds=LIVE_RUN_VISIBLE_SECONDS),
            )
        )
        stmt = (
            select(Message)
            .options(joinedload(Message.agent_thoughts))
            .where(
                Message.conversation_id == debug_conversation.id,
                # 展示 normal/stop/timeout/error——中断、超时、出错的任务也保留已输出内容和「继续执行」入口。
                # normal 仍需 answer 非空（隐藏占位消息）；终态（stop/timeout/error）即使 answer 为空也展示。
                Message.status.in_([
                    MessageStatus.NORMAL,
                    MessageStatus.STOP,
                    MessageStatus.TIMEOUT,
                    MessageStatus.ERROR,
                ]),
                or_(
                    Message.answer != "",
                    Message.status != MessageStatus.NORMAL,
                    Message.id.in_(live_run_message_ids),
                ),
                *filters,  # 你的动态过滤条件
            )
            .order_by(desc(Message.created_at))
        )
        messages = await paginator.paginate(stmt)

        # 6、标记每条消息是否可断点续跑（动态属性，Message 模型无 can_resume 列）
        # 仅 stop/timeout/error 状态消息才可能可恢复（EXISTS 查询避免 N+1）
        # 按 message_id 定位断点（不再依赖 query 字符串精确匹配——同一会话多轮消息的断点归属各自消息）
        sub_task_service = SubTaskService(db=self.db)
        for m in messages:
            m.can_resume = (
                m.status in (MessageStatus.STOP, MessageStatus.TIMEOUT, MessageStatus.ERROR)
                and await sub_task_service.has_resumable_checkpoints(m.id)
            )

        # 6.1、注入每条消息"最新 run"的终态（run_status）：前端据此把已终结的消息
        # 从"运行中"误判摘出（终结显示「继续执行」/只读，运行中才显示可停止）。
        message_ids = [m.id for m in messages]
        if message_ids:
            # run_id 一并透出：前端刷新后要按 run_id 调 resume 端点重挂还在跑的 run
            run_rows = (
                await self.db.execute(
                    select(AgentRun.message_id, AgentRun.status, AgentRun.id)
                    .where(
                        AgentRun.message_id.in_(message_ids),
                        AgentRun.parent_run_id.is_(None),
                    )
                    .order_by(AgentRun.message_id, AgentRun.version.desc())
                )
            ).all()
            latest_run_by_msg: dict = {}
            for message_id, run_status, run_id in run_rows:
                if message_id not in latest_run_by_msg:
                    latest_run_by_msg[message_id] = (run_status, run_id)
            for m in messages:
                latest = latest_run_by_msg.get(m.id)
                m.run_status = latest[0] if latest else ""
                m.run_id = str(latest[1]) if latest and latest[1] else ""

        return messages, paginator

    async def get_or_create_debug_conversation(self, app: App, account: Account) -> Conversation:
        """获取或创建当前账号在该应用下的调试会话（按账号隔离，避免多用户共用同一会话）"""
        # 1、查询当前账号在该应用下的调试会话，存在则直接复用
        stmt = (
            select(Conversation)
            .where(
                Conversation.app_id == app.id,
                Conversation.created_by == account.id,
                Conversation.invoke_from == InvokeFrom.DEBUGGER,
                Conversation.is_deleted.is_(False),
            )
            .order_by(desc(Conversation.created_at))
            .limit(1)
        )
        conversation = (await self.db.scalars(stmt)).first()
        if conversation:
            return conversation

        # 2、不存在则创建一条归属于当前账号的调试会话（独立事务边界）
        conversation = Conversation(
            app_id=app.id,
            name="New Conversation",
            invoke_from=InvokeFrom.DEBUGGER,
            created_by=account.id,
            updated_by=account.id,
        )
        self.db.add(conversation)
        await self.db.flush()
        await self.db.commit()  # 独立事务边界

        return conversation

    async def get_published_config(self, app_id: UUID, account: Account) -> dict[str, Any]:
        """根据传递的应用id+账号，获取应用的发布配置"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、构建发布配置并返回
        return {
            "web_app": {
                "token": await self.get_token_with_default(app),
                "status": app.status,
            }
        }

    async def regenerate_web_app_token(self, app_id: UUID, account: Account) -> str:
        """根据传递的应用id+账号，重新生成WebApp凭证标识"""
        # 1、获取应用信息并校验权限
        app = await self.get_app(app_id, account)

        # 2、判断应用是否已发布
        if app.status != AppStatus.PUBLISHED.value:
            raise FailedException("应用未发布，无法生成WebApp凭证标识")

        # 3、重新生成token并更新数据
        token = generate_random_string(16)
        await self.update(app, token=token)

        return token

    async def _validate_draft_app_config(self, draft_app_config: dict[str, Any], account: Account) -> dict[str, Any]:
        """校验传递的应用草稿配置信息，返回校验后的数据"""
        # 1、校验上传的草稿配置中对应的字段，至少拥有一个可以更新的配置
        acceptable_fields = [
            "model_config", "dialog_round", "preset_prompt",
            "tools", "workflows", "datasets", "retrieval_config",
            "long_term_memory", "opening_statement", "opening_questions",
            "speech_to_text", "text_to_speech", "review_config", "suggested_after_answer",
            "skills", "orchestrator_config"
        ]
        # 2、判断传递的草稿配置是否在可接受字段内
        if (
                not draft_app_config
                or not isinstance(draft_app_config, dict)
                or set(draft_app_config.keys()) - set(acceptable_fields)
        ):
            raise ValidateException("草稿配置字段出错，请核实后重试")

        # 3、校验model_config字段，provider/modeL使用严格校验（出错的时候直接抛出），parameters使用宽松校验，出错时使用默认值
        if "model_config" in draft_app_config:
            # 3.1 获取模型配置并判断数据是否为字典
            model_config = draft_app_config["model_config"]
            if not isinstance(model_config, dict):
                raise ValidateException("模型配置格式错误，请核实后重试")

            # 3.2 判断model_config键信息是否正确
            if set(model_config.keys()) != {"provider", "model", "parameters"}:
                raise ValidateException("模型配置格式错误，请核实后重试")

            # 3.3 判断模型提供者信息是否正确
            if not model_config["provider"] or not isinstance(model_config["provider"], str):
                raise ValidateException("模型服务提供商类型必须为字符串")

            # 3.4 判断模型信息是否正确
            if not model_config["model"] or not isinstance(model_config["model"], str):
                raise ValidateException("模型名字必须是否字符串")

            # 3.4.1 custom_api 是按账号懒合并的虚拟 provider：此处同步校验路径可能尚未合并，
            #       不能调会抛 NotFound 的 get_provider/get_model_entity。对 model key 做轻量校验即放行
            #       （用户自有模型，载入期由 load_language_model 强校验）。
            if model_config["provider"] == CUSTOM_API_PROVIDER:
                if not model_config["model"].startswith(f"{CUSTOM_API_PROVIDER}/"):
                    raise ValidateException("该服务提供商下不存在该模型，请核实后重试")
                if not isinstance(model_config["parameters"], dict):
                    model_config["parameters"] = {}
                draft_app_config["model_config"] = model_config
            else:
                provider = self.language_model_manager.get_provider(model_config["provider"])
                if provider is None:
                    raise ValidateException("该模型服务提供商不存在，请核实后重试")

                model_entity = provider.get_model_entity(model_config["model"])
                if model_entity is None:
                    raise ValidateException("该服务提供商下不存在该模型，请核实后重试")

                # 3.5 剔除传递的多余的parameter，亦或者是少传递的参数使用默认值补上
                parameters = {}
                for parameter in model_entity.parameters:
                    # 3.6 从model_config中获取参数值，如果不存在则设置为默认值
                    parameter_value = model_config["parameters"].get(parameter.name, parameter.default)

                    # 3.7 判断参数是否必填
                    if parameter.required:
                        # 3.8 参数必填，则值不允许为None，如果为None则设置默认值
                        if parameter_value is None:
                            parameter_value = parameter.default
                        else:
                            # 3.9 值非空则校验数据类型是否正确，不正确则设置默认值
                            if get_value_type(parameter_value) != parameter.type.value:
                                parameter_value = parameter.default
                    else:
                        # 3.10 参数非必填，数据非空的情况下需要校验
                        if (
                                parameter_value is not None
                                and get_value_type(parameter_value) != parameter.type.value
                        ):
                            parameter_value = parameter.default

                    # 3.11 判断参数是否存在options，如果存在则数值必须在options中选择
                    if parameter.options and parameter_value not in parameter.options:
                        parameter_value = parameter.default

                    # 3.12 参数类型为int/float，如果存在min/max时候需要校验
                    if (
                            parameter.type in [ModelParameterType.INT, ModelParameterType.FLOAT]
                            and parameter_value is not None
                            # 3.13 校验数值的min/max
                            and (
                                (parameter.min is not None and parameter_value < parameter.min)
                                or (parameter.max is not None and parameter_value > parameter.max)
                            )
                    ):
                        parameter_value = parameter.default

                    parameters[parameter.name] = parameter_value

                # 3.14 覆盖Agent配置中的模型配置
                model_config["parameters"] = parameters
                draft_app_config["model_config"] = model_config

        # 4、校验dialog_round上下文轮数，校验数据类型以及范围
        if "dialog_round" in draft_app_config:
            dialog_round = draft_app_config["dialog_round"]
            if (
                    not isinstance(dialog_round, int)
                    or not (0 <= dialog_round <= 100)
            ):
                raise ValidateException("携带上下文轮数范围为0-100")

        # 5、校验preset_prompt
        if "preset_prompt" in draft_app_config:
            preset_prompt = draft_app_config["preset_prompt"]
            if (
                    not isinstance(preset_prompt, str)
                    or len(preset_prompt) > 20000
            ):
                raise ValidateException("人设与回复逻辑必须是字符串，长度在0-20000个字符")

        # 6、校验tools工具
        if "tools" in draft_app_config:
            tools = draft_app_config["tools"]
            validate_tools = []
            # 6.1 tools类型必须为列表，空列表则代表不绑定任何工具
            if not isinstance(tools, list):
                raise ValidateException("工具列表必须是列表型数据")
            # 6.2 tools的长度不能超过12
            if len(tools) > 12:
                raise ValidateException("Agent绑定的工具数不能超过12")
            # 6.3 循环校验工具里的每一个参数
            for tool in tools:
                # 6.4 校验tool非空并且类型为字典
                if not tool or not isinstance(tool, dict):
                    raise ValidateException("绑定插件工具参数出错")
                # 6.5 校验工具的参数是不是type、provider_id、tool_id、params
                if set(tool.keys()) != {"type", "provider_id", "tool_id", "params"}:
                    raise ValidateException("绑定插件工具参数出错")
                # 6.6 校验type类型是否为builtin_tool以及api_tool
                if tool["type"] not in ["builtin_tool", "api_tool"]:
                    raise ValidateException("绑定插件工具参数出错")
                # 6.7 校验provider_id和tool_id
                if (
                        not tool["provider_id"]
                        or not tool["tool_id"]
                        or not isinstance(tool["provider_id"], str)
                        or not isinstance(tool["tool_id"], str)
                ):
                    raise ValidateException("插件提供者或者插件标识参数出错")
                # 6.8 校验params参数，类型为字典
                if not isinstance(tool["params"], dict):
                    raise ValidateException("插件自定义参数格式错误")
                # 6.9 校验对应的工具是否存在，而且需要划分成builtin_tool和api_tool
                if tool["type"] == "builtin_tool":
                    builtin_tool = self.builtin_provider_manager.get_tool(tool["provider_id"], tool["tool_id"])
                    if not builtin_tool:
                        continue
                else:
                    api_tool = await self.db.scalar(
                        select(ApiTool).where(
                            ApiTool.provider_id == tool["provider_id"],
                            ApiTool.name == tool["tool_id"],
                            ApiTool.account_id == account.id,
                        )
                    )
                    if not api_tool:
                        continue
                validate_tools.append(tool)

            # 6.10 校验绑定的工具是否重复
            check_tools = [f"{tool['provider_id']}_{tool['tool_id']}" for tool in validate_tools]
            if len(set(check_tools)) != len(validate_tools):
                raise ValidateException("绑定插件存在重复")

            # 6.11 重新赋值工具
            draft_app_config["tools"] = validate_tools

        # 7、校验workflows，提取已发布+权限正确的工作流列表进行绑定（更新配置阶段不校验工作流是否可以正常运行）
        if "workflows" in draft_app_config:
            workflows = draft_app_config["workflows"]

            # 7.1 判断workflows是否为列表
            if not isinstance(workflows, list):
                raise ValidateException("绑定工作流列表参数格式错误")

            # 7.2 判断关联的工作流列表是否超过5个
            if len(workflows) > 5:
                raise ValidateException("Agent绑定的工作流数量不能超过5个")

            # 7.3 循环校验工作流的每个参数，类型必须为UUID
            for workflow_id in workflows:
                try:
                    UUID(workflow_id)
                except ValueError as _:
                    raise ValidateException("工作流参数必须是UUID")

            # 7.4 判断是否重复关联了工作流
            if len(set(workflows)) != len(workflows):
                raise ValidateException("绑定工作流存在重复")

            # 7.5 校验关联工作流的权限，剔除不属于当前账号，亦或者未发布的工作流
            stmt = (
                select(Workflow)
                .where(
                    Workflow.id.in_(workflows),
                    Workflow.account_id == account.id,
                    Workflow.status == WorkflowStatus.PUBLISHED,
                )
            )
            workflow_records = (await self.db.scalars(stmt)).all()
            workflow_sets = {str(workflow_record.id) for workflow_record in workflow_records}
            draft_app_config["workflows"] = [workflow_id for workflow_id in workflows if workflow_id in workflow_sets]

        # 8、校验datasets知识库列表
        if "datasets" in draft_app_config:
            datasets = draft_app_config["datasets"]
            # 8.1 判断datasets类型是否为列表
            if not isinstance(datasets, list):
                raise ValidateException("绑定知识库列表参数格式错误")
            # 8.2 判断关联的知识库列表是否超过5个
            if len(datasets) > 5:
                raise ValidateException("Agent绑定的知识库数量不能超过5个")
            # 8.3 循环校验知识库的每个参数
            for dataset_id in datasets:
                try:
                    UUID(dataset_id)
                except ValueError:
                    raise ValidateException("知识库列表参数必须是UUID")
            # 8.4 判断是否传递了重复的知识库
            if len(set(datasets)) != len(datasets):
                raise ValidateException("绑定知识库存在重复")

            # 8.5 校验绑定的知识库权限，剔除不属于当前账号的知识库
            stmt = (
                select(Dataset).where(
                    Dataset.id.in_(datasets),
                    Dataset.account_id == account.id,
                )
            )
            dataset_records = (await self.db.execute(stmt)).scalars().all()
            dataset_sets = {str(dataset_record.id) for dataset_record in dataset_records}
            draft_app_config["datasets"] = [dataset_id for dataset_id in datasets if dataset_id in dataset_sets]

        # 校验skills技能列表
        if "skills" in draft_app_config:
            skills = draft_app_config["skills"]
            # 判断skills类型是否为列表
            if not isinstance(skills, list):
                raise ValidateException("绑定skills列表参数格式错误")
            # 判断关联的技能列表是否超过5个
            if len(skills) > 5:
                raise ValidateException("Agent绑定的skills数量不能超过5个")
            # 循环校验技能的每个参数
            for skill_id in skills:
                try:
                    UUID(skill_id)
                except ValueError:
                    raise ValidateException("skills列表参数必须是UUID")
            # 判断是否传递了重复的技能
            if len(set(skills)) != len(skills):
                raise ValidateException("绑定skills存在重复")

            # 校验绑定的技能是否存在且对当前用户可见，剔除不可见的技能
            stmt = (
                select(Skill).where(
                    Skill.id.in_(skills),
                    or_(
                        Skill.account_id == account.id,
                        Skill.visibility == "public",
                    ),
                )
            )
            skill_records = (await self.db.execute(stmt)).scalars().all()
            skill_sets = {str(skill_record.id) for skill_record in skill_records}
            draft_app_config["skills"] = [skill_id for skill_id in skills if skill_id in skill_sets]

        # 9、校验retrieval_config检索配置
        if "retrieval_config" in draft_app_config:
            retrieval_config = draft_app_config["retrieval_config"]
            # 9.1 判断检索配置非空且类型为字典
            if not retrieval_config or not isinstance(retrieval_config, dict):
                raise ValidateException("检索配置格式错误")
            # 9.2 校验必填字段（兼容旧结构；rerank/query_rewrite/agentic 为可选扩展键）
            required_keys = {"retrieval_strategy", "k", "score"}
            allowed_keys = required_keys | {"rerank", "query_rewrite", "agentic_enable", "max_rounds"}
            if not required_keys.issubset(set(retrieval_config.keys())) or not set(retrieval_config.keys()).issubset(allowed_keys):
                raise ValidateException("检索配置格式错误")
            # 9.3 校验检索策略是否正确
            if retrieval_config["retrieval_strategy"] not in ["semantic", "full_text", "hybrid"]:
                raise ValidateException("检索策略不正确")
            # 9.4 校验最大召回数量
            if not isinstance(retrieval_config["k"], int) or not (0 <= retrieval_config["k"] <= 10):
                raise ValidateException("最大召回数量范围为0-10")
            # 9.5 校验得分/最小匹配度
            if not isinstance(retrieval_config["score"], float) or not (0 <= retrieval_config["score"] <= 1):
                raise ValidateException("最小匹配度范围为0-1")
            # 9.6 校验可选的 rerank 配置
            if "rerank" in retrieval_config:
                rerank = retrieval_config["rerank"]
                if (
                        not isinstance(rerank, dict)
                        or set(rerank.keys()) != {"enable", "top_n"}
                        or not isinstance(rerank.get("enable"), bool)
                        or not isinstance(rerank.get("top_n"), int)
                        or not (1 <= rerank["top_n"] <= 50)
                ):
                    raise ValidateException("rerank配置格式错误")
            # 9.7 校验可选的 query_rewrite 配置
            if "query_rewrite" in retrieval_config:
                query_rewrite = retrieval_config["query_rewrite"]
                if (
                        not isinstance(query_rewrite, dict)
                        or set(query_rewrite.keys()) != {"enable"}
                        or not isinstance(query_rewrite.get("enable"), bool)
                ):
                    raise ValidateException("query_rewrite配置格式错误")
            # 9.8 校验可选的 Agentic 重检配置
            if "agentic_enable" in retrieval_config and not isinstance(retrieval_config["agentic_enable"], bool):
                raise ValidateException("agentic_enable配置格式错误")
            if "max_rounds" in retrieval_config:
                if not isinstance(retrieval_config["max_rounds"], int) or not (1 <= retrieval_config["max_rounds"] <= 3):
                    raise ValidateException("Agentic重检轮数范围为1-3")

        # 10、校验long_term_memory长期记忆配置
        if "long_term_memory" in draft_app_config:
            long_term_memory = draft_app_config["long_term_memory"]
            # 10.1 校验长期记忆格式（键集 {enable, provider, team_id, agent_id, user_id}，enable 必填布尔）
            if not long_term_memory or not isinstance(long_term_memory, dict):
                raise ValidateException("长期记忆设置格式错误")
            keys = set(long_term_memory.keys())
            if (
                    not {"enable"} <= keys <= {"enable", "provider", "team_id", "agent_id", "user_id"}
                    or not isinstance(long_term_memory["enable"], bool)
            ):
                raise ValidateException("长期记忆设置格式错误")
            # 10.2 校验记忆系统取值（default/builtin/tencent）
            provider = long_term_memory.get("provider", "default")
            if provider not in ("default", "builtin", "tencent"):
                raise ValidateException("长期记忆记忆系统设置错误")

        # 11、校验opening_statement对话开场白
        if "opening_statement" in draft_app_config:
            opening_statement = draft_app_config["opening_statement"]
            # 11.1 校验对话开场白类型以及长度
            if not isinstance(opening_statement, str) or len(opening_statement) > 2000:
                raise ValidateException("对话开场白的长度范围是0-2000")

        # 12、校验opening_questions开场建议问题列表
        if "opening_questions" in draft_app_config:
            opening_questions = draft_app_config["opening_questions"]
            # 12.1 校验是否为列表，并且长度不超过3
            if not isinstance(opening_questions, list) or len(opening_questions) > 3:
                raise ValidateException("开场建议问题不能超过3个")
            # 12.2 开场建议问题每个元素都是一个字符串
            for opening_question in opening_questions:
                if not isinstance(opening_question, str):
                    raise ValidateException("开场建议问题必须是字符串")

        # 13、校验语音转文本
        if "speech_to_text" in draft_app_config:
            speech_to_text = draft_app_config["speech_to_text"]
            # 13.1 校验语音转文本格式
            if not speech_to_text or not isinstance(speech_to_text, dict):
                raise ValidateException("语音转文本设置格式错误")
            # 13.2 校验语音转文本属性
            if (
                    set(speech_to_text.keys()) != {"enable"}
                    or not isinstance(speech_to_text["enable"], bool)
            ):
                raise ValidateException("语音转文本设置格式错误")

        # 14.校验text_to_speech文本转语音设置
        if "text_to_speech" in draft_app_config:
            text_to_speech = draft_app_config["text_to_speech"]
            # 14.1 校验字典格式
            if not isinstance(text_to_speech, dict):
                raise ValidateException("文本转语音设置格式错误")
            # 14.2 校验字段类型
            if (
                    set(text_to_speech.keys()) != {"enable", "voice", "auto_play"}
                    or not isinstance(text_to_speech["enable"], bool)
                    or text_to_speech["voice"] not in ALLOWED_AUDIO_VOICES
                    or not isinstance(text_to_speech["auto_play"], bool)
            ):
                raise ValidateException("文本转语音设置格式错误")

        # 15、校验回答后生成建议问题
        if "suggested_after_answer" in draft_app_config:
            suggested_after_answer = draft_app_config["suggested_after_answer"]
            # 15.1 校验回答后生成建议问题格式
            if not suggested_after_answer or not isinstance(suggested_after_answer, dict):
                raise ValidateException("回答后生成建议问题格式错误")
            # 15.2 校验回答后生成建议问题属性
            if (
                    set(suggested_after_answer.keys()) != {"enable"}
                    or not isinstance(suggested_after_answer["enable"], bool)
            ):
                raise ValidateException("回答后生成建议问题格式错误")

        # 16. 校验review_config审核配置
        if "review_config" in draft_app_config:
            review_config = draft_app_config["review_config"]
            # 16.1 校验字段格式，非空
            if not review_config or not isinstance(review_config, dict):
                raise ValidateException("审核配置格式错误")
            # 16.2 校验字段信息
            if set(review_config.keys()) != {"enable", "keywords", "inputs_config", "outputs_config"}:
                raise ValidateException("审核配置格式错误")
            # 16.3 校验enable
            if not isinstance(review_config["enable"], bool):
                raise ValidateException("review.enable格式错误")
            # 16.4 校验keywords
            if (
                    not isinstance(review_config["keywords"], list)
                    or (review_config["enable"] and len(review_config["keywords"]) == 0)
                    or len(review_config["keywords"]) > 100
            ):
                raise ValidateException("review.keywords非空且不能超过100个关键词")
            for keyword in review_config["keywords"]:
                if not isinstance(keyword, str):
                    raise ValidateException("review.keywords敏感词必须是字符串")

            # 16.5 校验inputs_config输入配置
            if (
                    not review_config["inputs_config"]
                    or not isinstance(review_config["inputs_config"], dict)
                    or set(review_config["inputs_config"].keys()) != {"enable", "preset_response"}
                    or not isinstance(review_config["inputs_config"]["enable"], bool)
                    or not isinstance(review_config["inputs_config"]["preset_response"], str)
            ):
                raise ValidateException("review.inputs_config必须是一个字典")

            # 16.6 校验outputs_config输出配置
            if (
                    not review_config["outputs_config"]
                    or not isinstance(review_config["outputs_config"], dict)
                    or set(review_config["outputs_config"].keys()) != {"enable"}
                    or not isinstance(review_config["outputs_config"]["enable"], bool)):
                raise ValidateException("review.outputs_config格式错误")

            # 16.7 在开启审核模块的时候，必须确保inputs_config或者是outputs_config至少有一个是开启的
            if review_config["enable"]:
                if (
                        review_config["inputs_config"]["enable"] is False
                        and review_config["outputs_config"]["enable"] is False
                ):
                    raise ValidateException("输入审核和输出审核至少需要开启一项")
                if (
                        review_config["inputs_config"]["enable"]
                        and review_config["inputs_config"]["preset_response"].strip() == ""
                ):
                    raise ValidateException("输入审核预设响应不能为空")

        return draft_app_config
