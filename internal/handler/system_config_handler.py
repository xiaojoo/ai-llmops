#!/usr/bin/env python
"""
系统配置处理器：/settings 页面配置的读取与保存。
"""
from dataclasses import dataclass

from fastapi import Request

from internal.server.deps import CurrentUser
from internal.service import SystemConfigService
from internal.service.system_config_service import SENSITIVE_KEYS
from package.response import success_json, success_message_json


@dataclass
class SystemConfigHandler:
    """系统配置处理器"""
    system_config_service: SystemConfigService

    async def get_system_config(self, user: CurrentUser) -> None:
        """读取全部系统配置（敏感项脱敏：有值显示已设置，不返回明文）"""
        config_map = await self.system_config_service.get_config_map()
        result = {}
        for key, value in config_map.items():
            if key in SENSITIVE_KEYS:
                result[key] = "********" if value else ""
            else:
                result[key] = value
        return success_json(result)

    async def save_system_config(self, user: CurrentUser, request: Request) -> None:
        """批量保存系统配置（JSON: {config_key: value}；空字符串清空该项回退环境变量）"""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or len(body) == 0:
            return success_json({"message": "无配置可保存"})
        configs = {}
        for key, value in body.items():
            if not isinstance(key, str) or not key.strip():
                continue
            configs[key.strip()] = "" if value is None else str(value)
        await self.system_config_service.save_configs(configs, account_id=user.id)
        return success_message_json("配置保存成功")
