import uuid
from unittest.mock import MagicMock

from redis import Redis

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _manager(monkeypatch):
    client = MagicMock(spec=Redis)
    client.exists.return_value = 0
    client.get.return_value = None
    monkeypatch.setattr("internal.extensions.redis.sync_redis_client", client)
    return AgentQueueManager(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP), client


def test_publish_writes_redis_stream_and_terminal_stop_key(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    event = AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END)
    manager.publish(task_id, event)

    client.xadd.assert_called_once()
    key, payload = client.xadd.call_args.args
    assert key == manager.generate_event_stream_key(task_id)
    assert AgentThought.model_validate_json(payload["thought"]).id == event.id
    client.set.assert_any_call(manager.generate_queue_stop_key(task_id), 1, ex=1800)


def test_publish_failure_sets_listener_error_signal(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    client.xadd.side_effect = ConnectionError("down")
    manager.publish(task_id, AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_MESSAGE))
    client.set.assert_any_call(manager.generate_queue_error_key(task_id), "publish_failed", ex=1800)


def test_listen_returns_publish_error_signal(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    client.get.side_effect = [None, b"publish_failed"]
    events = list(manager.listen(task_id))
    assert len(events) == 1
    assert events[0].event == QueueEvent.ERROR
    client.xread.assert_not_called()


def test_forward_writes_stream_without_terminal_stop(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    manager.forward(task_id, AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END))
    client.xadd.assert_called_once()
    assert not any(call.args[0] == manager.generate_queue_stop_key(task_id) for call in client.set.call_args_list)


def test_listen_reads_events_from_redis_stream(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    event = AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END, answer="done")
    client.xread.return_value = [
        (manager.generate_event_stream_key(task_id), [(b"1-0", {b"thought": event.model_dump_json()})]),
    ]
    assert list(manager.listen(task_id)) == [event]
    client.set.assert_any_call(manager.generate_queue_cursor_key(task_id), b"1-0", ex=1800)


def test_listen_emits_error_after_repeated_redis_failures(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    client.xread.side_effect = ConnectionError("down")
    events = list(manager.listen(task_id))
    assert len(events) == 1
    assert events[0].event == QueueEvent.ERROR


def test_listen_resumes_after_saved_cursor(monkeypatch):
    manager, client = _manager(monkeypatch)
    task_id = uuid.uuid4()
    client.get.side_effect = [b"7-0", None]
    event = AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END)
    client.xread.return_value = [
        (manager.generate_event_stream_key(task_id), [(b"8-0", {b"thought": event.model_dump_json()})]),
    ]
    assert list(manager.listen(task_id)) == [event]
    assert client.xread.call_args.args[0] == {manager.generate_event_stream_key(task_id): "7-0"}
