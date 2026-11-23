#!/usr/bin/env python
"""
@Time    : 2026/1/23 20:42
@Author  : sunxiaojie
@File    : builtin_app_handler.py
"""
from dataclasses import dataclass

from internal.core.language_model import LanguageModelManager
from internal.server.deps import CurrentUser
from internal.schema.builtin_app_schema import (
    AddBuiltinAppToSpaceReq,
    GetBuiltinAppCategoriesResp,
    GetBuiltinAppsResp,
)
from internal.service import BuiltinAppService
from package.response import success_json


@dataclass
class BuiltinAppHandler:
    """LLMOps内置应用处理器"""
    builtin_app_service: BuiltinAppService
    language_model_manager: LanguageModelManager

    async def get_builtin_app_categories(self, user: CurrentUser) -> None:
        """获取内置应用分类列表信息"""
        categories = await self.builtin_app_service.get_categories()
        resp = [
            GetBuiltinAppCategoriesResp.model_validate(c).model_dump(mode="json")
            for c in categories
        ]
        return success_json(resp)

    async def get_builtin_apps(self, user: CurrentUser) -> None:
        """获取所有内置应用列表信息"""
        builtin_apps = await self.builtin_app_service.get_builtin_apps()
        resp = []
        for a in builtin_apps:
            item = GetBuiltinAppsResp.model_validate(a).model_dump(mode="json", by_alias=True)
            mc = item.get("model_config") or {}
            labels = self.language_model_manager.resolve_model_config_display(
                mc.get("provider", ""),
                mc.get("model", ""),
            )
            if labels:
                item["model_config"] = {**mc, **labels}
            resp.append(item)
        return success_json(resp)

    async def add_builtin_app_to_space(self, user: CurrentUser, req: AddBuiltinAppToSpaceReq) -> None:
        """将指定的内置应用添加到个人空间"""
        app = await self.builtin_app_service.add_builtin_app_to_space(req.builtin_app_id, user)
        return success_json({"id": app.id})
