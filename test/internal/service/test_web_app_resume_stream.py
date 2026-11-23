#!/usr/bin/env python
"""断流重连续传流（WebAppService.stream_web_app_chat_resume）的行为契约。

架构上这条流**只读事件日志、不碰队列**：客户端断开后队列由 ChatRunner 的接管者独占
（一个队列只能有一个读者，抢着读会各拿到一半事件），新事件由接管者写进日志，
本端点按游标跟读。所以这里的判据全部围绕日志写。

要锁的五件事：
 1) 断开期间产生、由接管者补写进日志的事件，重连后必须原样送达；
 2) 客户端已收到（seq <= last_event_id）的帧不得重复下发，否则前端 answer 会累加两遍；
 3) 落库必须早于把终态帧交给客户端——那是"可以关连接"的信号，写在 yield 之后会被
    GeneratorExit 跳过（真机这样丢过 2361 字）；
 4) 日志为空时不落库（save_agent_thoughts 是纯 INSERT，重跑会长出双份推理过程行）；
 5) run 已终态且日志已被接管者清空时，必须补一帧 agent_end 收流——否则这条连接会
    对着空日志干等到超时，客户端拿到 200 之后一个字也等不来（真机实测踩到）。
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.service import web_app_service as was
from internal.service.chat_runner import agent_thought_to_sse_frame
from internal.service.event_replay import run_event_log
from internal.service.web_app_service import WebAppService


def _svc(run_status: str = "running") -> WebAppService:
    """续传流只读事件日志；run 状态查询与落库换成假实现，所以不碰真会话/真库。

    run_status 默认 running：送达类判据要证的是"跟读日志"，不能被补发的终态帧糊过去。
    """
    svc = object.__new__(WebAppService)
    row = None if run_status == "missing" else SimpleNamespace(
        id="run", status=run_status, conversation_id="conv-1", message_id="msg-1",
    )
    result = MagicMock()
    result.first = MagicMock(return_value=row)
    svc.db = MagicMock()
    svc.db.execute = AsyncMock(return_value=result)
    svc.db.get = AsyncMock(return_value=row)
    svc.chat_runner = MagicMock()
    svc.chat_runner.persist_resumed_run = AsyncMock()
    return svc


def _thought(run_id, event: QueueEvent, **kw) -> AgentThought:
    return AgentThought(id=uuid.uuid4(), task_id=run_id, event=event, **kw)


def _append(run_id: str, seq: int, thought: AgentThought) -> None:
    """模拟接管者往事件日志追加一帧（带对象，供续传侧落库回读）。"""
    frame = agent_thought_to_sse_frame(
        thought, "conv-1", "msg-1", uuid.UUID(str(run_id)), seq,
    )
    run_event_log.record(str(run_id), seq, frame, thought)


async def _drain(gen, limit: int = 4000) -> list[str]:
    out: list[str] = []
    async for chunk in gen:
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


@pytest.fixture
def clean_run(monkeypatch):
    """隔离单个 run 的日志，并把轮询节奏压到测试可接受的范围。"""
    run_id = str(uuid.uuid4())
    monkeypatch.setattr(was, "_RESUME_POLL_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(was, "_RESUME_POLL_TIMEOUT_SECONDS", 1.0)
    yield run_id
    run_event_log.clear(run_id)


# ---------- 送达 ----------

@pytest.mark.asyncio
async def test_resume_delivers_events_appended_after_client_left(clean_run):
    """核心断言：客户端走后被接管者补写进日志的事件，重连后必须原样送达。"""
    run_id = clean_run
    _append(run_id, 1, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开前"))
    _append(run_id, 2, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开前2"))
    _append(run_id, 3, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开后生成的后半段"))
    _append(run_id, 4, _thought(run_id, QueueEvent.AGENT_END))

    body = "".join(await _drain(
        _svc().stream_web_app_chat_resume("token", run_id, 2, None)
    ))

    assert "断开后生成的后半段" in body, (
        f"重连后没拿到断开期间的事件 → 刷新回来会永久缺一段回答。实际：{body[:400]}"
    )
    assert "断开前" not in body, "客户端已收到 seq<=2，不该重复下发"


@pytest.mark.asyncio
async def test_resume_replays_only_unseen_frames(clean_run):
    """Last-Event-ID 已见过的帧不得重复下发——否则前端 answer 会把同一段累加两遍。"""
    run_id = clean_run
    for seq in (1, 2, 3):
        _append(run_id, seq, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought=f"内容{seq}"))
    _append(run_id, 4, _thought(run_id, QueueEvent.AGENT_END))

    body = "".join(await _drain(
        _svc().stream_web_app_chat_resume("token", run_id, 2, None)
    ))

    assert "内容1" not in body and "内容2" not in body, "已送达的帧不该重发"
    assert "内容3" in body, "seq=3 未送达，必须补发"


@pytest.mark.asyncio
async def test_resume_tails_frames_appended_while_streaming(clean_run):
    """流打开之后日志里才出现的事件也要跟到：这是接管者还在跑时的真实时序。"""
    run_id = clean_run
    _append(run_id, 1, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="先有"))

    gen = _svc().stream_web_app_chat_resume("token", run_id, 0, None)
    assert "先有" in await gen.__anext__()

    # 客户端还挂着，接管者继续往日志里追加
    _append(run_id, 2, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="后到"))
    _append(run_id, 3, _thought(run_id, QueueEvent.AGENT_END))

    rest = ""
    async for frame in gen:
        rest += frame
    assert "后到" in rest, "跟读循环没拿到流打开之后才写入的帧"


# ---------- 落库 ----------

@pytest.mark.asyncio
async def test_resume_persists_pre_and_post_disconnect_thoughts(clean_run):
    """续传结束要落库，且把"断开前已发出"那批一起落——断开路径的 finally 落不了库。

    真机实测：重连把 29340 字送到了客户端，库里 message_agent_thought 却 0 行、
    run 永远 running，因为原流拿到 GeneratorExit 后那个 await 不会被恢复。
    """
    run_id = clean_run
    _append(run_id, 1, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开前", answer="a1"))
    _append(run_id, 2, _thought(run_id, QueueEvent.AGENT_MESSAGE, thought="断开后", answer="a2"))
    _append(run_id, 3, _thought(run_id, QueueEvent.AGENT_END))

    svc = _svc()
    captured: dict = {}

    async def _fake_persist(*, run, thoughts, account):
        captured["thoughts"] = thoughts

    svc.chat_runner.persist_resumed_run = _fake_persist

    await _drain(svc.stream_web_app_chat_resume("token", run_id, 0, None))

    assert "thoughts" in captured, "续传结束后没落库 → 库里 answer 仍为空、run 停在 running"
    texts = [t.thought for t in captured["thoughts"]]
    assert any("断开前" in (x or "") for x in texts), f"断开前那批没被带上：{texts}"
    assert any("断开后" in (x or "") for x in texts), f"断开后那批没被带上：{texts}"


@pytest.mark.asyncio
async def test_persist_happens_before_terminal_frame_is_sent(clean_run):
    """落库必须早于终态帧交给客户端：客户端一收到 agent_end 就可能关连接。"""
    run_id = clean_run
    _append(run_id, 1, _thought(run_id, QueueEvent.AGENT_MESSAGE, answer="正文"))
    _append(run_id, 2, _thought(run_id, QueueEvent.AGENT_END))

    order: list[str] = []

    async def _fake_persist(*, run, thoughts, account):
        order.append("persist")

    svc = _svc()
    svc.chat_runner.persist_resumed_run = _fake_persist

    async for frame in svc.stream_web_app_chat_resume("token", run_id, 0, None):
        if "event: agent_end" in frame:
            order.append("end_frame")
            break
        order.append("frame")

    assert order == ["frame", "persist", "end_frame"], (
        f"落库应在 agent_end 帧送达客户端之前完成，实际顺序：{order}"
    )


@pytest.mark.asyncio
async def test_resume_with_empty_log_does_not_persist(clean_run):
    """run 还在跑、日志暂时无内容：不能吐帧，也不能去写库。"""
    run_id = clean_run
    svc = _svc()

    frames = await _drain(
        svc.stream_web_app_chat_resume("token", run_id, 0, None), limit=5,
    )

    assert frames == [], "run 未结束且日志为空时不该凭空造帧"
    assert svc.chat_runner.persist_resumed_run.await_count == 0, (
        "空事件也落库会让 save_agent_thoughts 重复 INSERT 推理过程行"
    )


# ---------- 已结束的 run 必须收流 ----------

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled", "timed_out"])
async def test_resume_closes_when_run_already_terminated(clean_run, status):
    """run 已被接管者跑完并清掉日志：重连必须拿到一帧 agent_end 而不是挂到超时。

    真机时序：断开→接管者把 run 跑完落库→清日志，这中间客户端才回来重连。
    补发的终态帧同时是"内容请回源取"的信号（answer 已在库里，不再重放事件）。
    """
    run_id = clean_run
    frames = await _drain(
        _svc(status).stream_web_app_chat_resume("token", run_id, 6, None), limit=5,
    )

    assert len(frames) == 1, f"run 已终态（{status}）应只补一帧收流，实际 {len(frames)} 帧"
    assert "event: agent_end" in frames[0], f"补的必须是终态帧，实际：{frames[0]}"
    # 序号接在客户端游标之后，前端游标才不会错乱
    assert "id: 7" in frames[0], f"终态帧序号应接在 last_event_id 之后，实际：{frames[0]}"


@pytest.mark.asyncio
async def test_resume_closes_when_run_row_is_gone(clean_run):
    """run 行查不到（被清理/并发删除）：同样要收流，别把客户端吊在空连接上。"""
    run_id = clean_run
    frames = await _drain(
        _svc("missing").stream_web_app_chat_resume("token", run_id, 0, None), limit=5,
    )

    assert frames and "event: agent_end" in frames[0], "run 不存在时必须立即收流"


@pytest.mark.asyncio
async def test_resume_does_not_invent_frame_when_status_query_fails(clean_run):
    """状态查询报错时不许误判成"已结束"：宁可跟读到超时，也别提前收掉一个还在跑的轮次。"""
    run_id = clean_run
    svc = _svc()
    svc.db.execute = AsyncMock(side_effect=RuntimeError("库连接断了"))

    frames = await _drain(
        svc.stream_web_app_chat_resume("token", run_id, 0, None), limit=5,
    )

    assert svc.db.execute.await_count >= 1, "没走到状态查询就等于没测异常分支"
    assert frames == [], "凭空补 agent_end 会让客户端把还在生成的回答当成已完成"
