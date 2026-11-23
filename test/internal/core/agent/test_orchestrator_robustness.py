#!/usr/bin/env python
"""编排器 plan 节点健壮性测试：LLM 结构化输出不稳定时的降级与归一化（E2E 验证发现的生产缺陷）"""
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from pydantic import ConfigDict, ValidationError

from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig, ConfirmVerdict, SubTaskPlan, SubTaskSpec
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


@pytest.fixture(autouse=True)
def _mock_confirm_waits(monkeypatch):
    """图级测试聚焦 plan 健壮性/停止竞态：确认节点真实执行，但把阻塞在 Redis 的
    wait_for_plan_choice 替换为"确认全量"（真实实现会 blpop 300s 挂起测试）"""
    monkeypatch.setattr(
        "internal.core.agent.agents.agent_queue_manager.AgentQueueManager.wait_for_plan_choice",
        MagicMock(return_value=("confirm", [], "", False)),
    )


class FakeOrchestratorLLM(BaseLanguageModel):
    """假 LLM：可配置 with_structured_output 行为（正常/先抛后成/字符串化字段）"""
    model_config = ConfigDict(extra="allow")

    def __init__(self, *, subtasks=None, fail_times=0, raw_dicts=False, features=None, plan_error=None, **kwargs):
        super().__init__(**kwargs)
        self._subtasks = subtasks
        self._fail_times = fail_times
        self._calls = 0
        self._raw_dicts = raw_dicts
        self._plan_error = plan_error
        self.features = features or [ModelFeature.TOOL_CALL]

    def with_structured_output(self, schema, **kwargs):
        if schema is ConfirmVerdict:
            # 确认点2（confirm_result 节点）：图级测试统一无歧义 → 直接 END
            class FakeVerdictPlanner:
                def invoke(self, messages):
                    return SimpleNamespace(need_confirm=False, reason="")
            return FakeVerdictPlanner()

        class FakePlanner:
            def __init__(self, outer):
                self._outer = outer

            def invoke(self, messages):
                self._outer._calls += 1
                if self._outer._plan_error is not None:
                    raise self._outer._plan_error
                if self._outer._calls <= self._outer._fail_times:
                    raise ValidationError.from_exception_data(
                        "SubTaskPlan", [{"type": "missing", "loc": ("subtasks", 0, "order"), "input": {}}]
                    )
                if self._outer._raw_dicts:
                    return {"subtasks": self._outer._subtasks or []}
                return SubTaskPlan(subtasks=self._outer._subtasks or [])
        return FakePlanner(self)

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
        deadline = time.time() + 20
        while time.time() < deadline:
            if self._done.is_set():
                yield from self.events
                return
            time.sleep(0.01)
        raise AssertionError("编排器图 20s 内未完成推理")

    def _is_stopped(self, task_id):
        return False


def _run(monkeypatch, llm):
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="robust",
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 2, "resume_mode": "auto"},
        ),
    )
    return list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [], "query": "写报告",
    }))


def test_plan_node_retries_then_decomposes(monkeypatch):
    """解析失败一次后重试成功 → 正常分解（修复：此前 ValidationError 直接炸掉 plan 节点）"""
    spec = SubTaskSpec(order=1, title="调研", role_prompt="你是调研员", expect_output="结论")
    events = _run(monkeypatch, FakeOrchestratorLLM(subtasks=[spec], fail_times=1))
    kinds = [e.event for e in events]
    assert kinds.count(QueueEvent.SUB_TASK_START) == 1
    assert kinds.count(QueueEvent.AGENT_END) == 1


def test_plan_node_degrades_to_direct_answer_when_parse_always_fails(monkeypatch):
    """解析持续失败 → 退化为直接回答（不挂起、不崩溃）"""
    events = _run(monkeypatch, FakeOrchestratorLLM(subtasks=[], fail_times=2))
    kinds = [e.event for e in events]
    assert QueueEvent.SUB_TASK_START not in kinds
    assert kinds.count(QueueEvent.AGENT_END) == 1


def test_plan_node_surfaces_length_error_when_parse_always_fails(monkeypatch):
    """上下文/输出超长错误：不再静默降级为直接回答，而是透传 ERROR 事件给前端。

    修复：此前 plan 节点 catch 住 LengthFinishReasonError 后静默降级，
    前端收不到任何事件、任务莫名停止；现按不可恢复错误抛出，由基类透传。
    """
    length_err = RuntimeError("Could not parse response content as the length limit was reached")
    events = _run(monkeypatch, FakeOrchestratorLLM(subtasks=[], plan_error=length_err))
    kinds = [e.event for e in events]
    assert QueueEvent.ERROR in kinds
    # 不应退化为直接回答
    assert QueueEvent.SUB_TASK_START not in kinds
    err = [e for e in events if e.event == QueueEvent.ERROR][0]
    assert err.observation
    assert ("上下文" in err.observation) or ("输出" in err.observation)


def test_plan_node_normalizes_stringified_and_missing_fields(monkeypatch):
    """LLM 字符串化数组/缺失 order → 归一化后正常执行（修复：required_tools='[]' 曾触发 ValidationError）"""
    spec = SubTaskSpec(title="调研", role_prompt="你是调研员", expect_output="结论", required_tools="[]")
    events = _run(monkeypatch, FakeOrchestratorLLM(subtasks=[spec]))
    starts = [e for e in events if e.event == QueueEvent.SUB_TASK_START]
    assert len(starts) == 1
    # SUB_TASK_PLAN 的 thought 中 order 已被补全为 1、required_tools 已归一化为列表
    plan_events = [e for e in events if e.event == QueueEvent.SUB_TASK_PLAN]
    assert plan_events
    import json
    plan = json.loads(plan_events[0].thought)
    assert plan[0]["order"] == 1
    assert plan[0]["required_tools"] == []


def test_sub_task_spec_accepts_lenient_types():
    """SubTaskSpec 宽松解析：缺 order、字符串化 required_tools 不抛错（交给 _plan_node 归一化）"""
    spec = SubTaskSpec(title="t", role_prompt="r", required_tools="[]")
    assert spec.order is None
    assert spec.required_tools == "[]"
    spec2 = SubTaskSpec(title="t", role_prompt="r")
    assert spec2.required_tools == []


def test_monitor_flags_late_registered_subtasks(monkeypatch):
    """停止竞态回归：max_parallel=1 顺序执行时，停止落地后迟注册的子任务也必须被标记停止。

    旧实现监控线程在传播一次后立即 return，只有首个轮询瞬间已注册的子任务能收到停止标志；
    新实现持续轮询至 execution_done，保证全部子任务（含迟到者）都被标记。
    """
    ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    specs = [
        SubTaskSpec(order=1, title="甲", role_prompt="角色甲", expect_output="e", task_id=ids[0]),
        SubTaskSpec(order=2, title="乙", role_prompt="角色乙", expect_output="e", task_id=ids[1]),
        SubTaskSpec(order=3, title="丙", role_prompt="角色丙", expect_output="e", task_id=ids[2]),
    ]

    class SlowLLM(FakeOrchestratorLLM):
        def stream(self, messages):
            time.sleep(0.5)  # 拉长子任务执行时长，制造"迟注册"窗口
            yield from super().stream(messages)

    class StoppedMainQueueManager(StubQueueManager):
        """仅主任务视为已停止：子任务正常跑完，从而产生迟注册的时序窗口"""
        def __init__(self, user_id=None, invoke_from=None, model_name=""):
            super().__init__(user_id=user_id, invoke_from=invoke_from, model_name=model_name)
            self.main_id = None

        def publish(self, task_id, thought):
            if thought.event == QueueEvent.SUB_TASK_PLAN:
                self.main_id = task_id  # 编排器发布 plan 事件时记录主任务 id
            super().publish(task_id, thought)

        def _is_stopped(self, task_id):
            return self.main_id is not None and task_id == self.main_id

    recorded = []

    def fake_set_stop_flag(task_id, invoke_from, user_id):
        recorded.append(task_id)

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StoppedMainQueueManager)
    monkeypatch.setattr("internal.core.agent.agents.orchestrator_agent.AgentQueueManager.set_stop_flag", fake_set_stop_flag)

    agent = OrchestratorAgent(
        name="race",
        llm=SlowLLM(subtasks=specs),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    list(agent.stream({"messages": [HumanMessage(content="写报告")], "history": [], "query": "写报告"}))
    # 全部三个子任务（含迟注册的）都必须被标记停止
    assert set(recorded) == set(ids), f"迟注册子任务未被标记停止: 记录={set(map(str, recorded))} 期望={set(map(str, ids))}"
