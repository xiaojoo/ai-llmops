#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : memory_tools.py

记忆工具集：把记忆的读写检索暴露给 Agent（MemGPT/LangMem 模式）。
- search_memory：检索情景记忆（向量召回）
- write_memory：写入情景经历（episodic）或行为规则（procedural）
- update_memory：改写程序记忆（规则/人设）
- forget_memory：删除记忆
"""
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from internal.service.episodic_memory_service import EpisodicMemoryService
from internal.service.procedural_memory_service import ProceduralMemoryService
from internal.service.user_memory_service import UserMemoryService

logger = logging.getLogger(__name__)


class SearchMemoryInput(BaseModel):
    query: str = Field(description="检索 query，与当前对话主题相关")
    memory_type: str = Field(default="episodic", description="记忆类型：episodic(经历) / procedural(规则)")


class WriteMemoryInput(BaseModel):
    content: str = Field(description="要写入的记忆内容")
    memory_type: str = Field(default="episodic", description="记忆类型：episodic(经历) / procedural(规则)")


class UpdateMemoryInput(BaseModel):
    memory_id: str = Field(description="要改写的程序记忆 id")
    content: str = Field(description="改写后的规则内容")


class ForgetMemoryInput(BaseModel):
    memory_id: str = Field(description="要删除的记忆 id")
    memory_type: str = Field(default="procedural", description="记忆类型：episodic / procedural")


@dataclass
class MemoryTools:
    """记忆工具集构建器"""
    db: AsyncSession
    user_memory_service: UserMemoryService
    episodic_memory_service: EpisodicMemoryService
    procedural_memory_service: ProceduralMemoryService

    async def get_tools(
            self,
            *,
            app_id: UUID,
            user_id: UUID,
    ) -> list[BaseTool]:
        """构建四个记忆工具，闭包绑定 app_id/user_id 实现命名空间隔离。

        工具内部调用经 worker_run 桥接（同步工具内无法直接 await）。
        """
        from package.database import build_engine, worker_run

        procedural_memory_service = self.procedural_memory_service
        episodic_memory_service = self.episodic_memory_service

        def _run_with_engine(coro_factory):
            """工具在 Agent 图线程（子线程）里被调用：asyncio.run 新 loop + 全局 engine
            会跨 loop 复用 asyncpg 连接报 InterfaceError → 每调用独立 engine（同 loop 创建/dispose）。
            async 上下文（测试/事件循环内同步 invoke）经 run_sync_bridge 丢新线程执行，
            否则 worker_run 的运行中-loop 守卫拒绝。"""
            from package.database import run_sync_bridge

            return run_sync_bridge(lambda: worker_run(coro_factory, engine_factory=build_engine))

        @tool("search_memory", args_schema=SearchMemoryInput)
        def search_memory(query: str, memory_type: str = "episodic") -> str:
            """检索记忆：episodic 返回情景经历（向量召回），procedural 返回行为规则"""
            async def _coro(session: AsyncSession) -> str:
                from internal.container import create_procedural_memory_service, create_episodic_memory_service
                if memory_type == "procedural":
                    svc = create_procedural_memory_service(session)
                    return await svc.get_instructions(app_id, user_id)
                eps_svc = create_episodic_memory_service(session)
                episodes = await eps_svc.search_episodes(app_id, user_id, query, top_k=5)
                if not episodes:
                    return "没有检索到相关的情景记忆"
                return "\n".join(f"- {e.content}" for e in episodes)

            return _run_with_engine(_coro)

        @tool("write_memory", args_schema=WriteMemoryInput)
        def write_memory(content: str, memory_type: str = "episodic") -> str:
            """写入记忆：episodic 写入情景经历，procedural 写入/改写行为规则"""
            async def _coro(session: AsyncSession) -> str:
                from internal.container import create_procedural_memory_service, create_episodic_memory_service
                if memory_type == "procedural":
                    svc = create_procedural_memory_service(session)
                    await svc.upsert_instruction(app_id, user_id, content, source="agent_tool")
                    return "行为规则写入成功"
                eps_svc = create_episodic_memory_service(session)
                await eps_svc.write_episode(
                    app_id=app_id, user_id=user_id,
                    content=content, importance=0.6, source="agent_tool",
                )
                return "情景记忆已写入"

            return _run_with_engine(_coro)

        @tool("update_memory", args_schema=UpdateMemoryInput)
        def update_memory(memory_id: str, content: str) -> str:
            """改写程序记忆（行为规则/人设），新内容生效并版本+1"""
            async def _coro(session: AsyncSession) -> str:
                from internal.container import create_procedural_memory_service
                svc = create_procedural_memory_service(session)
                record = await svc.upsert_instruction(
                    app_id, user_id, content, source="agent_update",
                )
                # 幂等命中（内容未变）：不删除旧规则，避免静默删除唯一有效规则
                if str(record.id) != memory_id:
                    try:
                        await svc.soft_delete(app_id, user_id, UUID(memory_id))
                    except Exception:
                        logger.warning("update_memory 旧规则删除失败：%s", memory_id)
                return "行为规则已更新"

            return _run_with_engine(_coro)

        @tool("forget_memory", args_schema=ForgetMemoryInput)
        def forget_memory(memory_id: str, memory_type: str = "procedural") -> str:
            """删除记忆（软删除，保留审计）"""
            async def _coro(session: AsyncSession) -> str:
                from internal.container import create_procedural_memory_service
                from internal.model import EpisodicMemory
                if memory_type == "procedural":
                    svc = create_procedural_memory_service(session)
                    await svc.soft_delete(app_id, user_id, UUID(memory_id))
                    return "程序记忆已删除"
                # episodic：软删除（保留审计），Weaviate 向量清理留待后续
                record = await session.get(EpisodicMemory, UUID(memory_id))
                if record and record.app_id == app_id and record.user_id == user_id:
                    from internal.service.base_service import BaseService
                    bs = BaseService(db=session)
                    await bs.update(record, is_deleted=True)
                return "情景记忆已删除"

            return _run_with_engine(_coro)

        return [search_memory, write_memory, update_memory, forget_memory]
