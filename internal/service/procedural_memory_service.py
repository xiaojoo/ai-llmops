#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : procedural_memory_service.py
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model import ProceduralMemory

from .base_service import BaseService

logger = logging.getLogger(__name__)


@dataclass
class ProceduralMemoryService(BaseService):
    """程序记忆服务：Agent 行为规则/人设的读取与改写"""
    db: AsyncSession

    async def get_instructions(self, app_id: UUID, user_id: UUID) -> str:
        """获取当前有效的程序记忆（行为规则），渲染成文本供注入"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
            .order_by(ProceduralMemory.version.desc())
        )
        records = (await self.db.execute(stmt)).scalars().all()
        return "\n".join(f"- {r.content}" for r in records)

    async def upsert_instruction(self, app_id: UUID, user_id: UUID, content: str, source: str) -> ProceduralMemory:
        """写入/改写一条程序记忆（幂等：相同内容合并，不同内容新写一条并版本+1 由审计保留）"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.content == content,
                ProceduralMemory.is_deleted.is_(False),
            )
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing
        # 计算当前最大版本
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
            .order_by(ProceduralMemory.version.desc())
            .limit(1)
        )
        latest = (await self.db.execute(stmt)).scalar_one_or_none()
        version = (latest.version + 1) if latest else 1
        return await self.create(
            ProceduralMemory,
            app_id=app_id, user_id=user_id,
            content=content, source=source,
            trust_score=0.6, version=version,
        )

    async def soft_delete(self, app_id: UUID, user_id: UUID, memory_id: UUID) -> None:
        """删除一条程序记忆"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.id == memory_id,
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
        )
        record = (await self.db.execute(stmt)).scalar_one_or_none()
        if record:
            await self.update(record, is_deleted=True)

    async def get_instruction_records(self, app_id: UUID, user_id: UUID) -> list[ProceduralMemory]:
        """获取当前有效的程序记忆记录（调试/审计，按版本倒序）"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
            .order_by(ProceduralMemory.version.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()
