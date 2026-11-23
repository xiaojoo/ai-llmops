#!/usr/bin/env python
"""断开接管者（ChatRunner._start_takeover / _take_over_run / _persist_detached）的判据。

这一层是第 2 期要根治的东西：客户端断开后如果没人再回来，队列就没人读——真机实测
库里留下过 12 条 status=running 的孤儿 run，答案一个字都没落库。接管者在断开那一刻
（原读者已退出、队列无争用）接手把队列读完、写进事件日志、落库并终结 run。

判据重点：
 * 序号必须接着断开前的 seq 往下写，否则重连端点的游标会错乱；
 * 见到终态事件就停，不能永久挂在队列上；
 * 落库权用 SETNX 认领，和重连端点二选一，否则 save_agent_thoughts 会写出双份行；
 * 落库必须自带会话（请求的 AsyncSession 已随响应关闭）。
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from internal.service.chat_runner import ChatRunner
from internal.service.event_replay import run_event_log


def _runner() -> ChatRunner:
    return ChatRunner(
        db=MagicMock(),
        retrieval_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        memory_provider_resolver=MagicMock(),
    )


def _thought(run_id, event: QueueEvent, **kw) -> AgentThought:
    return AgentThought(id=uuid.uuid4(), task_id=run_id, event=event, **kw)


def _ctx(run_id, *, store=None, seq: int = 0):
    """_take_over_run 的入参。落库方法只吃其中一部分，用 _persist_args 取。"""
    account = SimpleNamespace(id=uuid.uuid4())
    return dict(
        run_id=run_id,
        store=store if store is not None else {},
        seq=seq,
        app=SimpleNamespace(id=uuid.uuid4()),
        app_config={},
        conversation=SimpleNamespace(id=uuid.uuid4()),
        message=SimpleNamespace(id=uuid.uuid4()),
        account=account,
        invoke_from=InvokeFrom.WEB_APP,
    )


def _persist_args(ctx: dict, thoughts: list) -> dict:
    """_persist_detached 的签名里没有 store/seq，从 ctx 里挑它要的。"""
    return {k: v for k, v in ctx.items() if k not in ("store", "seq")} | {"thoughts": thoughts}


@pytest.fixture
def clean_queue():
    run_id = uuid.uuid4()
    yield run_id
    AgentQueueManager._queues.pop(str(run_id), None)
    run_event_log.clear(str(run_id))


def _publish(run_id, *thoughts):
    """按图线程的真实路径发事件（终态事件会顺带 put(None) 停掉监听）。"""
    manager = AgentQueueManager(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP)
    for t in thoughts:
        manager.publish(run_id, t)


@pytest.mark.asyncio
async def test_takeover_drains_queue_into_log(clean_queue):
    """断开后的事件要被读完并写进事件日志，重连的客户端正是从日志跟读的。

    注意断言时机：_take_over_run 的 finally 会 clear 日志（run 已结束、DB 里已有答案，
    不清就是无限增长的内存），所以必须在落库那一刻取日志快照。
    """
    run_id = clean_queue
    runner = _runner()
    captured: dict = {}

    async def _fake_persist(**kw):
        captured.update(kw)
        captured["log_snapshot"] = run_event_log.history_after(str(run_id), 0)

    runner._persist_detached = _fake_persist
    _publish(run_id, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开后第一段"))
    _publish(run_id, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开后第二段"))
    _publish(run_id, _thought(run_id, QueueEvent.AGENT_END))

    await runner._take_over_run(**_ctx(run_id))

    assert "thoughts" in captured, "接管结束后没有落库 → run 会永远停在 running"
    texts = [t.thought for t in captured["thoughts"] if t.thought]
    assert texts == ["断开后第一段", "断开后第二段"], f"两段都该收到：{texts}"
    assert len(captured["log_snapshot"]) == 3, (
        f"3 帧都应写进日志供重连跟读，实际 {len(captured['log_snapshot'])}"
    )
    # 收尾必须清日志，否则每个 run 都留下一份永不释放的事件副本
    assert run_event_log.history_after(str(run_id), 0) == [], "接管结束应已清空日志"


@pytest.mark.asyncio
async def test_takeover_continues_seq_after_disconnect(clean_queue):
    """序号必须接着断开前继续：重连端点拿 last_event_id 当游标，接不上就会漏帧/重帧。"""
    run_id = clean_queue
    runner = _runner()
    ids: list[int] = []

    async def _fake_persist(**kw):
        from internal.service.web_app_service import _parse_sse_frame

        ids.extend(_parse_sse_frame(f)[0] for f in run_event_log.history_after(str(run_id), 0))

    runner._persist_detached = _fake_persist
    _publish(run_id, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="x"))
    _publish(run_id, _thought(run_id, QueueEvent.AGENT_END))

    await runner._take_over_run(**_ctx(run_id, seq=42))  # 断开前已发到 42

    assert ids == [43, 44], f"应接着 42 往下编号，实际 {ids}"


@pytest.mark.asyncio
async def test_takeover_stops_at_terminal_and_does_not_hang(clean_queue):
    """必须见到终态就返回：挂在队列上等于一个永不退出的后台任务。"""
    run_id = clean_queue
    runner = _runner()
    last: list[int] = []

    async def _fake_persist(**kw):
        last.append(run_event_log.last_seq(str(run_id)))

    runner._persist_detached = _fake_persist
    _publish(run_id, _thought(run_id, QueueEvent.STOP, observation="用户停止"))

    await asyncio.wait_for(runner._take_over_run(**_ctx(run_id)), timeout=15)
    assert last == [1], f"只应读到那一条 STOP 就收手，实际 last_seq={last}"


@pytest.mark.asyncio
async def test_takeover_persists_with_its_own_session(clean_queue, monkeypatch):
    """落库必须走 worker_run 自带会话：请求的 AsyncSession 已随响应关闭。"""
    run_id = clean_queue
    runner = _runner()
    calls: list = []

    def _fake_worker_run(fn, **kw):
        calls.append(kw.get("engine_factory"))
        return None

    import package.database

    monkeypatch.setattr(package.database, "worker_run", _fake_worker_run)
    thoughts = [_thought(run_id, QueueEvent.AGENT_MESSAGE, thought="x")]

    await runner._persist_detached(**_persist_args(_ctx(run_id), thoughts))

    assert len(calls) == 1, "落库没有走 worker_run（会复用已关闭的请求会话）"
    assert calls[0] is package.database.build_engine, "必须传 engine_factory，否则跨 loop 复用连接池"


@pytest.mark.asyncio
async def test_takeover_skips_persist_when_claim_taken(clean_queue, monkeypatch):
    """落库权已被重连端点认领时不能再写：save_agent_thoughts 是纯 INSERT，会写双份行。"""
    run_id = clean_queue
    runner = _runner()
    assert run_event_log.claim_persist(str(run_id)) is True, "先由重连端点认领走"

    called: list = []
    import package.database

    monkeypatch.setattr(
        package.database, "worker_run", lambda fn, **kw: called.append(1),
    )

    await runner._persist_detached(**_persist_args(
        _ctx(run_id), [_thought(run_id, QueueEvent.AGENT_MESSAGE)],
    ))

    assert called == [], "已被认领还去写库，会长出双份推理过程行"


@pytest.mark.asyncio
async def test_disconnect_schedules_takeover(clean_queue):
    """接线判据：客户端断开（aclose → GeneratorExit）时必须真的派出接管者。

    上面几条测的是接管者本身能用；这一条测的是"断开"这个事件确实触发了它。
    少了这层接线，接管者写得再对也是死代码。
    """
    from internal.service.chat_runner import _aiter_sync

    run_id = clean_queue
    runner = _runner()
    runner.conversation_service.save_agent_thoughts = AsyncMock()
    scheduled: list = []

    def _fake_start(**kw):
        scheduled.append(kw)

    runner._start_takeover = _fake_start

    def _sync_stream(_input):
        yield _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="第一段")
        yield _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="第二段")

    agent = MagicMock()
    agent.stream = lambda _input: _sync_stream(_input)
    llm = MagicMock()
    llm.convert_to_human_message = lambda q, imgs: q

    gen = runner._stream_and_persist(
        agent=agent, llm=llm, app=SimpleNamespace(id=uuid.uuid4()), app_config={},
        conversation=SimpleNamespace(id=uuid.uuid4(), summary=""),
        message=SimpleNamespace(id=uuid.uuid4(), query="q", image_urls=[]),
        account=SimpleNamespace(id=uuid.uuid4()), invoke_from=InvokeFrom.WEB_APP,
        history=[], user_profile="", run_id=run_id,
    )
    await gen.__anext__()  # 收到第一帧，模拟客户端正在看

    await gen.aclose()  # 客户端关页面

    assert len(scheduled) == 1, "客户端断开后没有派出接管者 → 这个 run 会成为孤儿"
    assert scheduled[0]["run_id"] == run_id
    assert _aiter_sync is not None


@pytest.mark.asyncio
async def test_normal_completion_does_not_schedule_takeover(clean_queue):
    """正常跑完不该派接管者：原流自己就会落库，再派一个只会抢队列。"""
    run_id = clean_queue
    runner = _runner()
    runner.conversation_service.save_agent_thoughts = AsyncMock()
    runner._record_run_finish = AsyncMock()
    scheduled: list = []
    runner._start_takeover = lambda **kw: scheduled.append(kw)

    def _sync_stream(_input):
        yield _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="第一段")
        yield _thought(run_id, QueueEvent.AGENT_END)

    agent = MagicMock()
    agent.stream = lambda _input: _sync_stream(_input)
    llm = MagicMock()
    llm.convert_to_human_message = lambda q, imgs: q

    gen = runner._stream_and_persist(
        agent=agent, llm=llm, app=SimpleNamespace(id=uuid.uuid4()), app_config={},
        conversation=SimpleNamespace(id=uuid.uuid4(), summary=""),
        message=SimpleNamespace(id=uuid.uuid4(), query="q", image_urls=[]),
        account=SimpleNamespace(id=uuid.uuid4()), invoke_from=InvokeFrom.WEB_APP,
        history=[], user_profile="", run_id=run_id,
    )
    frames = [f async for f in gen]

    assert len(frames) == 2, f"两帧都应送达，实际 {len(frames)}"
    assert scheduled == [], "正常结束不该派接管者"
    assert runner.conversation_service.save_agent_thoughts.await_count == 1, \
        "正常路径仍由原流自己落库"


@pytest.mark.asyncio
async def test_claim_is_one_shot_per_run():
    """同一个 run 只能认领一次落库权——这是接管者与重连端点二选一的依据。"""
    run_id = uuid.uuid4()
    try:
        assert run_event_log.claim_persist(str(run_id)) is True, "第一次应抢到"
        assert run_event_log.claim_persist(str(run_id)) is False, "第二次必须抢不到"
        assert run_event_log.claim_persist(str(run_id)) is False, "之后也一直抢不到"
    finally:
        run_event_log.clear(str(run_id))


@pytest.mark.asyncio
async def test_claim_reacquirable_after_clear():
    """clear 之后要能重新认领：否则内存兜底路径下复用同一 run_id 会永久写不了库。"""
    run_id = uuid.uuid4()
    assert run_event_log.claim_persist(str(run_id)) is True
    run_event_log.clear(str(run_id))
    assert run_event_log.claim_persist(str(run_id)) is True, "清理后应能重新认领"
    run_event_log.clear(str(run_id))
