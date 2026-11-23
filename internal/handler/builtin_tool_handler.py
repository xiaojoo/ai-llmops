#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/26 22:37
@author : sunxiaojie
@File   : builtin_tool_handler.py
"""
from dataclasses import dataclass

from fastapi.responses import Response

from internal.service import BuiltinToolService
from package.response import success_json


@dataclass
class BuiltinToolHandler:
    """内置工具处理器"""
    builtin_tool_service: BuiltinToolService

    async def get_builtin_tools(self) -> None:
        """获取LLMOps所有内置工具信息+提供商信息"""
        builtin_tools = self.builtin_tool_service.get_builtin_tools()
        return success_json(builtin_tools)

    async def get_provider_tool(self, provider_name: str, tool_name: str) -> None:
        """根据传递的提供商名字+工具名字获取指定工具的信息"""
        builtin_tool = self.builtin_tool_service.get_provider_tool(provider_name, tool_name)
        return success_json(builtin_tool)

    async def get_provider_icon(self, provider_name: str) -> None:
        """根据传递的提供商获取icon图标流信息"""
        icon, mimetype = self.builtin_tool_service.get_provider_icon(provider_name)
        return Response(content=icon, media_type=mimetype)

    async def get_categories(self) -> None:
        """获取所有内置提供商的分类信息"""
        categories = self.builtin_tool_service.get_categories()
        return success_json(categories)
