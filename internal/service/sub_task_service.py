#!/usr/bin/env python
"""子任务断点服务：保存/查询/标记完成/清理"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from internal.core.agent.entities.agent_entity import SubTaskSpec
from internal.model import SubTaskCheckpoint

from .base_service import BaseService

# 可恢复状态：断点续跑的前提
RESUMABLE_STATUSES = ("running", "stop", "timeout", "error")
COMPLETE_STATUS = "complete"


@dataclass
class SubTaskService(BaseService):
    db: AsyncSession

    async def save_checkpoint(
            self,
            *,
            app_id: UUID,
            conversation_id: UUID,
            message_id: UUID,
            position: int,
            query: str,
            spec: SubTaskSpec,
            status: str,
            messages: list,
            iteration_count: int,
            partial_answer: str,
            total_token_count: int = 0,
            total_price: float = 0.0,
            plan_id: UUID | None = None,
    ) -> None:
        """保存（或更新）指定位置的子任务断点。

        唯一索引 (message_id, position) 上的原子 upsert——并发运行不会产生重复行，
        消除了 get-then-create 竞态下 get_checkpoint 的 MultipleResultsFound 崩溃。
        plan_id 记录计划代际（replan/regenerate 重拆前旧断点会被清空，防错误复用）。
        """
        values = dict(
            app_id=app_id, conversation_id=conversation_id, message_id=message_id,
            position=position, query=query,
            title=spec.title, role_prompt=spec.role_prompt, expect_output=spec.expect_output,
            required_tools=spec.required_tools, status=status, messages=messages,
            iteration_count=iteration_count, partial_answer=partial_answer,
            total_token_count=total_token_count, total_price=total_price,
            plan_id=plan_id,
            created_by=conversation_id, updated_by=conversation_id,
            updated_at=datetime.now(),
        )
        stmt = insert(SubTaskCheckpoint).values(**values).on_conflict_do_update(
            index_elements=["message_id", "position"],
            # 更新集：除定位键/主键/创建时间外的全部字段（upsert 更新也刷新 updated_at）
            set_={k: v for k, v in values.items() if k not in ("message_id", "position", "id", "created_at")},
        )
        await self.db.execute(stmt)
        await self.db.commit()  # 独立事务边界

    async def get_checkpoint(self, message_id: UUID, position: int) -> SubTaskCheckpoint | None:
        stmt = select(SubTaskCheckpoint).where(
            SubTaskCheckpoint.message_id == message_id,
            SubTaskCheckpoint.position == position,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_resumable_checkpoints(self, message_id: UUID) -> list[SubTaskCheckpoint]:
        stmt = select(SubTaskCheckpoint).where(
            SubTaskCheckpoint.message_id == message_id,
            SubTaskCheckpoint.status.in_(RESUMABLE_STATUSES),
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def has_resumable_checkpoints(self, message_id: UUID) -> bool:
        # EXISTS 风格查询——只取一行的 id，不物化整行，避免 N+1 全量 SELECT
        stmt = (
            select(SubTaskCheckpoint.id)
            .where(
                SubTaskCheckpoint.message_id == message_id,
                SubTaskCheckpoint.status.in_(RESUMABLE_STATUSES),
            )
            .limit(1)
        )
        return (await self.db.execute(stmt)).first() is not None

    async def mark_complete(
            self,
            *,
            message_id: UUID,
            position: int,
            answer: str,
            total_token_count: int,
            total_price: float,
    ) -> None:
        """子任务成功完成：写入最终答案缓存并标记 complete"""
        record = await self.get_checkpoint(message_id, position)
        if record is None:
            return
        await self.update(
            record,
            status=COMPLETE_STATUS, partial_answer=answer,
            total_token_count=total_token_count, total_price=total_price,
            updated_by=message_id,
        )

    async def clear_checkpoints(self, message_id: UUID | None = None, conversation_id: UUID | None = None) -> None:
        """删除断点（会话级或消息级级联清理）。

        断点按 message_id 定位，默认按会话清理：给定 conversation_id 时清空该会话下
        全部消息的断点；给定 message_id 时仅清理该消息的断点。
        """
        stmt = select(SubTaskCheckpoint)
        if message_id is not None:
            stmt = stmt.where(SubTaskCheckpoint.message_id == message_id)
        elif conversation_id is not None:
            stmt = stmt.where(SubTaskCheckpoint.conversation_id == conversation_id)
        records = (await self.db.execute(stmt)).scalars().all()
        for record in records:
            await self.db.delete(record)
        await self.db.commit()  # 独立事务边界
