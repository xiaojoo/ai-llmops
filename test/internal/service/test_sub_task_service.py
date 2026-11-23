import uuid

import pytest

from internal.core.agent.entities.agent_entity import SubTaskSpec
from internal.service.sub_task_service import SubTaskService


def _make_spec(order: int) -> SubTaskSpec:
    return SubTaskSpec(order=order, title="子任务", role_prompt="角色", expect_output="输出")


@pytest.mark.asyncio
async def test_save_and_get_checkpoint(db_session):
    service = SubTaskService(db=db_session)
    conv_id = uuid.uuid4()
    app_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    spec = _make_spec(1)

    await service.save_checkpoint(
        app_id=app_id, conversation_id=conv_id, message_id=msg_id, position=1,
        query="写报告", spec=spec, status="stop",
        messages=[{"type": "human", "data": {"content": "x"}}], iteration_count=2,
        partial_answer="部分内容",
    )
    ck = await service.get_checkpoint(msg_id, 1)
    assert ck is not None
    assert ck.status == "stop"
    assert ck.partial_answer == "部分内容"
    assert ck.iteration_count == 2

    # 再次保存应更新而非新增（UPDATE 后 expire 身份映射，强制重读）
    await service.save_checkpoint(
        app_id=app_id, conversation_id=conv_id, message_id=msg_id, position=1,
        query="写报告", spec=spec, status="running",
        messages=[], iteration_count=3, partial_answer="更多",
    )
    db_session.expire_all()
    ck2 = await service.get_checkpoint(msg_id, 1)
    assert ck2.iteration_count == 3


@pytest.mark.asyncio
async def test_resumable_and_complete(db_session):
    service = SubTaskService(db=db_session)
    conv_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    spec = _make_spec(1)
    await service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=msg_id,
        position=1, query="写报告", spec=spec, status="timeout",
        messages=[], iteration_count=1, partial_answer="",
    )
    assert await service.has_resumable_checkpoints(msg_id) is True
    assert await service.has_resumable_checkpoints(uuid.uuid4()) is False

    await service.mark_complete(message_id=msg_id, position=1, answer="最终结果",
                                total_token_count=10, total_price=0.01)
    assert await service.get_resumable_checkpoints(msg_id) == []
    ck = await service.get_checkpoint(msg_id, 1)
    assert ck.status == "complete"
    assert ck.partial_answer == "最终结果"


@pytest.mark.asyncio
async def test_clear_checkpoints(db_session):
    service = SubTaskService(db=db_session)
    conv_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    await service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=msg_id,
        position=1, query="q", spec=_make_spec(1), status="stop",
        messages=[], iteration_count=0, partial_answer="",
    )
    # 按消息清理：该消息的断点被清除
    await service.clear_checkpoints(message_id=msg_id)
    assert await service.get_checkpoint(msg_id, 1) is None
    # 按会话清理：会话下全部消息断点被清除
    await service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=uuid.uuid4(),
        position=2, query="q2", spec=_make_spec(2), status="stop",
        messages=[], iteration_count=0, partial_answer="",
    )
    await service.clear_checkpoints(conversation_id=conv_id)
    assert await service.has_resumable_checkpoints(msg_id) is False
