"""ChoiceService.submit async 化测试——校验任务归属后写入 Redis 选择队列"""
import uuid
from unittest.mock import MagicMock

import pytest

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import ForbiddenException
from internal.service.choice_service import ChoiceService


def _make_service(monkeypatch, belong_value) -> tuple[ChoiceService, MagicMock]:
    fake_redis = MagicMock()
    fake_redis.get.return_value = belong_value
    svc = ChoiceService(redis_client=fake_redis)
    monkeypatch.setattr(AgentQueueManager, "submit_choice", MagicMock(return_value=True))
    return svc, fake_redis


@pytest.mark.asyncio
async def test_submit_writes_choice(monkeypatch):
    account_id = uuid.uuid4()
    belong_value = f"account-{account_id}".encode()
    svc, fake_redis = _make_service(monkeypatch, belong_value)
    await svc.submit(uuid.uuid4(), "RBAC", False, MagicMock(id=account_id), InvokeFrom.DEBUGGER)
    AgentQueueManager.submit_choice.assert_called_once()
    call = AgentQueueManager.submit_choice.call_args
    assert call.kwargs["choice"] == "RBAC"
    assert call.kwargs["skip"] is False


@pytest.mark.asyncio
async def test_submit_forwards_plan_fields(monkeypatch):
    """plan 模式 submit 转发 action/keep_orders/custom（真实链路确认点 1 依赖这三项）"""
    account_id = uuid.uuid4()
    belong_value = f"account-{account_id}".encode()
    svc, _ = _make_service(monkeypatch, belong_value)
    await svc.submit(
        uuid.uuid4(), choice="", skip=False, account=MagicMock(id=account_id),
        invoke_from=InvokeFrom.DEBUGGER, event_id="evt-1",
        action="confirm", keep_orders=[1, 3], custom="补充要求",
    )
    AgentQueueManager.submit_choice.assert_called_once()
    call = AgentQueueManager.submit_choice.call_args
    assert call.kwargs["action"] == "confirm"
    assert call.kwargs["keep_orders"] == [1, 3]
    assert call.kwargs["custom"] == "补充要求"
    assert call.kwargs["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_submit_plan_empty_custom_normalized_to_none(monkeypatch):
    """确认执行（custom 空串）转发时归一化为 None，submit_choice 据此省略 payload 字段"""
    account_id = uuid.uuid4()
    belong_value = f"account-{account_id}".encode()
    svc, _ = _make_service(monkeypatch, belong_value)
    await svc.submit(
        uuid.uuid4(), choice="", skip=False, account=MagicMock(id=account_id),
        invoke_from=InvokeFrom.DEBUGGER, event_id="evt-1",
        action="confirm", keep_orders=[1, 3], custom="",
    )
    call = AgentQueueManager.submit_choice.call_args
    assert call.kwargs["action"] == "confirm"
    assert call.kwargs["keep_orders"] == [1, 3]
    assert call.kwargs["custom"] is None


@pytest.mark.asyncio
async def test_submit_forbidden_when_task_missing(monkeypatch):
    svc, _ = _make_service(monkeypatch, None)  # belong key 不存在
    with pytest.raises(ForbiddenException):
        await svc.submit(uuid.uuid4(), "RBAC", False, MagicMock(id=uuid.uuid4()), InvokeFrom.DEBUGGER)


@pytest.mark.asyncio
async def test_submit_forbidden_when_not_owner(monkeypatch):
    svc, _ = _make_service(monkeypatch, b"account-other-user-id")
    with pytest.raises(ForbiddenException):
        await svc.submit(uuid.uuid4(), "RBAC", False, MagicMock(id=uuid.uuid4()), InvokeFrom.DEBUGGER)
