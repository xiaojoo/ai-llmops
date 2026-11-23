#!/usr/bin/env python
"""Agent 运行（run）服务：run 生命周期（创建/终结）+ message.status 投影

语义：message.status 收窄为"该消息最新 run 状态的投影"（project_message_status）。
run 由 Runtime（ChatRunner / 编排器执行）驱动创建与终结，终态时投影回 message.status，
列表查询语义不变（message.status 仍为既有四态，保证前端/历史过滤不破坏）。
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.conversation_entity import InvokeFrom, MessageStatus, RunStatus, project_message_status
from internal.model import AgentRun, Message

logger = logging.getLogger(__name__)


@dataclass
class RunService:
    db: AsyncSession

    # ===== run 生命周期 =====

    async def next_version(self, message_id: UUID) -> int:
        """该消息已有 run 数 + 1（version：同一 message 的第 N 次 run，resume 递增）"""
        count = (
            await self.db.execute(
                select(func.count(AgentRun.id)).where(AgentRun.message_id == message_id)
            )
        ).scalar() or 0
        return int(count) + 1

    async def start_run(
            self,
            *,
            run_id: UUID,
            message_id: UUID,
            conversation_id: UUID,
            app_id: UUID,
            account_id: UUID,
            invoke_from: InvokeFrom | str,
            agent_type: str = "",
            parent_run_id: UUID | None = None,
            resume_trigger: bool = False,
    ) -> AgentRun:
        """run 开始：写入 running 行（version 按 message 已有 run 数自增）"""
        version = await self.next_version(message_id)
        record = AgentRun(
            id=run_id,
            message_id=message_id,
            conversation_id=conversation_id,
            app_id=app_id,
            created_by=account_id,
            updated_by=account_id,
            invoke_from=invoke_from.value if isinstance(invoke_from, InvokeFrom) else invoke_from,
            agent_type=agent_type,
            parent_run_id=parent_run_id,
            resume_trigger=resume_trigger,
            version=version,
            status=RunStatus.RUNNING.value,
            started_at=datetime.now(),
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def finish_run(
            self,
            run_id: UUID,
            *,
            status: RunStatus,
            error: str = "",
            total_token_count: int = 0,
            total_price: float = 0.0,
            latency: float = 0.0,
            project_message: bool = True,
    ) -> AgentRun | None:
        """run 终结：更新终态 + 统计；可选投影 message.status（最新 run 视图）"""
        record = await self.db.get(AgentRun, run_id)
        if record is None:
            logger.warning("终结 run 失败：run 不存在 run_id=%s", run_id)
            return None
        record.status = status.value if isinstance(status, RunStatus) else str(status)
        record.error = error
        record.total_token_count = total_token_count
        record.total_price = total_price
        record.latency = latency
        record.ended_at = datetime.now()
        record.updated_by = record.created_by
        await self.db.commit()

        if project_message:
            await self.project_message_status_from_run(record)
        return record

    async def update_run_status(self, run_id: UUID, status: RunStatus, error: str = "") -> AgentRun | None:
        """非终结态流转（running → awaiting_input 等）"""
        record = await self.db.get(AgentRun, run_id)
        if record is None:
            return None
        record.status = status.value if isinstance(status, RunStatus) else str(status)
        record.error = error
        record.updated_by = record.created_by
        await self.db.commit()
        return record

    # ===== 查询 =====

    async def get_latest_run(self, message_id: UUID) -> AgentRun | None:
        """该消息的最新 run（version 最大；同 version 取最后更新）"""
        stmt = (
            select(AgentRun)
            .where(AgentRun.message_id == message_id)
            .order_by(AgentRun.version.desc(), AgentRun.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def get_run(self, run_id: UUID) -> AgentRun | None:
        return await self.db.get(AgentRun, run_id)

    async def list_runs(self, message_id: UUID) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.message_id == message_id)
            .order_by(AgentRun.version.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ===== message.status 投影 =====

    async def project_message_status_from_run(self, run: AgentRun) -> None:
        """把 run 终态投影回 message.status（仅终态投影；运行中/等待输入不动 message）。

        只在该 run 是该 message 最新 run 时投影——旧 run 的迟到终态不得覆盖新 run。
        """
        try:
            run_status = RunStatus(run.status)
        except ValueError:
            return
        message_status = project_message_status(run_status)
        if message_status is None:
            return
        latest = await self.get_latest_run(run.message_id)
        if latest is None or latest.id != run.id:
            return
        message = await self.db.get(Message, run.message_id)
        if message is None:
            return
        # 终态投影为权威：run 是状态机，message.status 只是最新 run 的视图
        message.status = message_status.value if isinstance(message_status, MessageStatus) else str(message_status)
        await self.db.commit()

    async def is_latest_run(self, run_id: UUID, message_id: UUID) -> bool:
        latest = await self.get_latest_run(message_id)
        return latest is not None and latest.id == run_id
