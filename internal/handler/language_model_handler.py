#!/usr/bin/env python
"""
@Time    : 2026/1/17 16:12
@Author  : sunxiaojie
@File    : language_model_handler.py
"""
from dataclasses import dataclass

from fastapi.responses import Response

from internal.server.deps import CurrentUser
from internal.service import LanguageModelService
from package.response import success_json


@dataclass
class LanguageModelHandler:
    """语言模型处理器"""
    language_model_service: LanguageModelService

    async def get_language_models(self, user: CurrentUser) -> None:
        """获取所有的语言模型提供商信息"""
        return success_json(await self.language_model_service.get_language_models(account_id=user.id))

    async def get_language_model(self, user: CurrentUser, provider_name: str, model_name: str) -> None:
        """根据传递的提供商名字+模型名字获取模型详细信息"""
        return success_json(
            await self.language_model_service.get_language_model(
                provider_name,
                model_name,
                account_id=user.id,
            )
        )

    async def get_language_model_icon(self, provider_name: str) -> None:
        """根据传递的提供者名字获取指定提供商的icon图标"""
        icon, mimetype = await self.language_model_service.get_language_model_icon(provider_name)
        return Response(content=icon, media_type=mimetype)
