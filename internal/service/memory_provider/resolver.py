#!/usr/bin/env python
"""记忆系统 Provider 解析器：应用配置 > 系统默认 > builtin"""
import logging
from dataclasses import dataclass

from internal.service.system_config_service import SystemConfigService

from .base import MemoryProvider
from .builtin_provider import BuiltinMemoryProvider
from .tencent_provider import TencentMemoryProvider

logger = logging.getLogger(__name__)

BUILTIN = "builtin"
TENCENT = "tencent"
SYSTEM_MEMORY_PROVIDER_KEY = "MEMORY_PROVIDER"


@dataclass
class MemoryProviderResolver:
    system_config_service: SystemConfigService
    builtin_provider: BuiltinMemoryProvider
    tencent_provider: TencentMemoryProvider

    async def resolve(self, app_config: dict) -> MemoryProvider:
        # 1) 应用覆盖：long_term_memory.provider（default/缺失则跟随系统）
        long_term_memory = app_config.get("long_term_memory") or {}
        provider = long_term_memory.get("provider")
        if provider == BUILTIN:
            return self.builtin_provider
        if provider == TENCENT:
            return self.tencent_provider
        # 2) 系统默认：MEMORY_PROVIDER（DB > 环境变量 > 空）
        system_provider = await self.system_config_service.get_config(SYSTEM_MEMORY_PROVIDER_KEY)
        if system_provider == TENCENT:
            return self.tencent_provider
        if system_provider and system_provider != BUILTIN:
            logger.warning("未知 MEMORY_PROVIDER=%s，回退内置记忆系统", system_provider)
        # 3) 缺省 builtin
        return self.builtin_provider
