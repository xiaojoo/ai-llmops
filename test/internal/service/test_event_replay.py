"""SSE 事件缓冲 + Last-Event-ID 重放（event_replay.EventReplayBuffer）单测。

锁定断线续传地基的正确性：按 run_id 记录已发帧，`history_after` 按序号补发。
"""
from internal.service.event_replay import EventReplayBuffer


def _frame(seq: int, tag: str) -> str:
    # 模拟 sse_format 输出（id: <seq> 是 Last-Event-ID 的序号单位）
    return f"id: {seq}\nevent: {tag}\ndata: {{\"seq\": {seq}}}\n\n"


def test_record_and_history_after_ordered():
    buf = EventReplayBuffer()
    buf.record("run-1", 1, _frame(1, "a"))
    buf.record("run-1", 2, _frame(2, "b"))
    buf.record("run-1", 3, _frame(3, "c"))

    # 全量重放（last_seq=0）
    assert buf.history_after("run-1", 0) == [_frame(1, "a"), _frame(2, "b"), _frame(3, "c")]
    # 从 1 之后（跳过 1）
    assert buf.history_after("run-1", 1) == [_frame(2, "b"), _frame(3, "c")]
    # 从 2 之后
    assert buf.history_after("run-1", 2) == [_frame(3, "c")]
    # 已到最新
    assert buf.history_after("run-1", 3) == []


def test_last_seq():
    buf = EventReplayBuffer()
    assert buf.last_seq("run-x") == 0
    buf.record("run-x", 5, _frame(5, "a"))
    buf.record("run-x", 9, _frame(9, "b"))
    assert buf.last_seq("run-x") == 9


def test_unknown_run_returns_empty():
    buf = EventReplayBuffer()
    assert buf.history_after("nope", 0) == []
    assert buf.last_seq("nope") == 0


def test_clear_releases():
    buf = EventReplayBuffer()
    buf.record("run-1", 1, _frame(1, "a"))
    assert buf.history_after("run-1", 0)
    buf.clear("run-1")
    assert buf.history_after("run-1", 0) == []
    assert buf.last_seq("run-1") == 0
    assert len(buf) == 0


def test_ring_buffer_caps_at_maxlen():
    # 超过上限只保留最新 N 条，避免长时间 run 内存膨胀
    buf = EventReplayBuffer(maxlen=3)
    for i in range(1, 7):
        buf.record("r", i, _frame(i, "a"))
    assert buf.history_after("r", 0) == [_frame(4, "a"), _frame(5, "a"), _frame(6, "a")]


def test_run_scoping_isolated():
    buf = EventReplayBuffer()
    buf.record("run-a", 1, _frame(1, "a"))
    buf.record("run-b", 1, _frame(1, "b"))
    assert buf.history_after("run-a", 0) == [_frame(1, "a")]
    assert buf.history_after("run-b", 0) == [_frame(1, "b")]
    assert len(buf) == 2
