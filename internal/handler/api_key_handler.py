#!/usr/bin/env python
"""
@Time    : 2026/1/20 21:24
@Author  : sunxiaojie
@File    : api_key_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.api_key_schema import (
    CreateApiKeyReq,
    GetApiKeysWithPageResp,
    UpdateApiKeyIsActiveReq,
    UpdateApiKeyReq,
)
from internal.service import ApiKeyService
from package.paginator import PageModel, PaginatorReq
from package.response import success_json, success_message_json


@dataclass
class ApiKeyHandler:
    """API秘钥处理器"""
    api_key_service: ApiKeyService

    async def create_api_key(self, user: CurrentUser, req: CreateApiKeyReq) -> None:
        """创建API秘钥"""
        await self.api_key_service.create_api_key(req, user)
        return success_message_json("创建API密钥成功")

    async def delete_api_key(self, user: CurrentUser, api_key_id: UUID) -> None:
        """根据传递的id删除API秘钥"""
        await self.api_key_service.delete_api_key(api_key_id, user)
        return success_message_json("删除API密钥成功")

    async def update_api_key(self, user: CurrentUser, api_key_id: UUID, req: UpdateApiKeyReq) -> None:
        """根据传递的信息更新API秘钥"""
        await self.api_key_service.update_api_key(api_key_id, user, **req.model_dump())
        return success_message_json("更新API密钥成功")

    async def update_api_key_is_active(self, user: CurrentUser, api_key_id: UUID, req: UpdateApiKeyIsActiveReq) -> None:
        """根据传递的信息更新API秘钥激活状态"""
        await self.api_key_service.update_api_key(api_key_id, user, **req.model_dump())
        return success_message_json("更新API密钥状态成功")

    async def get_api_keys_with_page(self, user: CurrentUser, req: Annotated[PaginatorReq, Query()]) -> None:
        """获取当前登录账号的API秘钥分页列表信息"""
        api_keys, paginator = await self.api_key_service.get_api_keys_with_page(req, user)
        resp = [
            GetApiKeysWithPageResp.model_validate(k).model_dump(mode="json")
            for k in api_keys
        ]
        return success_json(PageModel(list=resp, paginator=paginator))
