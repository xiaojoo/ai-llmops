#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/27 19:23
@Author : sunxiaojie
@File   : api_tool_service.py
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from internal.core.tools.api_tools.entities import OpenApiSchema
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.exception import NotFoundException, ValidateException
from internal.model import Account, ApiTool, ApiToolProvider
from internal.schema.api_tool_schema import (
    CreateApiToolReq,
    GetApiToolProvidersWithPageReq,
)
from internal.service import BaseService
from package.paginator import Paginator


@dataclass
class ApiToolService(BaseService):
    """自定义API插件服务"""
    db: AsyncSession
    api_provider_manager: ApiProviderManager

    async def update_api_tool_provider(self, provider_id: UUID, req: CreateApiToolReq, account: Account):
        """根据传递的provider_id+req更新对应的API工具提供者信息"""
        # 1、根据传递的provider_id查找API工具提供者信息并校验
        api_tool_provider = await self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None or api_tool_provider.account_id != account.id:
            raise ValidateException("该工具提供者不存在")

        # 2、校验openapi_schema数据
        openapi_schema = self.parse_openapi_schema(req.openapi_schema)
        # 3、检测当前账号是否已经创建了同名的工具提供者，如果是则抛出错误
        stmt = select(ApiToolProvider).where(
            ApiToolProvider.account_id == account.id,
            ApiToolProvider.name == req.name,
            ApiToolProvider.id != api_tool_provider.id,
        )
        check_api_tool_provider = (await self.db.execute(stmt)).scalars().one_or_none()
        if check_api_tool_provider:
            raise ValidateException(f"该工具提供者名字{req.name}已存在")

        # 4、删除该工具提供者下的所有工具（独立事务边界）
        stmt = delete(ApiTool).where(
            ApiTool.provider_id == api_tool_provider.id,
            ApiTool.account_id == account.id,
        )
        await self.db.execute(stmt)
        await self.db.commit()  # 独立事务边界

        # 5、修改工具提供者信息
        await self.update(
            api_tool_provider,
            name=req.name,
            icon=req.icon,
            headers=req.headers,
            openapi_schema=req.openapi_schema,
        )

        # 6、新增工具信息从而完成覆盖更新
        for path, path_item in openapi_schema.paths.items():
            for method, method_item in path_item.items():
                await self.create(
                    ApiTool,
                    account_id=account.id,
                    provider_id=api_tool_provider.id,
                    name=method_item.get("operationId"),
                    description=method_item.get("description"),
                    url=f"{openapi_schema.server}{path}",
                    method=method,
                    parameters=method_item.get("parameters", []),
                )

    async def get_api_tool_providers_with_page(
            self,
            req: GetApiToolProvidersWithPageReq,
            account: Account
    ) -> tuple[list[Any], Paginator]:
        """获取自定义API工具服务提供者分页列表数据"""
        # 1、构建分页查询器
        paginator = Paginator(db=self.db, req=req)
        # 2、构建筛选器
        filters = [ApiToolProvider.account_id == account.id]
        if req.search_word:
            filters.append(ApiToolProvider.name.ilike(f"%{req.search_word}%"))
        # 3、执行分页并获取数据（selectinload 预加载 tools 关系，避免 async 下 lazy load MissingGreenlet）
        stmt = (
            select(ApiToolProvider)
            .options(selectinload(ApiToolProvider.tools))
            .where(*filters)
            .order_by(desc(ApiToolProvider.created_at))
        )
        api_tool_providers = await paginator.paginate(stmt)
        return api_tool_providers, paginator

    async def get_api_tool(self, provider_id: UUID, tool_name: str, account: Account) -> ApiTool:
        """根据传递的provider_id+tool_name获取工具的详情信息"""
        stmt = select(ApiTool).where(
            ApiTool.provider_id == provider_id,
            ApiTool.name == tool_name
        )
        api_tool = (await self.db.execute(stmt)).scalars().one_or_none()
        if api_tool is None or api_tool.account_id != account.id:
            raise NotFoundException("该工具不存在")
        return api_tool

    async def get_api_tool_provider(self, provider_id: UUID, account: Account) -> ApiToolProvider:
        """根据传递的provider_id获取API工具提供者信息"""
        # 1、查询数据库获取对应的数据
        api_tool_provider = await self.get(ApiToolProvider, provider_id)
        # 2、检验数据是否为空，并且判断该数据是否属于当前账号
        if api_tool_provider is None or api_tool_provider.account_id != account.id:
            raise NotFoundException("该工具不存在")
        return api_tool_provider

    async def create_api_tool(self, req: CreateApiToolReq, account: Account) -> None:
        """根据传递的请求创建自定义API工具"""
        # 1、检验并提取openapi_schema对应的数据
        openapi_schema = self.parse_openapi_schema(req.openapi_schema)
        # 2、查询当前登录的账号是否已经创建了同名的工具提供者，如果是则抛出错误
        stmt = select(ApiToolProvider).where(
            ApiToolProvider.account_id == account.id,
            ApiToolProvider.name == req.name
        )
        api_tool_provider = (await self.db.execute(stmt)).scalars().one_or_none()
        if api_tool_provider is not None:
            raise ValidateException(f"该工具提供者名字{req.name}已存在")
        # 3、首先创建工具提供者，并获取工具提供者的id信息，然后在创建工具信息
        api_tool_provider = await self.create(
            ApiToolProvider,
            account_id=account.id,
            name=req.name,
            icon=req.icon,
            description=openapi_schema.description,
            openapi_schema=req.openapi_schema,
            headers=req.headers,
        )

        # 4、创建api工具并关联api_tool_provider
        for path, path_item in openapi_schema.paths.items():
            for method, method_item in path_item.items():
                await self.create(
                    ApiTool,
                    account_id=account.id,
                    provider_id=api_tool_provider.id,
                    name=method_item.get("operationId"),
                    description=method_item.get("description"),
                    url=f"{openapi_schema.server}{path}",
                    method=method,
                    parameters=method_item.get("parameters", []),
                )

    async def delete_api_tool_provider(self, provider_id: UUID, account: Account):
        """根据传递的provider_id进行删除工具提供者信息"""
        # 1、先查找数据，检测下provider_id对应的数据是否存在，权限是否正确
        api_tool_provider = await self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None or api_tool_provider.account_id != account.id:
            raise NotFoundException("该工具提供者不存在")

        # 2、删除提供者对应的工具信息（独立事务边界）
        stmt = delete(ApiTool).where(
            ApiTool.provider_id == provider_id,
            ApiTool.account_id == account.id
        )
        await self.db.execute(stmt)

        # 3、删除服务提供者
        await self.db.delete(api_tool_provider)
        await self.db.commit()  # 独立事务边界

    @classmethod
    def parse_openapi_schema(cls, openapi_schema_str: str) -> OpenApiSchema:
        """解析传递的openapi_schema字符串，如果出错则抛出错误"""
        try:
            data = json.loads(openapi_schema_str.strip())
            if not isinstance(data, dict):
                raise ValidateException("传递数据必须符合OpenAPI规范的JSON字符")
        except ValidateException:
            raise
        except Exception:
            raise ValidateException("传递数据必须符合OpenAPI规范的JSON字符")
        return OpenApiSchema(**data)

    async def api_tool_invoke(self):
        provider_id = "30388847-f079-45ec-8e75-02341feaba48"
        tool_name = "YoudaoSuggest"

        stmt = select(ApiTool).where(
            ApiTool.provider_id == provider_id,
            ApiTool.name == tool_name
        )
        api_tool = (await self.db.execute(stmt)).scalars().one_or_none()
        api_tool_provider = api_tool.provider

        from internal.core.tools.api_tools.entities import ToolEntity
        tool = self.api_provider_manager.get_tool(ToolEntity(
            id=provider_id,
            name=tool_name,
            url=api_tool.url,
            method=api_tool.method,
            description=api_tool.description,
            headers=api_tool_provider.headers,
            parameters=api_tool.parameters,
        ))

        # return tool.invoke({"username": "love", "email": "json"})
        return tool.invoke({"q": "love", "doctype": "json"})

    async def debug_api_tool(self, provider_id: UUID, tool_name: str, arguments: dict, account: Account) -> Any:
        """根据传递的provider_id+tool_name+arguments调试API工具"""
        # 1、校验工具提供者是否存在且属于当前账号
        api_tool_provider = await self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None or api_tool_provider.account_id != account.id:
            raise NotFoundException("该工具提供者不存在")

        # 2、校验工具是否存在且属于当前账号
        api_tool = await self.get_api_tool(provider_id, tool_name, account)

        # 3、根据工具配置构建LangChain工具并发起请求
        from internal.core.tools.api_tools.entities import ToolEntity
        tool = self.api_provider_manager.get_tool(ToolEntity(
            id=str(provider_id),
            name=tool_name,
            url=api_tool.url,
            method=api_tool.method,
            description=api_tool.description,
            headers=api_tool_provider.headers,
            parameters=api_tool.parameters,
        ))
        return tool.invoke(arguments)
