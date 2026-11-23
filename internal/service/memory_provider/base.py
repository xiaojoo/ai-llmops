#!/usr/bin/env python
"""记忆系统 Provider 抽象：MemoryProvider 接口 + MemoryReadContext"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass
class MemoryReadContext:
    """对话前注入 Agent 的记忆提示词块（情景记忆 + 程序记忆）"""
    episodic_memory: str = ""
    procedural_instructions: str = ""


class MemoryProvider(ABC):
    """记忆提供者：读侧（画像/情景/程序/工具）与写侧（对话后抽取）统一入口。

    四个方法均携带 app_config：内置实现忽略它；腾讯实现从中取 model_config 构建 LLM。
    """

    @abstractmethod
    async def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        """语义记忆画像文本（<用户画像> 块）"""

    @abstractmethod
    async def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        """对话前召回情景记忆与程序记忆"""

    @abstractmethod
    async def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        """Agent 可用的记忆工具列表（list[BaseTool]）"""

    @abstractmethod
    async def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        """对话结束后异步执行记忆写侧管道（实现内部自行起 worker_run）"""
