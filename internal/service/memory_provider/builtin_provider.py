#!/usr/bin/env python
"""内置记忆提供者：现有语义/情景/程序记忆的薄封装，行为与现状完全一致"""
import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

from package.database import build_engine, worker_run
from internal.service.episodic_memory_service import EpisodicMemoryService
from internal.service.procedural_memory_service import ProceduralMemoryService
from internal.service.user_memory_service import UserMemoryService
from internal.core.tools.memory_tools import MemoryTools
from sqlalchemy.ext.asyncio import AsyncSession

from .base import MemoryProvider, MemoryReadContext

logger = logging.getLogger(__name__)


@dataclass
class BuiltinMemoryProvider(MemoryProvider):
    """内置记忆系统：委托现有三个记忆 service 与 MemoryTools，行为零变化"""
    user_memory_service: UserMemoryService
    episodic_memory_service: EpisodicMemoryService
    procedural_memory_service: ProceduralMemoryService
    memory_tools: MemoryTools

    async def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        return self.user_memory_service._render_current_facts(
            await self.user_memory_service.get_current_facts(app_id, user_id, min_trust=0.3)
        )

    async def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        ctx = MemoryReadContext()
        try:
            episodes = await self.episodic_memory_service.search_episodes(app_id, user_id, query, top_k=3)
            ctx.episodic_memory = "\n".join(f"- {e.content}" for e in episodes)
        except Exception:
            logger.exception("情景记忆召回失败")
        ctx.procedural_instructions = await self.procedural_memory_service.get_instructions(app_id, user_id)
        return ctx

    async def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        return await self.memory_tools.get_tools(
            app_id=app_id,
            user_id=user_id,
        )

    async def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        """写侧管道：worker_run 在独立线程中执行（独立 loop + loop 内 AsyncSession）。

        调用方处于 async 上下文时 worker_run 的运行中-loop 守卫会抛 RuntimeError。
        用 asyncio.to_thread 将 worker_run 移到线程池——线程内无运行中 loop，守卫放行，
        asyncio.run 自建独立 loop。
        """
        # 用户特征抽取
        async def _extract_user_facts_coro(session: AsyncSession) -> None:
            from internal.container import (
                create_user_memory_service,
            )
            service = create_user_memory_service(session)
            try:
                await service.expire_overdue_facts(app_id, user_id)
                current_facts = await service.get_current_facts(app_id, user_id)
                current_profile = service._render_current_facts(current_facts)
                # LLM 调用前先提交读事务——抽取调用可能耗时 60s+（代理/限流重试），
                # 事务空闲超 idle_in_transaction_session_timeout 会被 PG 终止，连接随之关闭，
                # 后续 commit 抛 "connection is closed"。
                await session.commit()
                extracted = await service.extract_user_facts(query, answer, current_profile)
                if extracted:
                    await service.upsert_facts(app_id, user_id, extracted)
            except Exception:
                logger.exception("用户特征抽取写入失败，app_id=%s, user_id=%s", app_id, user_id)

        # 情景记忆抽取
        async def _extract_episodes_coro(session: AsyncSession) -> None:
            from internal.container import (
                create_episodic_memory_service,
            )
            service = create_episodic_memory_service(session)
            try:
                existing = await service.get_recent_text(app_id, user_id)
                # LLM 调用前先提交读事务（见 _extract_user_facts_coro 注释）
                await session.commit()
                episodes = await service.extract_episodes(query, answer, existing)
                if episodes:
                    await service.upsert_episodes(app_id, user_id, episodes)
            except Exception:
                logger.exception("情景记忆抽取写入失败，app_id=%s, user_id=%s", app_id, user_id)

        # to_thread 内无运行中 loop，worker_run 守卫放行
        # 线程内 asyncio.run 新 loop，必须 engine_factory=build_engine——全局 engine 的
        # asyncpg 连接绑定主事件循环，跨 loop 复用会抛 InterfaceError 并把连接毒化回池
        # （表现为后续请求 "connection is closed" / 连接被终止）。
        await asyncio.to_thread(worker_run, _extract_user_facts_coro, commit_on_success=True, engine_factory=build_engine)
        await asyncio.to_thread(worker_run, _extract_episodes_coro, commit_on_success=True, engine_factory=build_engine)
