import asyncio
import json
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import ConfigDict

from internal.core.agent.agents import OrchestratorAgent
from internal.core.agent.entities.agent_entity import (
    AgentConfig, ConfirmVerdict, SubTaskPlan, SubTaskSpec,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


@pytest.fixture(autouse=True)
def _mock_confirm_waits(monkeypatch):
    """图级测试聚焦 plan/execute/summarize/stop/timeout 机制：确认节点真实执行，
    但把阻塞在 Redis 的确认等待替换为"确认全量/无歧义"（真实 wait_for_plan_choice
    会 blpop 300s 挂起测试；confirm 交互细节由 confirm_plan/confirm_result 测试文件覆盖）"""
    monkeypatch.setattr(
        "internal.core.agent.agents.agent_queue_manager.AgentQueueManager.wait_for_plan_choice",
        MagicMock(return_value=("confirm", [], "", False)),
    )


class FakeOrchestratorLLM(BaseLanguageModel):
    """假 LLM：with_structured_output 返回固定计划；stream 产出固定文本"""
    model_config = ConfigDict(extra="allow")

    def __init__(self, *, subtasks=None, features=None, **kwargs):
        super().__init__(**kwargs)
        self._subtasks = subtasks
        self.features = features or [ModelFeature.TOOL_CALL]

    def with_structured_output(self, schema, **kwargs):
        # 注：嵌套类方法内的 self 是 FakePlanner 实例而非外层 LLM，
        # 必须经闭包捕获外层 subtasks（brief 原样会 AttributeError）。
        subtasks = self._subtasks
        if schema is ConfirmVerdict:
            # 确认点2（confirm_result 节点）：图级测试统一无歧义 → need_confirm=False
            # 直接 END，不再发布 ask_user / 阻塞 wait_for_choice
            class FakeVerdictPlanner:
                def invoke(self, messages):
                    return SimpleNamespace(need_confirm=False, reason="")
            return FakeVerdictPlanner()

        class FakePlanner:
            def invoke(self, messages):
                return SubTaskPlan(subtasks=subtasks or [])
        return FakePlanner()

    def stream(self, messages):
        yield AIMessageChunk(content="好的", tool_calls=[])

    def get_num_tokens_safe(self, messages):
        return 10

    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class StubQueueManager:
    """进程内收集事件，替代依赖 Redis 的真实管理器"""

    def __init__(self, user_id=None, invoke_from=None, model_name=""):
        self.events = []
        self._done = threading.Event()

    def publish(self, task_id, thought):
        self.events.append(thought)
        if thought.event in (QueueEvent.AGENT_END, QueueEvent.ERROR, QueueEvent.STOP, QueueEvent.TIMEOUT):
            self._done.set()

    def publish_error(self, task_id, error):
        self.publish(task_id, AgentThought(
            id=uuid.uuid4(), task_id=task_id,
            event=QueueEvent.ERROR, observation=str(error),
        ))

    def forward(self, task_id, thought):
        self.events.append(thought)

    def stop_listen(self, task_id):
        self._done.set()

    def listen(self, task_id):
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._done.is_set():
                yield from self.events
                return
            time.sleep(0.01)
        raise AssertionError("编排器图 15s 内未完成推理")

    def _is_stopped(self, task_id):
        return False


def _run_agent(monkeypatch, llm, input_extra=None):
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch",
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
            preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 2, "resume_mode": "auto"},
        ),
    )
    base = {"messages": [HumanMessage(content="写一篇市场调研报告")], "history": []}
    # 注：langgraph 1.2.11 不会为输入缺失的键填充 pydantic 默认值，state["query"] 会 KeyError；
    # query 是与 chat_runner 一致的一等输入键，测试须像生产调用方一样注入。
    base["query"] = "写一篇市场调研报告"
    if input_extra:
        base.update(input_extra)
    return list(agent.stream(base))


def test_orchestrator_decomposes_and_runs_subtasks(monkeypatch):
    specs = [
        SubTaskSpec(order=1, title="市场调研", role_prompt="你是调研员，负责收集市场数据", expect_output="调研结论"),
        SubTaskSpec(order=2, title="报告撰写", role_prompt="你是撰稿人，负责写报告", expect_output="报告正文"),
    ]
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=specs))
    kinds = [e.event for e in events]
    assert QueueEvent.SUB_TASK_PLAN in kinds
    assert kinds.count(QueueEvent.SUB_TASK_START) == 2
    assert kinds.count(QueueEvent.SUB_TASK_END) == 2
    assert kinds.count(QueueEvent.AGENT_END) == 1
    # 子任务事件带归属
    sub_events = [e for e in events if e.event == QueueEvent.AGENT_MESSAGE and e.sub_task_id]
    assert sub_events, "子 Agent 消息事件应桥接并带 sub_task_id"
    assert sub_events[0].sub_task_title in ("市场调研", "报告撰写")


def test_orchestrator_without_subtasks_degrades_to_direct_answer(monkeypatch):
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=[]))
    kinds = [e.event for e in events]
    assert QueueEvent.SUB_TASK_PLAN not in kinds
    assert QueueEvent.SUB_TASK_START not in kinds
    assert kinds.count(QueueEvent.AGENT_END) == 1
    assert any(e.event == QueueEvent.AGENT_MESSAGE for e in events)


def test_orchestrator_summarizes_sub_results(monkeypatch):
    specs = [SubTaskSpec(order=1, title="调研", role_prompt="调研", expect_output="结论")]
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=specs))
    # summarize 阶段产出 AGENT_MESSAGE（不带 sub_task_id）
    final_messages = [e for e in events if e.event == QueueEvent.AGENT_MESSAGE and not e.sub_task_id]
    assert final_messages, "汇总阶段应产出主消息"


class StoppableStubQueueManager(StubQueueManager):
    """停止感知替身：SUB_TASK_START 发布后即视为主任务已停止；记录所有监听方使用的任务id"""

    listen_ids = []  # 类级共享：跨实例记录 listen(task_id) 调用（主任务 + 各子 Agent）

    def __init__(self, user_id=None, invoke_from=None, model_name=""):
        super().__init__(user_id=user_id, invoke_from=invoke_from, model_name=model_name)
        self.stopped = threading.Event()

    def publish(self, task_id, thought):
        if thought.event == QueueEvent.SUB_TASK_START:
            self.stopped.set()
        super().publish(task_id, thought)

    def listen(self, task_id):
        type(self).listen_ids.append(task_id)
        return super().listen(task_id)

    def _is_stopped(self, task_id):
        return self.stopped.is_set()


class SlowStreamLLM(FakeOrchestratorLLM):
    """慢速流式 LLM：拉长子任务存活时间，保证停止监控轮询周期内子任务仍在运行"""

    def stream(self, messages):
        yield AIMessageChunk(content="第一段", tool_calls=[])
        time.sleep(1.0)
        yield AIMessageChunk(content="第二段", tool_calls=[])


def test_orchestrator_stop_propagates_to_subtasks(monkeypatch):
    """主任务停止 → 停止监控把 sub_task_id 作为停止目标，且子 Agent 监听的就是该 id"""
    recorded = []
    monkeypatch.setattr(
        "internal.core.agent.agents.orchestrator_agent.AgentQueueManager.set_stop_flag",
        staticmethod(lambda *args, **kwargs: recorded.append(args)),
    )
    StoppableStubQueueManager.listen_ids = []
    monkeypatch.setattr(
        "internal.core.agent.agents.base_agent.AgentQueueManager", StoppableStubQueueManager,
    )
    specs = [SubTaskSpec(order=1, title="调研", role_prompt="调研", expect_output="结论")]
    agent = OrchestratorAgent(
        name="orch",
        llm=SlowStreamLLM(subtasks=specs),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
            preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 2, "resume_mode": "auto"},
        ),
    )
    events = list(agent.stream({
        "messages": [HumanMessage(content="写一篇市场调研报告")],
        "history": [],
        "query": "写一篇市场调研报告",
    }))
    sub_task_id = specs[0].task_id
    assert sub_task_id is not None
    # 子 Agent 必须以 sub_task_id 监听（停止标志才能命中其监听队列）
    assert sub_task_id in StoppableStubQueueManager.listen_ids, \
        "子 Agent 应监听 sub_task_id，停止标志才能命中其监听队列"
    # 停止监控应把 sub_task_id 作为停止目标
    assert recorded, "主任务停止时应调用 set_stop_flag 传播给运行中的子任务"
    assert recorded[0][0] == sub_task_id


def test_orchestrator_happy_path_does_not_stall(monkeypatch):
    """无停止的 happy path 不应因 monitor.join(timeout=5) 阻塞（修复前每个 execute 节点烧满 5s）"""
    specs = [SubTaskSpec(order=1, title="调研", role_prompt="调研", expect_output="结论")]
    start = time.perf_counter()
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=specs))
    elapsed = time.perf_counter() - start
    kinds = [e.event for e in events]
    assert kinds.count(QueueEvent.AGENT_END) == 1
    assert elapsed < 4, f"happy path 不应因停止监控 join 阻塞，实际耗时 {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_orchestrator_stopped_subtask_persists_stop_checkpoint(monkeypatch):
    """主任务停止后，运行中的子任务以 stop 终态落断点/发 SUB_TASK_END/返回结果，而非 complete/normal

    agent 断点读写经 worker_run 独立引擎真实落库（不 monkeypatch
    create_sub_task_service），agent.stream 经 to_thread 在无运行中 loop 的线程执行。
    """
    from package.database import build_engine, worker_run

    def _get_ck(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.get_checkpoint(conv_id, 1)

    conv_id = uuid.uuid4()
    monkeypatch.setattr(
        "internal.core.agent.agents.orchestrator_agent.AgentQueueManager.set_stop_flag",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "internal.core.agent.agents.base_agent.AgentQueueManager", StoppableStubQueueManager,
    )
    captured = {}

    def spy_summarize(self, state):
        captured["sub_results"] = [r for r in state["sub_results"]]
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
        ))
        return {"messages": [AIMessage(content="")]}

    # 必须先于 agent 构造安装（StateGraph 在 __init__ 时绑定节点方法）
    monkeypatch.setattr(OrchestratorAgent, "_summarize_node", spy_summarize)

    specs = [SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")]
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=specs),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    events = await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    })))
    # 断点以 stop 终态落库（可恢复），而非 complete（不可恢复）
    ck = await asyncio.to_thread(
        lambda: worker_run(_get_ck, commit_on_success=False, engine_factory=build_engine)
    )
    assert ck is not None
    assert ck.status == "stop", f"停止的子任务应落 stop 断点，实际: {ck.status}"
    # SUB_TASK_END 事件 observation 反映停止
    end_events = [e for e in events if e.event == QueueEvent.SUB_TASK_END]
    assert end_events, "应发布 SUB_TASK_END"
    assert end_events[0].observation.startswith("stop:"), end_events[0].observation
    # 子任务结果状态为 stop（汇总阶段可见）
    assert captured["sub_results"], "汇总阶段应收到子任务结果"
    assert captured["sub_results"][0].status == "stop"


@pytest.mark.asyncio
async def test_orchestrator_timeout_sets_stop_flag_and_saves_timeout(monkeypatch):
    """子任务超时 → 顶部墙钟校验 break + set_stop_flag 终止子 Agent + timeout 断点落库"""
    from package.database import build_engine, worker_run

    def _get_ck(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.get_checkpoint(conv_id, 1)

    conv_id = uuid.uuid4()
    recorded = []
    monkeypatch.setattr(
        "internal.core.agent.agents.orchestrator_agent.AgentQueueManager.set_stop_flag",
        staticmethod(lambda *args, **kwargs: recorded.append(args)),
    )
    monkeypatch.setattr(
        "internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager,
    )

    def spy_summarize(self, state):
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
        ))
        return {"messages": [AIMessage(content="")]}

    monkeypatch.setattr(OrchestratorAgent, "_summarize_node", spy_summarize)

    specs = [SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")]
    agent = OrchestratorAgent(
        name="orch", llm=SlowStreamLLM(subtasks=specs),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto",
                                 "sub_task_timeout": 0.05},
        ),
    )
    events = await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    })))
    ck = await asyncio.to_thread(
        lambda: worker_run(_get_ck, commit_on_success=False, engine_factory=build_engine)
    )
    assert ck is not None and ck.status == "timeout"
    sub_task_id = specs[0].task_id
    assert recorded, "超时应调用 set_stop_flag 终止子 Agent 监听循环"
    assert recorded[0][0] == sub_task_id
    end_events = [e for e in events if e.event == QueueEvent.SUB_TASK_END]
    assert end_events and end_events[0].observation.startswith("timeout:"), \
        end_events[0].observation if end_events else "无 SUB_TASK_END"


class FakeTool(BaseTool):
    """最小可用工具替身：仅用于验证 required_tools 过滤与计划提示词"""
    description: str = "测试工具"

    def _run(self, *args, **kwargs):
        return ""


def test_build_sub_agent_filters_tools_by_required_tools(monkeypatch):
    """子 Agent 工具按 spec.required_tools 过滤；为空时使用全量工具池"""
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    tools = [FakeTool(name="天气工具"), FakeTool(name="搜索工具")]
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=tools,
            orchestrator_config={},
        ),
    )
    spec = SubTaskSpec(order=1, title="t", role_prompt="r", expect_output="e",
                       required_tools=["天气工具"])
    sub = agent._build_sub_agent(spec)
    assert [t.name for t in sub.agent_config.tools] == ["天气工具"], \
        "required_tools 非空时应过滤工具池"
    spec2 = SubTaskSpec(order=2, title="t2", role_prompt="r", expect_output="e")
    sub2 = agent._build_sub_agent(spec2)
    assert [t.name for t in sub2.agent_config.tools] == ["天气工具", "搜索工具"], \
        "required_tools 为空时应使用全量工具池"


def test_plan_prompt_lists_available_tools(monkeypatch):
    """规划提示词列出可用工具名（供 required_tools 选取）"""
    captured = {}

    class PlanRecordingLLM(FakeOrchestratorLLM):
        def with_structured_output(self, schema, **kwargs):
            subtasks = self._subtasks

            class FakePlanner:
                def invoke(self, messages):
                    captured["plan_input"] = messages
                    return SubTaskPlan(subtasks=subtasks or [])
            return FakePlanner()

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    tools = [FakeTool(name="天气工具"), FakeTool(name="搜索工具")]
    agent = OrchestratorAgent(
        name="orch", llm=PlanRecordingLLM(subtasks=[]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=tools,
            orchestrator_config={},
        ),
    )
    list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [], "query": "写报告",
    }))
    system_prompt = captured["plan_input"][0].content
    assert "天气工具" in system_prompt and "搜索工具" in system_prompt, system_prompt
