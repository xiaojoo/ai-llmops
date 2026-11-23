#!/usr/bin/env python
"""记忆工具集测试：search/write/update/forget_memory

MemoryTools 经 container 工厂构造；get_tools 为 async（await）；
工具 invoke 内部经 worker_run 独立 engine 真实落库（测试库，随机 uuid 隔离，
断言用 db_session 查询已提交行；不清理以避免跨连接回滚失效）。
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from internal.container import create_memory_tools
from internal.model import EpisodicMemory, ProceduralMemory


class TestMemoryTools:
    @pytest.mark.asyncio
    async def test_get_tools_returns_four_tools(self, db_session):
        tools_service = create_memory_tools(db_session)
        tools = await tools_service.get_tools(app_id=uuid4(), user_id=uuid4())
        names = {tool.name for tool in tools}
        assert names == {"search_memory", "write_memory", "update_memory", "forget_memory"}

    @pytest.mark.asyncio
    async def test_write_tool_persists_procedural(self, db_session):
        tools_service = create_memory_tools(db_session)
        app_id, user_id = uuid4(), uuid4()
        tools = await tools_service.get_tools(app_id=app_id, user_id=user_id)
        write_tool = next(t for t in tools if t.name == "write_memory")

        result = write_tool.invoke({
            "content": "用户要求回答时先给结论",
            "memory_type": "procedural",
        })

        assert "成功" in result
        stmt = select(ProceduralMemory).where(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        )
        records = (await db_session.execute(stmt)).scalars().all()
        assert len(records) == 1
        assert records[0].content == "用户要求回答时先给结论"

    @pytest.mark.asyncio
    async def test_update_memory_same_content_keeps_rule(self, db_session):
        """update_memory 幂等命中（内容未变）不应软删唯一有效规则"""
        tools_service = create_memory_tools(db_session)
        app_id, user_id = uuid4(), uuid4()
        tools = await tools_service.get_tools(app_id=app_id, user_id=user_id)
        write_tool = next(t for t in tools if t.name == "write_memory")
        update_tool = next(t for t in tools if t.name == "update_memory")

        write_tool.invoke({
            "content": "回答用户时先给结论",
            "memory_type": "procedural",
        })
        stmt = select(ProceduralMemory).where(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        )
        record = (await db_session.execute(stmt)).scalars().one()

        result = update_tool.invoke({
            "memory_id": str(record.id),
            "content": "回答用户时先给结论",  # 相同内容 → 幂等命中
        })

        assert "已更新" in result
        await db_session.refresh(record)
        assert record.is_deleted is False, "幂等命中不应软删唯一有效规则"
        instructions = await tools_service.procedural_memory_service.get_instructions(app_id, user_id)
        assert "回答用户时先给结论" in instructions, "规则应仍可被检索到"

    @pytest.mark.asyncio
    async def test_forget_memory_episodic_soft_deletes(self, db_session):
        """forget_memory episodic 分支应软删（is_deleted=True）而非物理删除"""
        tools_service = create_memory_tools(db_session)
        app_id, user_id = uuid4(), uuid4()
        tools = await tools_service.get_tools(app_id=app_id, user_id=user_id)
        write_tool = next(t for t in tools if t.name == "write_memory")
        forget_tool = next(t for t in tools if t.name == "forget_memory")

        # 先经 write 工具真实落库一条 episodic，再取 id 删除（独立连接可见已提交行）
        write_tool.invoke({
            "content": "用户正在准备搬家到北京",
            "memory_type": "episodic",
        })
        stmt = select(EpisodicMemory).where(
            EpisodicMemory.app_id == app_id,
            EpisodicMemory.user_id == user_id,
        )
        episode = (await db_session.execute(stmt)).scalars().one()

        result = forget_tool.invoke({
            "memory_id": str(episode.id),
            "memory_type": "episodic",
        })

        assert "已删除" in result
        await db_session.refresh(episode)
        assert episode.is_deleted is True, "episodic 应软删而非物理删除"
        remaining = (await db_session.execute(stmt)).scalars().all()
        assert len(remaining) == 1, "软删应保留记录（审计）"
