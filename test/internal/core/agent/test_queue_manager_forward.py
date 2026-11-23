import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _make_manager(monkeypatch) -> AgentQueueManager:
    fake_redis = MagicMock()
    # sync_redis_client 为模块级单例；代码经 _sync_redis() 活引用 internal.extensions.redis 模块属性
    monkeypatch.setattr("internal.extensions.redis.sync_redis_client", fake_redis)
    return AgentQueueManager(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP)


def test_forward_puts_event_without_stop_sentinel(monkeypatch):
    qm = _make_manager(monkeypatch)
    task_id = uuid.uuid4()
    event = AgentThought(
        id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END, answer="x",
        model_name="test-model",  # 非空避免 forward 内部 model_copy 换对象，保持 `got is event` 同一性
    )
    qm.forward(task_id, event)
    q = qm.queue(task_id)
    got = q.get(timeout=1)
    assert got is event  # 事件本身
    assert q.empty()  # 没有 None（stop 哨兵）


def test_publish_terminal_does_add_stop_sentinel(monkeypatch):
    """对照测试：publish 终态事件会 stop_listen（放 None），forward 必须没有这个行为"""
    qm = _make_manager(monkeypatch)
    task_id = uuid.uuid4()
    qm.publish(task_id, AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END))
    q = qm.queue(task_id)
    items = []
    while not q.empty():
        try:
            items.append(q.get(timeout=1))
        except Exception:
            break
    assert None in items
