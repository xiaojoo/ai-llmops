#!/usr/bin/env python
"""编排引擎选择 + 预算护栏（GuardedOrchestratorAgent）的判据。

引擎选择是"系统设置里配第三方编排"这条需求的落点：应用配置优先、全局默认兜底、
配错要回落但不能静默。预算护栏是 google/ax 那条 "can burn money in a loop if nobody is
watching" 的单机移植，判据重点是：熔断发生在**批次边界**，已启动的子任务不被腰斩，
且熔断不触发失败自动重规划（重拆只会继续烧预算）。
"""
import uuid

import pytest
from unittest.mock import MagicMock

from internal.core.agent.agents.guarded_orchestrator_agent import GuardedOrchestratorAgent
from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import (
    AgentConfig,
    SubTaskResult,
    SubTaskSpec,
)
from internal.entity.conversation_entity import InvokeFrom
from internal.service.chat_runner import _resolve_orchestrator_class
from test.internal.core.agent.test_orchestrator_confirm_plan import _FakeLLM

_ENV_KEYS = [
    "ORCHESTRATOR_ENGINE",
    "ORCHESTRATOR_BUDGET_MAX_TOKENS",
    "ORCHESTRATOR_BUDGET_MAX_PRICE",
    "ORCHESTRATOR_BUDGET_MAX_SECONDS",
    "ORCHESTRATOR_BUDGET_MAX_SUBTASKS",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def _make(cls=OrchestratorAgent, orchestrator_config=None):
    agent = cls(
        name="t-orch",
        llm=_FakeLLM(features=[]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(),
            invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="",
            enable_long_term_memory=False,
            tools=[],
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config=dict(orchestrator_config or {}),
        ),
    )
    qm = MagicMock()
    qm._is_stopped.return_value = False
    agent._agent_queue_manager = qm
    return agent


def _spec(order, *, deps=()):
    return SubTaskSpec(
        order=order, title=f"任务{order}", role_prompt=f"你是{order}号",
        depends_on=list(deps), task_id=uuid.uuid4(),
    )


def _res(order, *, tokens=0, price=0.0, status="normal"):
    return SubTaskResult(
        order=order, title=f"任务{order}", status=status,
        total_token_count=tokens, total_price=price,
    )


# ---------- 引擎选择 ----------

def test_default_engine_is_the_original_orchestrator():
    """没配任何东西必须还是原引擎：默认路径行为不能因为加了开关而改变。"""
    assert _resolve_orchestrator_class({}) is OrchestratorAgent


def test_app_config_selects_guarded():
    assert _resolve_orchestrator_class({"engine": "guarded"}) is GuardedOrchestratorAgent


def test_engine_value_is_case_and_space_tolerant():
    assert _resolve_orchestrator_class({"engine": " Guarded "}) is GuardedOrchestratorAgent


def test_unknown_engine_falls_back_but_logs(monkeypatch):
    """配错不能让整轮对话失败，但也不能静默——否则用户以为开着护栏。"""
    warns = []
    monkeypatch.setattr(
        "internal.service.chat_runner.logger.warning", lambda msg, *a: warns.append(msg % a),
    )
    assert _resolve_orchestrator_class({"engine": "ax"}) is OrchestratorAgent
    assert warns and "ax" in warns[0]


def test_system_setting_provides_global_default(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_ENGINE", "guarded")
    assert _resolve_orchestrator_class({}) is GuardedOrchestratorAgent


def test_app_config_overrides_system_setting(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_ENGINE", "guarded")
    assert _resolve_orchestrator_class({"engine": "subtask"}) is OrchestratorAgent


# ---------- 预算闸门 ----------

def test_no_budget_configured_never_trips():
    """一项都没配就放行：忘了配预算不该把用户的任务全停掉。"""
    agent = _make(GuardedOrchestratorAgent)
    assert agent._budget_allows({}, {1: _res(1, tokens=999999)}, elapsed=9999) == (True, "")


def test_token_cap_trips_at_boundary():
    agent = _make(GuardedOrchestratorAgent, {"budget": {"max_total_tokens": 1000}})
    assert agent._budget_allows({}, {1: _res(1, tokens=400)})[0] is True
    allowed, why = agent._budget_allows({}, {1: _res(1, tokens=600), 2: _res(2, tokens=500)})
    assert allowed is False and "1100" in why and "1000" in why


def test_price_cap_trips():
    agent = _make(GuardedOrchestratorAgent, {"budget": {"max_total_price": 0.5}})
    assert agent._budget_allows({}, {1: _res(1, price=0.2)})[0] is True
    assert agent._budget_allows({}, {1: _res(1, price=0.6)})[0] is False


def test_wall_clock_cap_trips():
    agent = _make(GuardedOrchestratorAgent, {"budget": {"max_wall_clock_seconds": 60}})
    assert agent._budget_allows({}, {}, elapsed=30)[0] is True
    allowed, why = agent._budget_allows({}, {}, elapsed=61)
    assert allowed is False and "61" in why


def test_sub_task_count_cap_trips():
    agent = _make(GuardedOrchestratorAgent, {"budget": {"max_dispatched_sub_tasks": 2}})
    assert agent._budget_allows({}, {1: _res(1)})[0] is True
    assert agent._budget_allows({}, {1: _res(1), 2: _res(2)})[0] is False


def test_budget_reads_system_setting(monkeypatch):
    """全局选了 guarded 却每个应用都不配预算 = 没有护栏，所以预算也能只在系统设置配。"""
    monkeypatch.setenv("ORCHESTRATOR_BUDGET_MAX_TOKENS", "100")
    agent = _make(GuardedOrchestratorAgent)
    assert agent._budget_allows({}, {1: _res(1, tokens=150)})[0] is False


def test_app_budget_overrides_system_setting(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_BUDGET_MAX_TOKENS", "100")
    agent = _make(GuardedOrchestratorAgent, {"budget": {"max_total_tokens": 5000}})
    assert agent._budget_allows({}, {1: _res(1, tokens=150)})[0] is True


def test_invalid_budget_value_does_not_stop_everything(monkeypatch):
    """脏值按"该项不限"处理并告警，不能抛异常把整轮任务打死。"""
    monkeypatch.setenv("ORCHESTRATOR_BUDGET_MAX_TOKENS", "abc")
    agent = _make(GuardedOrchestratorAgent)
    assert agent._budget_allows({}, {1: _res(1, tokens=10)})[0] is True


def test_base_engine_has_no_budget_gate():
    """默认引擎不受预算配置影响：只覆写钩子，配置里残留 budget 也不该限流。"""
    agent = _make(OrchestratorAgent, {"budget": {"max_total_tokens": 1}})
    assert agent._budget_allows({}, {1: _res(1, tokens=999)}) == (True, "")


# ---------- 熔断发生在执行链路里 ----------

def test_budget_trip_skips_remaining_waves_without_replanning():
    """批间断开：已跑的那批保留结果，没派发的标熔断失败，且不触发自动重拆。"""
    agent = _make(GuardedOrchestratorAgent, {"budget": {"max_total_tokens": 50}})
    calls = []

    def _fake(state, spec, running_ids, ids_lock, resume_mode, sub_task_timeout, upstream=None):
        calls.append(spec.order)
        return _res(spec.order, tokens=80)

    object.__setattr__(agent, "_run_subtask", _fake)
    specs = [_spec(1), _spec(2, deps=[1]), _spec(3, deps=[2])]

    out = agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})

    assert calls == [1], f"预算熔断后不该继续派发，实际跑了 {calls}"
    assert out["budget_exhausted"] is True
    assert out["auto_replan"] is False, "熔断造成的失败再重拆只会继续烧预算"
    by_order = {r.order: r for r in out["sub_results"]}
    assert by_order[1].status == "normal"
    assert by_order[2].status == "error" and "预算熔断" in by_order[2].error
    assert 3 not in by_order, "被熔断的子任务不该出现两次判定结果"
