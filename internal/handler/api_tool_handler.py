#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/27 15:27
@author : sunxiaojie
@File   : api_tool_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.api_tool_schema import (
    CreateApiToolReq,
    DebugApiToolReq,
    GetApiToolProviderResp,
    GetApiToolProvidersWithPageReq,
    GetApiToolProvidersWithPageResp,
    GetApiToolResp,
    ValidateOpenAPISchemaReq,
)
from internal.service import ApiToolService
from package.paginator import PageModel
from package.response import success_json, success_message_json


@dataclass
class ApiToolHandler:
    """自定义API插件处理器"""
    api_tool_service: ApiToolService

    async def get_api_tool_providers_with_page(self, user: CurrentUser, req: Annotated[GetApiToolProvidersWithPageReq, Query()]) -> None:
        """获取API工具提供者列表信息，改接口支持分页"""
        apt_tool_providers, paginator = await self.api_tool_service.get_api_tool_providers_with_page(req, user)
        resp = [
            GetApiToolProvidersWithPageResp.model_validate(p).model_dump(mode="json")
            for p in apt_tool_providers
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def create_api_tool(self, user: CurrentUser, req: CreateApiToolReq) -> None:
        """创建自定义API工具"""
        await self.api_tool_service.create_api_tool(req, user)
        return success_message_json("创建自定义API插件成功")

    async def update_api_tool_provider(self, user: CurrentUser, provider_id: UUID, req: CreateApiToolReq) -> None:
        """更新自定义API工具提供者信息"""
        await self.api_tool_service.update_api_tool_provider(provider_id, req, user)
        return success_message_json("更新自定义API插件成功")

    async def get_api_tool(self, user: CurrentUser, provider_id: UUID, tool_name: str) -> None:
        """根据传递的provider_id+tool_name获取工具的详情信息"""
        api_tool = await self.api_tool_service.get_api_tool(provider_id, tool_name, user)
        resp = GetApiToolResp.model_validate(api_tool)
        return success_json(resp.model_dump(mode="json"))

    async def debug_api_tool(self, user: CurrentUser, provider_id: UUID, tool_name: str, req: DebugApiToolReq) -> None:
        """根据传递的provider_id+tool_name+arguments调试API工具接口"""
        result = await self.api_tool_service.debug_api_tool(provider_id, tool_name, req.arguments, user)
        return success_json({"result": result})

    async def get_apt_tool_provider(self, user: CurrentUser, provider_id: UUID) -> None:
        """根据传递的provider_id获取工具提供者的原始信息"""
        api_tool_provider = await self.api_tool_service.get_api_tool_provider(provider_id, user)
        resp = GetApiToolProviderResp.model_validate(api_tool_provider)
        return success_json(resp.model_dump(mode="json"))

    async def delete_api_tool_provider(self, user: CurrentUser, provider_id: UUID) -> None:
        """根据传递的provider_id进行删除工具提供者信息"""
        await self.api_tool_service.delete_api_tool_provider(provider_id, user)
        return success_message_json("删除自定义API插件成功")

    async def validate_openapi_schema(self, user: CurrentUser, req: ValidateOpenAPISchemaReq) -> None:
        """校验传递的openapi_schema字符串是否正确"""
        self.api_tool_service.parse_openapi_schema(req.openapi_schema)
        return success_message_json("数据校验成功")
