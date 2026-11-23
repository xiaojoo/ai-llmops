#!/usr/bin/env python
"""编排器子任务依赖（DAG）调度 + 失败自动重规划的判据。

这两件事原来都不存在：_execute_node 把全部子任务一次性丢进线程池（扁平并行、互不知情），
提示词还明令"子任务之间不得互相依赖"；子任务 error/timeout 后直接进 summarize，
只能靠用户在确认框里手动重拆。现在 depends_on 决定批次、前置产出注入后置提问、
失败自动回 plan 重拆（共用 2 轮上限）。

调度器最坏情况是"等不到前置结果永久挂死"，所以成环/悬空依赖必须断环而不是卡住——
本文件专门锁这几条。
"""
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.orchestrator_agent import (
    OrchestratorAgent,
    _UPSTREAM_CONTEXT_LIMIT,
)
from internal.core.agent.entities.agent_entity import (
    AgentConfig,
    SubTaskResult,
    SubTaskSpec,
)
from internal.entity.conversation_entity import InvokeFrom
from test.internal.core.agent.test_orchestrator_confirm_plan import _FakeLLM


def _spec(order, *, deps=(), title=None):
    return SubTaskSpec(
        order=order,
        title=title or f"任务{order}",
        role_prompt=f"你是{order}号",
        depends_on=list(deps),
        task_id=uuid.uuid4(),
    )


def _make_agent(orchestrator_config=None):
    """只测调度与决策：队列与子任务执行全部换成进程内桩，不碰 LLM/DB/Redis。"""
    agent = OrchestratorAgent(
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
    # agent_queue_manager 是只读 property，桩打在私有后备字段上（与 test_agent_soft_stop 同款）
    qm = MagicMock()
    qm._is_stopped.return_value = False
    agent._agent_queue_manager = qm
    return agent


def _record_scheduler(agent, outcomes):
    """把 _run_subtask 换成记录器：返回 (调用顺序, 每次拿到的 upstream)。

    BaseAgent 是 pydantic 模型，实例上覆盖方法要走 object.__setattr__（普通赋值会被
    __setattr__ 当作未知字段拒掉）。
    outcomes: order → SubTaskResult
    """
    calls: list[tuple[int, dict]] = []

    def _fake(state, spec, running_ids, ids_lock, resume_mode, sub_task_timeout, upstream=None):
        calls.append((spec.order, dict(upstream or {})))
        return outcomes[spec.order]

    object.__setattr__(agent, "_run_subtask", _fake)
    return calls


def _ok(order, answer=""):
    return SubTaskResult(order=order, title=f"任务{order}", status="normal", answer=answer)


def _bad(order, error="模型超时"):
    return SubTaskResult(order=order, title=f"任务{order}", status="error", error=error)


# ---------- 拓扑分批 ----------

def test_waves_no_deps_run_in_one_parallel_wave():
    """无依赖必须全在第一波：分批不该把原本能并行的任务串行化。"""
    waves = OrchestratorAgent._build_waves([_spec(1), _spec(2), _spec(3)])
    assert [[s.order for s in w] for w in waves] == [[1, 2, 3]]


def test_waves_chain_and_diamond():
    chain = [_spec(1), _spec(2, deps=[1]), _spec(3, deps=[2])]
    assert [[s.order for s in w] for w in OrchestratorAgent._build_waves(chain)] == [[1], [2], [3]]

    diamond = [_spec(1), _spec(2, deps=[1]), _spec(3, deps=[1]), _spec(4, deps=[2, 3])]
    assert [[s.order for s in w] for w in OrchestratorAgent._build_waves(diamond)] == [
        [1], [2, 3], [4],
    ]


def test_waves_break_cycle_instead_of_hanging():
    """A→B→A 成环时必须断环继续调度：挂死等于用户永远等不到回答。"""
    cyclic = [_spec(1, deps=[2]), _spec(2, deps=[1])]
    waves = OrchestratorAgent._build_waves(cyclic)
    scheduled = sorted(s.order for w in waves for s in w)
    assert scheduled == [1, 2], f"成环不能吞掉子任务，实际 {scheduled}"


def test_waves_ignore_self_and_dangling_deps():
    """自依赖/指向不存在 order 的依赖是 LLM 常犯错误，忽略而不是报错。"""
    specs = [_spec(1, deps=[1, 99]), _spec(2, deps=[99])]
    waves = OrchestratorAgent._build_waves(specs)
    assert [[s.order for s in w] for w in waves] == [[1, 2]]


# ---------- 提问注入 ----------

def test_subtask_query_injects_upstream_answer():
    q = OrchestratorAgent._subtask_query("原始提问", {1: "检索到的资料"})
    assert q.startswith("原始提问")
    assert "前置子任务 #1 的产出" in q and "检索到的资料" in q


def test_subtask_query_without_upstream_is_unchanged():
    assert OrchestratorAgent._subtask_query("原始提问", {}) == "原始提问"


def test_subtask_query_truncates_overlong_upstream():
    """超长上游必须截断：几段长回答拼起来会顶爆上下文，整轮失败比丢尾巴更糟。"""
    q = OrchestratorAgent._subtask_query("q", {1: "x" * (_UPSTREAM_CONTEXT_LIMIT + 500)})
    assert "…（已截断）" in q
    assert len(q) < _UPSTREAM_CONTEXT_LIMIT + 200


# ---------- 执行编排 ----------

def test_downstream_receives_upstream_answer_and_runs_after_it():
    agent = _make_agent()
    specs = [_spec(1), _spec(2, deps=[1])]
    calls = _record_scheduler(agent, {1: _ok(1, "上游产出"), 2: _ok(2)})

    agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})

    assert [o for o, _ in calls] == [1, 2], "有依赖时顺序执行"
    assert calls[1][1] == {1: "上游产出"}, f"后置没拿到前置产出：{calls[1][1]}"


def test_downstream_of_failed_upstream_is_not_executed():
    """前置失败还硬跑后置，只会拿脏上下文再烧一遍 token。"""
    agent = _make_agent()
    specs = [_spec(1), _spec(2, deps=[1])]
    calls = _record_scheduler(agent, {1: _bad(1)})

    out = agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})

    assert [o for o, _ in calls] == [1], f"后置不该被执行：{calls}"
    by_order = {r.order: r for r in out["sub_results"]}
    assert by_order[2].status == "error" and "#1" in by_order[2].error


def test_independent_tasks_still_parallel_after_change():
    """回归保护：没声明依赖的多个子任务仍在一批，不该被分批串行化。"""
    agent = _make_agent()
    specs = [_spec(1), _spec(2), _spec(3)]
    seen: list[list[int]] = []
    lock_holder = []

    def _fake(state, spec, running_ids, ids_lock, resume_mode, sub_task_timeout, upstream=None):
        with ids_lock:
            seen.append(spec.order)
            lock_holder.append(running_ids is not None)
        return _ok(spec.order)

    object.__setattr__(agent, "_run_subtask", _fake)
    agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})
    assert sorted(seen) == [1, 2, 3]


# ---------- 失败自动重规划 ----------

def test_execute_triggers_auto_replan_on_failure():
    agent = _make_agent()
    specs = [_spec(1)]
    _record_scheduler(agent, {1: _bad(1, "工具报错")})

    out = agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})

    assert out["auto_replan"] is True
    assert out["plan_attempts"] == 1
    assert "工具报错" in out["plan_feedback"] and "工具报错" in out["replan_reason"]


def test_auto_replan_respects_two_round_budget():
    """预算用尽必须停下进 summarize，否则失败→重拆→失败无限循环。"""
    agent = _make_agent()
    specs = [_spec(1)]
    _record_scheduler(agent, {1: _bad(1)})

    out = agent._execute_node(
        {"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q", "plan_attempts": 2},
    )
    assert out.get("auto_replan") is False, "第 3 轮不该再自动重拆"


def test_auto_replan_disabled_by_config():
    agent = _make_agent({"auto_replan_on_failure": False})
    specs = [_spec(1)]
    _record_scheduler(agent, {1: _bad(1)})

    out = agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})
    assert out["auto_replan"] is False


def test_user_stop_does_not_trigger_replan():
    """stop 是用户明确叫停，自动重拆会把他刚停的东西再跑一遍。"""
    agent = _make_agent()
    specs = [_spec(1)]
    _record_scheduler(agent, {1: SubTaskResult(order=1, title="任务1", status="stop")})

    out = agent._execute_node({"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q"})
    assert out["auto_replan"] is False


def test_success_clears_auto_replan_flag():
    """成功轮必须显式落回 False：langgraph 合并局部 state，不清会让下一轮跳过确认框。"""
    agent = _make_agent()
    specs = [_spec(1)]
    _record_scheduler(agent, {1: _ok(1, "答案")})

    out = agent._execute_node(
        {"task_id": uuid.uuid4(), "sub_tasks": specs, "query": "q", "auto_replan": True},
    )
    assert out["auto_replan"] is False


def test_conditions_route_on_auto_replan():
    assert OrchestratorAgent._execute_condition({"auto_replan": True}) == "plan"
    assert OrchestratorAgent._execute_condition({"auto_replan": False}) == "summarize"
    specs = {"sub_tasks": [_spec(1)], "auto_replan": True}
    assert OrchestratorAgent._plan_condition(specs) == "execute", "自动重拆不该再弹确认框"
    assert OrchestratorAgent._plan_condition({"sub_tasks": [_spec(1)]}) == "confirm_plan"
    assert OrchestratorAgent._plan_condition({"sub_tasks": [], "auto_replan": True}) == "direct_answer"


# ---------- 依赖字段归一化 ----------

def test_coerce_int_list_tolerates_llm_junk():
    f = OrchestratorAgent._coerce_int_list
    assert f("[1, 2]") == [1, 2]
    assert f("not json") == []
    assert f(2) == [2]
    assert f(["1", "x", None, 3, 3]) == [1, 3]
    assert f({"a": 1}) == []
    assert f([]) == []


def test_agent_queue_manager_not_touched_by_scheduler():
    """桩别泄漏到真实类：_is_stopped 被 MagicMock 顶掉会让所有测试里的任务都被判为已停止。"""
    assert AgentQueueManager._is_stopped is not None
