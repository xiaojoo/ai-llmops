#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/26 22:48
@Author : sunxiaojie
@File   : builtin_tool_service.py
"""
import mimetypes
import os
from dataclasses import dataclass

from internal.config.settings import get_settings
from internal.core.tools.builtin_tools.categories import BuiltinCategoryManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.exception import NotFoundException


@dataclass
class BuiltinToolService:
    """内置工具服务"""
    builtin_provider_manager: BuiltinProviderManager
    builtin_category_manager: BuiltinCategoryManager

    def get_builtin_tools(self) -> list:
        """获取LLMOps项目中的所有内置提供商+工具信息"""
        # 1、获取所有的提供商
        providers = self.builtin_provider_manager.get_providers()
        # 2、遍历所有的提供商并提取工具信息
        builtin_tools = []
        for provider in providers:
            provider_entity = provider.provider_entity
            builtin_tool = {
                **provider_entity.model_dump(exclude={"icon"}),
                "tools": []
            }
            # 3、循环遍历提取提供者的所有工具实体
            for tool_entity in provider.get_tool_entities():
                # 4、从提供者中获取工具函数
                tool = provider.get_tool(tool_entity.name)
                # 5、构建工具实体信息
                tool_dict = {
                    **tool_entity.model_dump(),
                    "inputs": self.get_tool_inputs(tool),
                }
                builtin_tool["tools"].append(tool_dict)

            builtin_tools.append(builtin_tool)
        return builtin_tools

    def get_provider_tool(self, provider_name: str, tool_name: str):
        """根据传递的提供商名字+工具名字获取指定工具的信息"""
        # 1、获取内置的提供商
        provider = self.builtin_provider_manager.get_provider(provider_name)
        if provider is None:
            raise NotFoundException(tool_name)

        # 2、获取该提供商下的对应工具
        tool_entity = provider.get_tool_entity(tool_name)
        if tool_entity is None:
            raise NotFoundException(f"该工具{tool_name}不存在")

        # 3、组装提供商和工具实体信息
        provider_entity = provider.provider_entity
        tool = provider.get_tool(tool_name)

        builtin_tool = {
            "provider": {**provider_entity.model_dump(exclude={"icon", "created_at"})},
            **tool_entity.model_dump(),
            "created_at": provider_entity.created_at,
            "inputs": self.get_tool_inputs(tool),
        }
        return builtin_tool

    def get_provider_icon(self, provider_name: str) -> tuple[bytes, str]:
        """根据传递的提供商获取icon图标流信息"""
        # 1、获取对应的工具提供者
        provider = self.builtin_provider_manager.get_provider(provider_name)
        if provider is None:
            raise NotFoundException(provider_name)
        if provider is None:
            raise NotFoundException(f"该工具提供商{provider_name}不存在")
        # 2、获取项目的根路径信息
        root_path = str(get_settings().project_root)
        # 3、凭借得到提供者所在的文件夹
        provider_path = os.path.join(
            root_path,
            "internal", "core", "tools", "builtin_tools", "providers", provider_name
        )
        # 4、凭借得到icon对应的路径
        icon_path = os.path.join(provider_path, "_asset", provider.provider_entity.icon)
        # 5、检测icon是否存在
        if not os.path.exists(icon_path):
            raise NotFoundException("该工具提供商_asset下没有提供图标")
        # 6、读取icon的类型
        mimetype, _ = mimetypes.guess_type(icon_path)
        mimetype = mimetype or "application/octet-stream"
        # 7、读取icon的字节数据
        with open(icon_path, "rb") as f:
            byte_data = f.read()
            return byte_data, mimetype

    def get_categories(self):
        """获取所有内置提供商的分类信息"""
        category_map = self.builtin_category_manager.get_category_map()
        return [{
            "name": category["entity"].name,
            "category": category["entity"].category,
            "icon": category["icon"]
        } for category in category_map.values()]

    @classmethod
    def get_tool_inputs(cls, tool) -> list:
        """根据传入的工具获取inputs信息"""
        # if hasattr(tool, "args_schema") and tool.args_schema:
        #     return tool.args_schema.model_json_schema()
        #
        # return {}

        if not hasattr(tool, "args_schema") or not tool.args_schema:
            return []

        schema = tool.args_schema.model_json_schema()
        properties = schema.get("properties", {})
        required_fields = set(schema.get("required", []))

        inputs = []
        for name, prop in properties.items():
            inputs.append({
                "name": name,
                "type": cls._schema_type(prop),
                "description": prop.get("description", ""),
                "required": name in required_fields,
            })
        return inputs

    @staticmethod
    def _schema_type(prop: dict) -> str:
        """从 JSON Schema 属性中提取类型：兼容 pydantic 可选字段的 anyOf/oneOf"""
        if prop.get("type"):
            return prop["type"]
        for key in ("anyOf", "oneOf"):
            subs = prop.get(key)
            if isinstance(subs, list):
                for sub in subs:
                    t = sub.get("type")
                    if t and t != "null":
                        return t
                if subs:
                    return subs[0].get("type", "string")
        return "string"
