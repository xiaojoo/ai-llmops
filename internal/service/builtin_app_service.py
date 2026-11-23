#!/usr/bin/env python
"""
@Time    : 2026/1/23 20:53
@Author  : sunxiaojie
@File    : builtin_app_service.py
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from internal.core.builtin_apps import BuiltinAppManager
from internal.core.builtin_apps.entities.builtin_app_entity import BuiltinAppEntity
from internal.core.builtin_apps.entities.category_entity import CategoryEntity
from internal.entity.app_entity import AppConfigType, AppStatus
from internal.model import Account, App, AppConfigVersion
from internal.service import BaseService


@dataclass
class BuiltinAppService(BaseService):
    """内置应用服务"""
    db: AsyncSession
    builtin_app_manager: BuiltinAppManager

    async def get_categories(self) -> list[CategoryEntity]:
        """获取分类列表信息"""
        return self.builtin_app_manager.get_categories()

    async def get_builtin_apps(self) -> list[BuiltinAppEntity]:
        """获取所有内置应用实体信息列表"""
        return self.builtin_app_manager.get_builtin_apps()

    async def add_builtin_app_to_space(self, builtin_app_id: str, account: Account) -> App:
        """将指定的内置应用添加到个人空间下"""
        # 1、获取内置应用信息，并检测是否存在
        builtin_app = self.builtin_app_manager.get_builtin_app(builtin_app_id)
        if builtin_app is None:
            raise NotImplementedError("该内置应用不存在，请核实后重试")

        # 2、创建应用信息
        app = App(
            account_id=account.id,
            status=AppStatus.DRAFT,
            **builtin_app.model_dump(include={"name", "icon", "description"})
        )
        self.db.add(app)
        await self.db.flush()

        # 3、创建草稿配置信息
        draft_app_config = AppConfigVersion(
            app_id=app.id,
            model_config=builtin_app.language_model_config,
            config_type=AppConfigType.DRAFT,
            **builtin_app.model_dump(include={
                "dialog_round", "preset_prompt", "tools", "retrieval_config", "long_term_memory",
                "opening_statement", "opening_questions", "speech_to_text", "text_to_speech",
                "review_config", "suggested_after_answer",
            })
        )
        self.db.add(draft_app_config)
        await self.db.flush()

        # 4、更新应用草稿配置
        app.draft_app_config_id = draft_app_config.id
        await self.db.commit()  # 独立事务边界

        return app
