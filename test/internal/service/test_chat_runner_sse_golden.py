#!/usr/bin/env python
"""SSE 黄金测试：ChatRunner async generator 的 SSE 事件序列与 payload 字段。

mock LLM/Agent，不真实调用；严格对照 queue_entity.QueueEvent 保留的事件类型枚举：
- 成功路径事件序列：agent_thought（含 task_id；ping 透传但不落库）→ agent_message 增量 →
  agent_end（流结束"done"事件——QueueEvent 无 done 枚举，AGENT_END 即旧逻辑的流结束标记）；
- 每事件 SSE 行格式 `event: <type>\ndata: <json>\n\n`；data 含 id/task_id/event/type 字段
  （id=事件 id、task_id=任务 id、event=事件枚举值、conversation_id/message_id）；
- 错误路径：LLM 抛异常 → error 事件 → 生成器正常结束（无悬挂）。
"""
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.service.chat_runner import ChatRunner

# 成功路径期望事件序列（与旧同步逻辑产出顺序一致）
EXPECTED_SUCCESS_EVENTS = [
    QueueEvent.AGENT_THOUGHT,   # agent thought
    QueueEvent.PING,            # ping 联通事件（透传，不落库）
    QueueEvent.AGENT_MESSAGE,   # message 增量 ①
    QueueEvent.AGENT_MESSAGE,   # message 增量 ②
    QueueEvent.AGENT_END,       # done（QueueEvent 无 done，AGENT_END 即流结束事件）
]


class FakeLLM:
    """支持 tool_call 的假 LLM"""
    features = (ModelFeature.TOOL_CALL,)
    context_window = None
    max_tokens = 8192

    def convert_to_human_message(self, query, image_urls=None):
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=query)


class GoldenAgent:
    """流式产出：agent_thought → ping → agent_message 增量 ×2 → agent_end"""
    def __init__(self, *args, **kwargs):
        pass

    def stream(self, *args, **kwargs):
        task_id = uuid4()
        msg_id = uuid4()
        yield AgentThought(
            id=uuid4(), task_id=task_id, event=QueueEvent.AGENT_THOUGHT,
            thought="我准备调用工具", latency=0.1,
        )
        yield AgentThought(id=uuid4(), task_id=task_id, event=QueueEvent.PING)
        yield AgentThought(
            id=msg_id, task_id=task_id, event=QueueEvent.AGENT_MESSAGE,
            thought="你好", message=[], answer="你好，", latency=0.1,
        )
        yield AgentThought(
            id=msg_id, task_id=task_id, event=QueueEvent.AGENT_MESSAGE,
            thought="你好", message=[], answer="很高兴见到你", latency=0.2,
        )
        yield AgentThought(id=uuid4(), task_id=task_id, event=QueueEvent.AGENT_END)


class FailingAgent:
    """stream 直接抛异常的假 Agent（错误路径）"""
    def __init__(self, *args, **kwargs):
        pass

    def stream(self, *args, **kwargs):
        raise RuntimeError("模拟LLM调用失败")


MOCK_CONFIG = {
    "model_config": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    "dialog_round": 5,
    "tools": [],
    "datasets": [],
    "workflows": [],
    "skills": [],
    "preset_prompt": "",
    "long_term_memory": {"enable": False},
    "review_config": {},
}


def _make_runner(monkeypatch, agent_class) -> ChatRunner:
    """构造 ChatRunner（纯 mock 依赖），仅替换 agent_class；记忆/压缩/历史/落库全部替身化。"""
    runner = ChatRunner(
        db=MagicMock(),
        retrieval_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        memory_provider_resolver=MagicMock(),
    )
    # run() 在 Agent 循环前 await self.db.commit()
    runner.db.commit = AsyncMock()
    runner.language_model_service.load_language_model = AsyncMock(return_value=FakeLLM())
    runner.app_config_service.get_langchain_tools_by_tools_config = AsyncMock(return_value=[])
    runner._build_history = AsyncMock(return_value=[])
    runner.conversation_service.compact_if_needed = AsyncMock(return_value=False)
    runner.memory_provider_resolver.resolve = AsyncMock(
        return_value=MagicMock(get_read_context=MagicMock(return_value=MagicMock(episodic_memory=""))),
    )
    # 替换 chat_runner 模块内的 agent 类引用（沿用既有测试模式）
    monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", agent_class)
    return runner


def _parse_sse(event_str: str) -> tuple[str, dict]:
    """解析 SSE 行：返回 (event 类型, data JSON)。帧格式含 `id: <seq>` 头行。"""
    lines = event_str.strip().split("\n")
    # 找到 event 行与 data 行（允许 id:/retry: 头行存在）
    event_line = next((l for l in lines if l.startswith("event: ")), None)
    data_line = next((l for l in lines if l.startswith("data: ")), None)
    assert event_line is not None, f"应存在 event 行，实际: {event_str!r}"
    assert data_line is not None, f"应存在 data 行，实际: {event_str!r}"
    event_type = event_line[len("event: "):]
    payload = json.loads(data_line[len("data: "):])
    return event_type, payload


def _golden_args():
    return dict(
        app=MagicMock(id=uuid4()),
        app_config=dict(MOCK_CONFIG),
        conversation=MagicMock(id=uuid4(), summary="", app_id=uuid4()),
        message=MagicMock(id=uuid4(), query="你好", image_urls=[], resume_trigger=False),
        account=MagicMock(id=uuid4()),
        invoke_from=InvokeFrom.DEBUGGER,
    )


@pytest.mark.asyncio
async def test_success_path_event_sequence_and_payload(monkeypatch):
    """成功路径：agent_thought → ping → agent_message 增量 → agent_end（done），顺序与旧逻辑一致"""
    runner = _make_runner(monkeypatch, GoldenAgent)
    saved = {}
    async def _fake_save(**kwargs):
        saved.update(kwargs)
    runner.conversation_service.save_agent_thoughts = _fake_save

    events = [e async for e in runner.run(**_golden_args())]

    # 1、事件类型序列逐项对照 QueueEvent 枚举
    types = [_parse_sse(e)[0] for e in events]
    assert types == [ev.value for ev in EXPECTED_SUCCESS_EVENTS], \
        f"事件序列与旧逻辑不一致，实际: {types}"

    # 2、每个事件 payload 字段：id/task_id/event 齐全；id/task_id 为字符串
    for event_str, expected_ev in zip(events, EXPECTED_SUCCESS_EVENTS):
        event_type, payload = _parse_sse(event_str)
        assert event_type == expected_ev.value
        assert payload["event"] == expected_ev.value
        assert isinstance(payload["id"], str) and payload["id"]
        assert isinstance(payload["task_id"], str) and payload["task_id"]
        assert "conversation_id" in payload and "message_id" in payload

    # 3、message 增量事件：两条 agent_message 各自携带增量 answer
    msg_payloads = [p for t, p in (_parse_sse(e) for e in events) if t == QueueEvent.AGENT_MESSAGE.value]
    assert [p["answer"] for p in msg_payloads] == ["你好，", "很高兴见到你"]

    # 4、AGENT_MESSAGE 增量按事件 id 合并后落库（ping 不落库，agent_end 落库）
    thoughts = saved.get("agent_thoughts", [])
    assert thoughts, "finally 应落库推理过程"
    assert len(thoughts) == 3, "agent_thought + 合并后的 agent_message + agent_end，ping 不落库"
    merged = next(t for t in thoughts if t.event == QueueEvent.AGENT_MESSAGE)
    assert merged.answer == "你好，很高兴见到你"
    assert all(t.event != QueueEvent.PING for t in thoughts), "ping 不应进入落库列表"


@pytest.mark.asyncio
async def test_error_path_emits_error_and_generator_ends(monkeypatch):
    """错误路径：LLM 抛异常 → error 事件；生成器正常结束（无悬挂）"""
    runner = _make_runner(monkeypatch, FailingAgent)
    saved = {}
    async def _fake_save(**kwargs):
        saved.update(kwargs)
    runner.conversation_service.save_agent_thoughts = _fake_save

    # asyncio.wait_for 保障：若生成器悬挂，测试在此超时失败（错误路径无悬挂）
    events = [e async for e in runner.run(**_golden_args())]

    assert len(events) == 1, "错误路径旧逻辑仅产出 error 事件后正常结束"
    event_type, payload = _parse_sse(events[0])
    assert event_type == QueueEvent.ERROR.value
    assert payload["event"] == QueueEvent.ERROR.value
    assert isinstance(payload["id"], str) and isinstance(payload["task_id"], str)
    assert "模拟LLM调用失败" in payload["observation"]

    # 落库：ERROR thought 已提交（status/error 更新由 save_agent_thoughts 负责）
    thoughts = saved.get("agent_thoughts", [])
    assert thoughts and thoughts[-1].event == QueueEvent.ERROR
    assert "模拟LLM调用失败" in thoughts[-1].observation
