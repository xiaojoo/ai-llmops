#!/usr/bin/env python
"""RunService 测试：run 生命周期（start_run/finish_run/update_run_status）+ message.status 投影语义

- run 由 Runtime 驱动创建/终结，version 按同 message 已有 run 数自增（stop→resume 递增）；
- message.status 收窄为"该消息最新 run 状态的投影"（project_message_status），
  仅终态、且仅当 run 是最新时投影——旧 run 迟到终结不得覆盖新 run。
"""
import uuid
from datetime import datetime

import pytest

from internal.entity.conversation_entity import (
    InvokeFrom,
    MessageStatus,
    RunStatus,
    project_message_status,
)
from internal.model import AgentRun, Message
from internal.service.run_service import RunService


async def _make_message(db_session) -> Message:
    """构造最小 Message 行（仅填非空归属列；其余列走 server_default / ORM 默认）"""
    account_id = uuid.uuid4()
    msg = Message(
        app_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        created_by=account_id,
        updated_by=account_id,
        invoke_from=InvokeFrom.WEB_APP,
        query="写一份市场调研报告",
    )
    db_session.add(msg)
    await db_session.flush()
    return msg


@pytest.mark.asyncio
async def test_start_run_writes_row_and_increments_version(db_session):
    """start_run：真实 db_session 落 running 行（version=1）；同 message 再开新 run → version=2"""
    svc = RunService(db=db_session)
    msg = await _make_message(db_session)
    account_id = uuid.uuid4()
    conv_id = msg.conversation_id
    app_id = msg.app_id

    run_id_1 = uuid.uuid4()
    run_1 = await svc.start_run(
        run_id=run_id_1, message_id=msg.id, conversation_id=conv_id,
        app_id=app_id, account_id=account_id, invoke_from=InvokeFrom.WEB_APP,
        agent_type="function_call",
    )
    assert run_1.id == run_id_1
    assert run_1.version == 1
    assert run_1.status == RunStatus.RUNNING.value
    assert run_1.message_id == msg.id
    assert run_1.conversation_id == conv_id
    assert run_1.app_id == app_id
    assert run_1.created_by == account_id
    assert run_1.invoke_from == InvokeFrom.WEB_APP.value
    assert run_1.agent_type == "function_call"
    assert run_1.parent_run_id is None
    assert run_1.resume_trigger is False
    assert run_1.started_at is not None

    # 再次对同 message start_run 另一 run_id（模拟 stop→resume 新 run）→ version 递增
    run_id_2 = uuid.uuid4()
    run_2 = await svc.start_run(
        run_id=run_id_2, message_id=msg.id, conversation_id=conv_id,
        app_id=app_id, account_id=account_id,
        invoke_from=InvokeFrom.DEBUGGER, agent_type="orchestrator",
        parent_run_id=run_id_1, resume_trigger=True,
    )
    assert run_2.version == 2
    assert run_2.status == RunStatus.RUNNING.value
    assert run_2.parent_run_id == run_id_1
    assert run_2.resume_trigger is True
    assert run_2.invoke_from == InvokeFrom.DEBUGGER.value
    assert run_2.agent_type == "orchestrator"

    # 真实读回：行确实落库（version 自增依赖 message 已有 run 计数，同事务可见）
    db_session.expire_all()
    stored = await db_session.get(AgentRun, run_id_1)
    assert stored is not None and stored.version == 1
    stored2 = await db_session.get(AgentRun, run_id_2)
    assert stored2 is not None and stored2.version == 2


@pytest.mark.asyncio
async def test_finish_run_projects_message_status_normal(db_session):
    """finish_run：run 置 succeeded + 统计字段；最新 run 终结把 message.status 投影为 normal"""
    svc = RunService(db=db_session)
    msg = await _make_message(db_session)
    account_id = uuid.uuid4()
    before = datetime.now()
    run = await svc.start_run(
        run_id=uuid.uuid4(), message_id=msg.id, conversation_id=msg.conversation_id,
        app_id=msg.app_id, account_id=account_id, invoke_from=InvokeFrom.WEB_APP,
        agent_type="function_call",
    )

    finished = await svc.finish_run(
        run.id, status=RunStatus.SUCCEEDED,
        total_token_count=1234, total_price=0.0123, latency=5.5,
    )
    assert finished is not None
    assert finished.status == RunStatus.SUCCEEDED.value
    assert finished.total_token_count == 1234
    assert finished.total_price == 0.0123
    assert finished.latency == 5.5
    assert finished.ended_at is not None
    assert finished.ended_at >= before

    # message.status 投影：succeeded → normal
    msg_id, run_id_snapshot = msg.id, run.id
    db_session.expire_all()
    projected = await db_session.get(Message, msg_id)
    assert projected.status == MessageStatus.NORMAL.value, \
        f"最新 run succeeded 应把 message.status 投影为 normal，实际: {projected.status}"

    # get_latest_run 能取到该 run
    latest = await svc.get_latest_run(msg_id)
    assert latest is not None and latest.id == run_id_snapshot


@pytest.mark.asyncio
async def test_finish_run_stale_run_does_not_override_newer_run(db_session):
    """旧 run 迟到终结不覆盖新 run：先 finish v2（succeeded），再 finish v1（failed），
    message.status 仍为 normal 而非 error（只投影最新 run）"""
    svc = RunService(db=db_session)
    msg = await _make_message(db_session)
    account_id = uuid.uuid4()
    run_v1 = await svc.start_run(
        run_id=uuid.uuid4(), message_id=msg.id, conversation_id=msg.conversation_id,
        app_id=msg.app_id, account_id=account_id, invoke_from=InvokeFrom.WEB_APP,
        agent_type="function_call",
    )
    run_v2 = await svc.start_run(
        run_id=uuid.uuid4(), message_id=msg.id, conversation_id=msg.conversation_id,
        app_id=msg.app_id, account_id=account_id, invoke_from=InvokeFrom.WEB_APP,
        agent_type="function_call", parent_run_id=run_v1.id, resume_trigger=True,
    )
    assert run_v1.version == 1 and run_v2.version == 2

    # v2（最新）先终结 succeeded → message.status = normal
    await svc.finish_run(run_v2.id, status=RunStatus.SUCCEEDED)
    # v1（旧 run）迟到终结 failed → 不得覆盖新 run 的投影
    await svc.finish_run(run_v1.id, status=RunStatus.FAILED, error="旧 run 超时迟到失败")

    msg_id, v1_id, v2_id = msg.id, run_v1.id, run_v2.id
    db_session.expire_all()
    projected = await db_session.get(Message, msg_id)
    assert projected.status == MessageStatus.NORMAL.value, \
        f"旧 run 迟到终结不得把 message.status 覆盖为 error，实际: {projected.status}"
    # run 行自身状态各自正确
    v1 = await db_session.get(AgentRun, v1_id)
    v2 = await db_session.get(AgentRun, v2_id)
    assert v1.status == RunStatus.FAILED.value and v1.error == "旧 run 超时迟到失败"
    assert v2.status == RunStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_update_run_status_running_to_awaiting_input(db_session):
    """update_run_status：非终结态流转 running → awaiting_input 可写（不改 message.status）"""
    svc = RunService(db=db_session)
    msg = await _make_message(db_session)
    run = await svc.start_run(
        run_id=uuid.uuid4(), message_id=msg.id, conversation_id=msg.conversation_id,
        app_id=msg.app_id, account_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
    )
    updated = await svc.update_run_status(run.id, RunStatus.AWAITING_INPUT)
    assert updated is not None
    assert updated.status == RunStatus.AWAITING_INPUT.value
    run_id_snapshot, msg_id = run.id, msg.id
    db_session.expire_all()
    stored = await db_session.get(AgentRun, run_id_snapshot)
    assert stored.status == RunStatus.AWAITING_INPUT.value
    # awaiting_input 非终态：message.status 保持初始值（未被投影）
    msg_row = await db_session.get(Message, msg_id)
    await db_session.refresh(msg_row)
    assert msg_row.status == "", \
        f"awaiting_input 非终态不应投影 message.status，实际: {msg_row.status}"


@pytest.mark.asyncio
async def test_list_runs_ascending_and_get_latest(db_session):
    """list_runs 按 version 升序；get_latest_run 取 version 最大"""
    svc = RunService(db=db_session)
    msg = await _make_message(db_session)
    account_id = uuid.uuid4()
    ids = []
    for _ in range(3):
        ids.append((await svc.start_run(
            run_id=uuid.uuid4(), message_id=msg.id, conversation_id=msg.conversation_id,
            app_id=msg.app_id, account_id=account_id, invoke_from=InvokeFrom.WEB_APP,
        )).id)

    runs = await svc.list_runs(msg.id)
    assert [r.id for r in runs] == ids  # 按创建顺序即 version 升序
    assert [r.version for r in runs] == [1, 2, 3]
    assert await svc.get_latest_run(msg.id) is not None
    latest = await svc.get_latest_run(msg.id)
    assert latest.id == ids[-1] and latest.version == 3
    # get_run 单查
    assert (await svc.get_run(ids[0])).id == ids[0]
    # is_latest_run
    assert await svc.is_latest_run(ids[-1], msg.id) is True
    assert await svc.is_latest_run(ids[0], msg.id) is False


def test_project_message_status_mapping():
    """project_message_status 纯函数映射（succeeded→normal / cancelled→stop / timed_out→timeout /
    failed→error；运行中/等待输入不投影 → None）"""
    assert project_message_status(RunStatus.SUCCEEDED) == MessageStatus.NORMAL
    assert project_message_status(RunStatus.CANCELLED) == MessageStatus.STOP
    assert project_message_status(RunStatus.TIMED_OUT) == MessageStatus.TIMEOUT
    assert project_message_status(RunStatus.FAILED) == MessageStatus.ERROR
    # 非终态：不投影（None）
    assert project_message_status(RunStatus.PENDING) is None
    assert project_message_status(RunStatus.RUNNING) is None
    assert project_message_status(RunStatus.AWAITING_INPUT) is None
