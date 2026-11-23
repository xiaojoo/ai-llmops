#!/usr/bin/env python
"""按 run 的持久事件日志（RunEventLog / RedisRunEventLog）判据。

换成 Redis Stream 要解决的是两个真机量到的问题：内存环形缓冲 500 帧上限导致长回答
断开再刷新丢头部（一次跑了 20964 个事件），以及进程内状态多 worker 不共享。
所以这里必须验：游标语义正确、超过 500 条不截断、AgentThought 能原样往返、
以及 Redis 不可用时确实退回内存而不是把聊天打断。
"""
import uuid

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.service.event_replay import (
    EventReplayBuffer,
    RedisRunEventLog,
    RunEventLog,
)


def _frame(seq: int, tag: str = "agent_message") -> str:
    return f"id: {seq}\nevent: {tag}\ndata: {{\"seq\": {seq}}}\n\n"


def _thought(run_id: str, seq: int) -> AgentThought:
    return AgentThought(
        id=uuid.uuid4(), task_id=uuid.UUID(run_id), event=QueueEvent.AGENT_MESSAGE,
        thought=f"第{seq}段中文内容", answer=f"ans{seq}", model_name="测试模型",
    )


@pytest.fixture(scope="module")
def redis_client():
    """真连一个 Redis；连不上就整组跳过并把原因打出来（不静默当通过）。"""
    from redis import Redis

    from internal.config.settings import get_settings

    s = get_settings()
    client = Redis(
        host=s.redis_host, port=s.redis_port, username=s.redis_username or None,
        password=s.redis_password or None, db=s.redis_db, decode_responses=False,
        socket_connect_timeout=2, socket_timeout=2,
    )
    try:
        client.ping()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Redis 不可达，Redis 后端判据未执行：{type(e).__name__}: {e}")
    yield client
    client.close()


@pytest.fixture
def log(redis_client):
    """真 Redis 后端 + 唯一 run_id，用完删键。"""
    run_id = str(uuid.uuid4())
    backend = RedisRunEventLog(client_factory=lambda: redis_client)
    yield backend, run_id
    redis_client.delete(f"gen_task:events:{run_id}", f"gen_task:evtctx:{run_id}")


# ---------- Redis 后端：游标与容量 ----------

def _seq_of(frame: str) -> str:
    """从帧里取出 data.seq，用来断言顺序而不是只看条数。"""
    return frame.split('"seq": ')[1].split("}")[0]


def test_cursor_returns_only_unseen_frames(log):
    backend, run_id = log
    for seq in (1, 2, 3, 4):
        assert backend.record(run_id, seq, _frame(seq)) is True

    assert [_seq_of(f) for f in backend.history_after(run_id, 0)] == ["1", "2", "3", "4"]
    assert [_seq_of(f) for f in backend.history_after(run_id, 2)] == ["3", "4"], \
        "游标之后应只剩 3、4"
    assert backend.history_after(run_id, 4) == [], "游标到末尾不该再吐帧"
    assert backend.last_seq(run_id) == 4


def test_no_500_frame_cap(log):
    """这条就是换 Redis 的理由：内存缓冲 500 帧会把头部丢掉。"""
    backend, run_id = log
    total = 620
    for seq in range(1, total + 1):
        assert backend.record(run_id, seq, _frame(seq)) is True

    frames = backend.history_after(run_id, 0)
    assert len(frames) == total, (
        f"应完整保留 {total} 帧，实际 {len(frames)} 帧——说明还在走 500 上限的内存缓冲"
    )
    assert _seq_of(frames[0]) == "1", "第一帧应是 seq=1，头部没被截掉"
    assert _seq_of(frames[-1]) == str(total)


def test_thought_round_trips_unchanged(log):
    """续传侧落库靠的就是这个对象：中文/UUID/枚举/model_name 必须原样回来。"""
    backend, run_id = log
    original = _thought(run_id, 7)
    backend.record(run_id, 7, _frame(7), original)
    backend.record(run_id, 8, _frame(8))  # 无对象的帧要被跳过而不是报错

    got = backend.history_thoughts_after(run_id, 0)
    assert len(got) == 1, f"只登记了 1 个对象，实际 {len(got)}"
    assert got[0].thought == original.thought
    assert got[0].answer == original.answer
    assert got[0].id == original.id
    assert got[0].event is QueueEvent.AGENT_MESSAGE
    assert got[0].model_name == "测试模型"


def test_context_round_trip_and_clear(log, redis_client):
    backend, run_id = log
    backend.set_run_context(run_id, "conv-9", "msg-9")
    assert backend.get_run_context(run_id) == {"conversation_id": "conv-9", "message_id": "msg-9"}
    backend.record(run_id, 1, _frame(1))
    backend.clear(run_id)
    assert backend.history_after(run_id, 0) == []
    assert backend.get_run_context(run_id) is None
    assert redis_client.exists(f"gen_task:events:{run_id}") == 0


def test_duplicate_seq_does_not_corrupt_order(log):
    """seq 被当 stream ID 用，重复写必须失败而不是插进去乱序。"""
    backend, run_id = log
    assert backend.record(run_id, 5, _frame(5)) is True
    assert backend.record(run_id, 5, _frame(5, "dup")) is False, "重复 seq 应写入失败"
    frames = backend.history_after(run_id, 0)
    assert len(frames) == 1 and "dup" not in frames[0]


# ---------- 门面：后端选择与降级 ----------

class _NoRedis:
    def __init__(self):
        self.calls = 0

    def available(self):
        return False

    def record(self, *a, **kw):
        self.calls += 1
        return False


def test_facade_uses_memory_when_redis_absent():
    mem = EventReplayBuffer()
    facade = RunEventLog(_NoRedis(), mem)
    run_id = "r-absent"
    facade.record(run_id, 1, _frame(1))
    facade.record(run_id, 2, _frame(2))
    assert facade.backend_of(run_id) == "memory"
    assert len(facade.history_after(run_id, 0)) == 2


def test_facade_pins_backend_per_run():
    """一个 run 的帧不能一半 Redis 一半内存：否则按游标读到的是残缺序列。"""
    class _Flaky:
        def __init__(self):
            self.up = True

        def available(self):
            return self.up

        def record(self, run_id, seq, frame, thought=None):
            return self.up

    flaky = _Flaky()
    facade = RunEventLog(flaky, EventReplayBuffer())
    run_id = "r-pin"
    facade.record(run_id, 1, _frame(1))
    assert facade.backend_of(run_id) == "redis"

    flaky.up = False  # Redis 中途挂掉
    facade.record(run_id, 2, _frame(2))
    assert facade.backend_of(run_id) == "memory", "写入失败后该 run 应整体退回内存"
    # 退回内存后不再回头问 Redis，避免序列分裂
    flaky.up = True
    assert facade.backend_of(run_id) == "memory"


def test_facade_new_run_picks_redis_again():
    class _Up:
        def available(self):
            return True

        def record(self, run_id, seq, frame, thought=None):
            return True

        def history_after(self, run_id, last_seq):
            return ["from-redis"]

    facade = RunEventLog(_Up(), EventReplayBuffer())
    assert facade.history_after("r-new", 0) == ["from-redis"]
    assert facade.backend_of("r-new") == "redis"
