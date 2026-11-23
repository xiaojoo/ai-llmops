import asyncio
import time
import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

from internal.core.agent.agents import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig, SubTaskSpec
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.entities.queue_entity import QueueEvent as QE
from internal.entity.conversation_entity import InvokeFrom
from internal.model import SubTaskCheckpoint
from package.database import build_engine, worker_run

# 断点读写经 worker_run 独立引擎真实落库（uuid 隔离），agent.stream 经
# to_thread 在无运行中 loop 的线程执行（agent 内部断点桥接同样走 worker_run + 独立 engine）。


@pytest.fixture(autouse=True)
def _mock_confirm_waits(monkeypatch):
    """图级测试聚焦断点恢复机制：确认节点真实执行，但把阻塞在 Redis 的
    wait_for_plan_choice 替换为"确认全量"（真实实现会 blpop 300s 挂起测试）"""
    monkeypatch.setattr(
        "internal.core.agent.agents.agent_queue_manager.AgentQueueManager.wait_for_plan_choice",
        MagicMock(return_value=("confirm", [], "", False)),
    )


async def _run_worker(coro_factory, *, commit: bool = True):
    """在 to_thread 线程执行 worker_run（独立 engine，真实提交/查询）"""
    return await asyncio.to_thread(
        lambda: worker_run(coro_factory, commit_on_success=commit, engine_factory=build_engine)
    )


def _save_checkpoint(conv_id, spec, messages=None, **extra):
    """预置断点：断点按 message_id 定位，测试里 message_id 即 conv_id
    （节点内 message_id 缺省回落到 conversation_id）"""
    def _save(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.save_checkpoint(
            app_id=uuid.uuid4(), conversation_id=conv_id, message_id=conv_id,
            position=1, query="写报告", spec=spec, status="stop",
            messages=messages if messages is not None
            else [{"type": "human", "data": {"content": "x"}}],
            iteration_count=2, partial_answer="部分内容", **extra,
        )
    return _save


def _get_checkpoint(conv_id, position=1):
    def _get(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.get_checkpoint(conv_id, position)
    return _get


@pytest.mark.asyncio
async def test_resume_auto_continues_from_checkpoint(monkeypatch):
    """auto 模式：断点存在且 query 匹配 → 子任务恢复续跑（resume=True 输入）"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

    captured = {}

    class RecordingLLM(FakeOrchestratorLLM):
        def stream(self, messages):
            captured["last_input"] = messages
            yield from super().stream(messages)

    class RecordingQueue(StubQueueManager):
        def __init__(self, user_id=None, invoke_from=None, model_name=""):
            super().__init__(user_id=user_id, invoke_from=invoke_from, model_name=model_name)
            self.sub_inputs = []

    # 预置断点：position 1 已中断（worker_run 独立引擎真实提交）
    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    await _run_worker(_save_checkpoint(conv_id, spec))

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", RecordingQueue)

    agent = OrchestratorAgent(
        name="orch",
        llm=RecordingLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    events = await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")],
        "history": [],
        "conversation_id": conv_id,
        "query": "写报告",
        "resume_trigger": False,
    })))
    # 恢复执行：事件中应出现子任务消息事件
    sub_msgs = [e for e in events if e.event == QE.AGENT_MESSAGE and e.sub_task_id]
    assert sub_msgs, "断点恢复后子任务应继续产出事件"
    # 完成后断点应标记 complete
    ck = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert ck.status == "complete"


@pytest.mark.asyncio
async def test_resume_manual_ignores_checkpoint_without_trigger(monkeypatch):
    """manual 模式：resume_trigger=False → 不查断点，全新执行（断点仍为 stop）"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    await _run_worker(_save_checkpoint(conv_id, spec, messages=[]))

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"resume_mode": "manual"},
        ),
    )
    await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    })))
    ck = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert ck.status == "complete"  # 全新执行并覆盖断点


@pytest.mark.asyncio
async def test_resume_reuses_completed_cache(monkeypatch):
    """complete 断点 → 子任务跳过执行，直接复用缓存答案"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    await _run_worker(_save_checkpoint(conv_id, spec, messages=[]))

    def _mark_complete(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.mark_complete(
            message_id=conv_id, position=1, answer="缓存答案",
            total_token_count=1, total_price=0.0,
        )
    await _run_worker(_mark_complete)

    seen_sub_start = []

    class CountingQueue(StubQueueManager):
        def __init__(self, user_id=None, invoke_from=None, model_name=""):
            super().__init__(user_id=user_id, invoke_from=invoke_from, model_name=model_name)

        def publish(self, task_id, thought):
            if thought.event == QE.SUB_TASK_START:
                seen_sub_start.append(thought)
            super().publish(task_id, thought)

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", CountingQueue)
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"resume_mode": "auto"},
        ),
    )
    start = time.perf_counter()
    await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    })))
    elapsed = time.perf_counter() - start
    assert seen_sub_start == [], "complete 缓存子任务不应重新执行（不发布 SUB_TASK_START）"
    assert elapsed < 4, f"缓存复用不应因 monitor join 阻塞，实际耗时 {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_orchestrator_checkpoint_stores_state_messages(monkeypatch):
    """断点 messages 保存最后一步的运行态消息（含系统提示词），而非仅输入消息"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    })))
    ck = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert ck is not None and ck.status == "complete"
    assert any(m.get("type") == "system" for m in (ck.messages or [])), \
        f"断点 messages 应含运行态系统提示词，实际: {ck.messages}"


@pytest.mark.asyncio
async def test_resume_llm_input_contains_system_message(monkeypatch):
    """恢复路径以断点消息（含系统提示词）直接续跑，LLM 输入包含 SystemMessage"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager
    from langchain_core.messages import SystemMessage

    captured = {}

    class RecordingLLM(FakeOrchestratorLLM):
        def stream(self, messages):
            captured.setdefault("inputs", []).append(messages)
            yield from super().stream(messages)

    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    await _run_worker(_save_checkpoint(
        conv_id, spec,
        messages=[
            {"type": "system", "data": {"content": "系统提示"}},
            {"type": "human", "data": {"content": "写报告"}},
        ],
    ))

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch", llm=RecordingLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    })))
    # 子 Agent 的 LLM 输入（含 HumanMessage）区别于汇总阶段输入（仅 SystemMessage）
    sub_inputs = [m for m in captured["inputs"] if any(isinstance(x, HumanMessage) for x in m)]
    assert sub_inputs, "应捕获到子 Agent 的 LLM 输入"
    assert any(isinstance(m, SystemMessage) for m in sub_inputs[0]), \
        f"恢复路径 LLM 输入应含系统提示词，实际: {sub_inputs[0]}"


# ===========================================================================
# 退化直答（无子任务，_direct_answer_node）的断点续跑
# ===========================================================================
def _save_direct_answer_checkpoint(
        conv_id, message_id, *, status="timeout", partial_answer="已生成部分代码。",
):
    """预置直答哨兵位置(-1)断点，用于直答续跑测试"""
    from internal.core.agent.entities.agent_entity import SubTaskSpec as _SubTaskSpec

    def _save(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.save_checkpoint(
            app_id=uuid.uuid4(), conversation_id=conv_id, message_id=message_id,
            position=-1, query="写一个战舰游戏",
            spec=_SubTaskSpec(order=-1, title="直接回答", role_prompt="", expect_output=""),
            status=status,
            messages=[
                {"type": "system", "data": {"content": "系统提示"}},
                {"type": "human", "data": {"content": "写一个战舰游戏"}},
            ],
            iteration_count=3, partial_answer=partial_answer,
        )
    return _save


class FakeDirectAnswerAgent:
    """直答子 Agent 替身：stream 直接产出 AgentThought 事件（不再经真实 FunctionCallAgent 图），
    聚焦验证 _direct_answer_node 的断点查询/恢复输入/终态落盘逻辑。"""

    def __init__(self, events):
        self._events = list(events)
        self.captured_input = None

    def stream(self, input_data, config=None, **kwargs):
        self.captured_input = input_data
        for ev in self._events:
            yield ev


def _direct_answer_event(content, message_id=None):
    return AgentThought(
        id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.AGENT_MESSAGE,
        answer=content, thought=content, message=[{"type": "human", "data": {"content": content}}],
    )


def _get_direct_answer_checkpoint(conv_id, position=-1):
    def _get(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.get_checkpoint(conv_id, position)
    return _get


@pytest.mark.asyncio
async def test_direct_answer_resume_continues_from_checkpoint(monkeypatch):
    """直答（无子任务）路径：预置哨兵断点 → 直答以 resume=True 续跑并完成（断点置 complete）"""
    conv_id = uuid.uuid4()
    original_message_id = uuid.uuid4()
    fake = None

    def _build_direct_answer_agent(self):
        nonlocal fake
        # 直答子 Agent 产出两段内容，正常结束（无 TIMEOUT/STOP）
        fake = FakeDirectAnswerAgent([
            _direct_answer_event("继续输出代码"),
            _direct_answer_event("代码完成"),
        ])
        return fake

    monkeypatch.setattr(
        "internal.core.agent.agents.orchestrator_agent.OrchestratorAgent._build_direct_answer_agent",
        _build_direct_answer_agent,
    )
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)

    await _run_worker(_save_direct_answer_checkpoint(conv_id, original_message_id))

    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写一个战舰游戏")], "history": [],
        "conversation_id": conv_id, "query": "写一个战舰游戏", "resume_trigger": False,
        "resume_message_id": original_message_id,
    })))
    assert fake is not None
    assert fake.captured_input.get("resume") is True, "直答续跑应以 resume=True 进入子 Agent"
    assert fake.captured_input.get("iteration_count") == 3, "直答续跑应带断点的迭代次数"
    assert any("写一个战舰游戏" in str(m.content) for m in fake.captured_input.get("messages", []))
    # 续跑完成：哨兵(-1)断点应置 complete（不可再续跑）
    ck = await _run_worker(_get_direct_answer_checkpoint(original_message_id), commit=False)
    assert ck is not None, "直答应落哨兵(-1)断点"
    assert ck.status == "complete"


@pytest.mark.asyncio
async def test_direct_answer_timeout_persists_resumable_checkpoint(monkeypatch):
    """直答在父级 listen 超时（子 Agent 流内出 TIMEOUT 事件）后，哨兵(-1)断点保持 timeout 可恢复"""
    conv_id = uuid.uuid4()
    fake = None

    def _build_direct_answer_agent(self):
        nonlocal fake
        # 先产出一段内容，再抛出 TIMEOUT → 直答循环 break，落 timeout 断点（保留已生成内容）
        fake = FakeDirectAnswerAgent([
            _direct_answer_event("一段已生成内容"),
            AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.TIMEOUT),
        ])
        return fake

    monkeypatch.setattr(
        "internal.core.agent.agents.orchestrator_agent.OrchestratorAgent._build_direct_answer_agent",
        _build_direct_answer_agent,
    )
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)

    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写一个战舰游戏")], "history": [],
        "conversation_id": conv_id, "query": "写一个战舰游戏", "resume_trigger": False,
    })))
    ck = await _run_worker(_get_direct_answer_checkpoint(conv_id), commit=False)
    assert ck is not None, "直答超时后应落哨兵(-1)断点"
    assert ck.status == "timeout", f"直答超时断点应可恢复，实际: {ck.status}"
    assert "一段已生成内容" in (ck.partial_answer or ""), "直答应保留已生成的部分内容"
