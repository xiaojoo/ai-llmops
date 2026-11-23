import json
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager


def _fake_redis(monkeypatch) -> MagicMock:
    fake_redis = MagicMock()
    # sync_redis_client 为模块级单例；代码经 _sync_redis() 活引用
    # internal.extensions.redis 模块属性 → monkeypatch 该模块属性（而非 agent_queue_manager 快照）
    monkeypatch.setattr("internal.extensions.redis.sync_redis_client", fake_redis)
    return fake_redis


def test_submit_choice_writes_json_to_redis(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = False
    task_id = uuid.uuid4()
    ok = AgentQueueManager.submit_choice(task_id, choice="RBAC")
    assert ok is True
    fake_redis.rpush.assert_called_once()
    payload = json.loads(fake_redis.rpush.call_args.args[1])
    assert payload == {"choice": "RBAC", "skip": False, "event_id": ""}


def test_submit_choice_includes_event_id(monkeypatch):
    """submit_choice 带 event_id 时 payload 必须携带 event_id（供 wait_for_choice 过滤）"""
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = False
    ok = AgentQueueManager.submit_choice(uuid.uuid4(), choice="RBAC", event_id="evt-1")
    assert ok is True
    payload = json.loads(fake_redis.rpush.call_args.args[1])
    assert payload == {"choice": "RBAC", "skip": False, "event_id": "evt-1"}


def test_submit_choice_duplicate_ignored(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = True
    fake_redis.llen.return_value = 1
    ok = AgentQueueManager.submit_choice(uuid.uuid4(), choice="RBAC")
    assert ok is False
    fake_redis.rpush.assert_not_called()


def test_wait_for_choice_returns_choice(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps({"choice": "ABAC", "skip": False}).encode())
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300)
    assert choice == "ABAC"
    assert skipped is False
    assert custom == ""


def test_wait_for_choice_custom(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"choice": "重新生成", "skip": False, "custom": "重点看方案B", "event_id": "e1"},
    ).encode())
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), event_id="e1")
    assert choice == "重新生成"
    assert custom == "重点看方案B"
    assert skipped is False


def test_wait_for_choice_timeout_returns_skip(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = None
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=0)
    assert choice is None
    assert skipped is True


def test_wait_for_choice_filters_mismatched_event_id(monkeypatch):
    """带 event_id 时：BLPOP 返回不匹配的残留载荷 → 丢弃继续等待，直到匹配载荷到达"""
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.side_effect = [
        ("key", json.dumps({"choice": "OLD", "skip": False, "event_id": "other-event"}).encode()),
        ("key", json.dumps({"choice": "NEW", "skip": False, "event_id": "evt-1"}).encode()),
    ]
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300, event_id="evt-1")
    assert choice == "NEW"
    assert skipped is False
    assert custom == ""


def test_wait_for_choice_skip_payload(monkeypatch):
    """用户显式"跳过"的载荷（choice 空 + skip: true）解析为跳过"""
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", b'{"choice": "", "skip": true}')
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300)
    assert choice == ""
    assert skipped is True
    assert custom == ""


def test_submit_choice_with_plan_payload(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = False
    ok = AgentQueueManager.submit_choice(
        uuid.uuid4(), action="confirm", keep_orders=[1, 3], custom="", event_id="e1",
    )
    assert ok is True
    payload = json.loads(fake_redis.rpush.call_args.args[1])
    assert payload["action"] == "confirm"
    assert payload["keep_orders"] == [1, 3]
    assert payload["custom"] == ""
    assert payload["event_id"] == "e1"


def test_wait_for_plan_choice_confirm(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"action": "confirm", "keep_orders": [1, 3], "custom": "", "skip": False, "event_id": "e1"},
    ).encode())
    action, keep, custom, skipped = AgentQueueManager.wait_for_plan_choice(uuid.uuid4(), event_id="e1")
    assert action == "confirm"
    assert keep == [1, 3]
    assert custom == ""
    assert skipped is False


def test_wait_for_plan_choice_replan(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"action": "replan", "keep_orders": [], "custom": "改用ABAC", "skip": False, "event_id": "e1"},
    ).encode())
    action, keep, custom, skipped = AgentQueueManager.wait_for_plan_choice(uuid.uuid4(), event_id="e1")
    assert action == "replan"
    assert keep == []
    assert custom == "改用ABAC"
    assert skipped is False


def test_wait_for_plan_choice_timeout(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = None
    action, keep, custom, skipped = AgentQueueManager.wait_for_plan_choice(uuid.uuid4(), timeout=1)
    assert skipped is True
    assert action == "confirm"  # 超时按确认处理，调用方据此全量执行
