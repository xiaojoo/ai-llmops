"""本地工具结果队列（Local Tool Runtime）测试：submit_tool_result / wait_for_tool_result。

验证：
- submit_tool_result 把 {tool_call_id, result, error} 写入 Redis 工具结果队列键
- 缺 tool_call_id / Redis 未就绪 → 返回 False
- wait_for_tool_result 按 tool_call_id 命中并返回 (result, error)
- 等待期间丢弃不匹配 tool_call_id 的残留载荷（等价 ask_user 的 event_id 过滤）
- 超时/异常按错误处理
"""
import json
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager


def _fake_redis(monkeypatch) -> MagicMock:
    fake_redis = MagicMock()
    monkeypatch.setattr("internal.extensions.redis.sync_redis_client", fake_redis)
    return fake_redis


def test_submit_tool_result_writes_payload(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    task_id = uuid.uuid4()
    ok = AgentQueueManager.submit_tool_result(task_id, "call_8f91", '{"content":"abc"}')
    assert ok is True
    fake_redis.rpush.assert_called_once()
    assert fake_redis.rpush.call_args.args[0] == AgentQueueManager.generate_tool_result_queue_key(task_id)
    payload = json.loads(fake_redis.rpush.call_args.args[1])
    assert payload == {"tool_call_id": "call_8f91", "result": '{"content":"abc"}', "error": ""}


def test_submit_tool_result_missing_tool_call_id(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    ok = AgentQueueManager.submit_tool_result(uuid.uuid4(), "", "x")
    assert ok is False
    fake_redis.rpush.assert_not_called()


def test_submit_tool_result_redis_unready(monkeypatch):
    monkeypatch.setattr("internal.extensions.redis.sync_redis_client", None)
    ok = AgentQueueManager.submit_tool_result(uuid.uuid4(), "call_1", "x")
    assert ok is False


def test_wait_for_tool_result_matches(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"tool_call_id": "call_1", "result": '{"content":"ok"}', "error": ""},
    ).encode())
    result, error = AgentQueueManager.wait_for_tool_result(uuid.uuid4(), "call_1", timeout=300)
    assert result == '{"content":"ok"}'
    assert error == ""


def test_wait_for_tool_result_error_reported(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"tool_call_id": "call_2", "result": "", "error": "读取失败"},
    ).encode())
    result, error = AgentQueueManager.wait_for_tool_result(uuid.uuid4(), "call_2", timeout=300)
    assert result == ""
    assert error == "读取失败"


def test_wait_for_tool_result_filters_mismatched_id(monkeypatch):
    """BLPOP 返回不匹配 tool_call_id 的残留载荷 → 丢弃继续等，直到命中匹配载荷"""
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.side_effect = [
        ("key", json.dumps({"tool_call_id": "other", "result": "old", "error": ""}).encode()),
        ("key", json.dumps({"tool_call_id": "call_9", "result": "new", "error": ""}).encode()),
    ]
    result, error = AgentQueueManager.wait_for_tool_result(uuid.uuid4(), "call_9", timeout=300)
    assert result == "new"
    assert error == ""


def test_wait_for_tool_result_timeout(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = None
    result, error = AgentQueueManager.wait_for_tool_result(uuid.uuid4(), "call_1", timeout=0)
    assert result == ""
    assert error == "本地工具执行超时"


def test_wait_for_tool_result_missing_id(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    result, error = AgentQueueManager.wait_for_tool_result(uuid.uuid4(), "", timeout=0)
    assert result == ""
    assert error == "缺失 tool_call_id"
