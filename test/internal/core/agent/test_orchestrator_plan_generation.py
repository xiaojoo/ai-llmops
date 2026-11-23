#!/usr/bin/env python
"""编排器计划代际（plan generation）测试：断点代际失效 + plan_id 落库

背景（OrchestratorAgent 新语义）：
- _plan_node 每次产出新计划都生成新 plan_id（replan/regenerate 重拆即新代际）；
- _execute_node 在 conversation_id 存在且 (plan_attempts>0 或 regenerate) 时，先用 worker_run
  清空该会话旧断点（代际失效），防"重拆后错误复用上一代计划的 complete 缓存"；
- _run_subtask_inner 各 save_checkpoint 落盘带 plan_id=state.get("plan_id")。

本文件基于真实 PG（worker_run + 独立 engine，uuid 隔离），参照 test_orchestrator_resume.py
的 _run_worker 模式；事件经 StubQueueManager 进程内收集。
"""
import asyncio
import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from internal.core.agent.agents import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig, SubTaskSpec
from internal.core.agent.entities.queue_entity import QueueEvent as QE
from internal.entity.conversation_entity import InvokeFrom
from package.database import build_engine, worker_run

# 图级测试统一把阻塞在 Redis 的 wait_for_plan_choice 替换为"确认全量"
# （真实实现 blpop 300s 挂起测试；见 test_orchestrator_resume.py 顶部注释）


@pytest.fixture(autouse=True)
def _mock_confirm_waits(monkeypatch):
    monkeypatch.setattr(
        "internal.core.agent.agents.agent_queue_manager.AgentQueueManager.wait_for_plan_choice",
        MagicMock(return_value=("confirm", [], "", False)),
    )


async def _run_worker(coro_factory, *, commit: bool = True):
    """在 to_thread 线程执行 worker_run（独立 engine，真实提交/查询）"""
    return await asyncio.to_thread(
        lambda: worker_run(coro_factory, commit_on_success=commit, engine_factory=build_engine)
    )


def _get_checkpoint(conv_id, position=1):
    def _get(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.get_checkpoint(conv_id, position)
    return _get


def _save_complete_checkpoint(conv_id, spec, *, answer="旧计划答案", plan_id=None):
    """预置一个 complete 断点（query 与 agent 输入一致，模拟上一代计划落下的结果缓存）

    断点的定位键是 message_id（见 sub_task_service.get_checkpoint / clear_checkpoints），
    这里与会话 id 取同一个值，助手就只需要一把键。
    """
    def _save(session):
        from internal.container import create_sub_task_service
        svc = create_sub_task_service(session)
        return svc.save_checkpoint(
            app_id=uuid.uuid4(), conversation_id=conv_id, message_id=conv_id,
            position=1, query="写报告", spec=spec, status="complete",
            messages=[{"type": "human", "data": {"content": "写报告"}}],
            iteration_count=1, partial_answer=answer, plan_id=plan_id,
        )
    return _save


def _make_spec(order: int = 1) -> SubTaskSpec:
    return SubTaskSpec(order=order, title="调研", role_prompt="调研员", expect_output="结论")


def _make_agent(monkeypatch, llm, *, resume_mode="auto"):
    from test.internal.core.agent.test_orchestrator_agent import StubQueueManager
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    return OrchestratorAgent(
        name="orch",
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": resume_mode},
        ),
    )


# ---------------------------------------------------------------------------
# 6) 断点代际失效：重拆（plan_attempts=1）后旧 complete 断点必须被清空并重新执行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_node_replan_generation_invalidates_old_complete_checkpoint(monkeypatch):
    """plan_attempts>0（模拟 replan 后进入 execute）→ 代际失效：清旧 complete 断点并全新执行

    - 预置 complete 断点 partial_answer="旧计划答案"（同 query 同 order 的上一代结果缓存）；
    - execute 节点开头按代际清断点 → 子任务重新执行（发布 SUB_TASK_START，而非缓存复用）；
    - 完成后再落盘的新断点携带本代 plan_id，且 partial_answer 不再是旧计划答案。
    """
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM

    conv_id = uuid.uuid4()
    spec = _make_spec()
    old_plan_id = uuid.uuid4()
    await _run_worker(_save_complete_checkpoint(conv_id, spec, plan_id=old_plan_id))
    pre = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert pre is not None and pre.status == "complete" and pre.partial_answer == "旧计划答案"

    agent = _make_agent(monkeypatch, FakeOrchestratorLLM(subtasks=[spec]))

    # 模拟 replan 后的 execute 状态：新代际 plan_id + plan_attempts=1 + conversation_id
    new_plan_id = uuid.uuid4()
    state = {
        "messages": [HumanMessage(content="写报告")],
        "history": [],
        "query": "写报告",
        "conversation_id": conv_id,
        "app_id": uuid.uuid4(),
        "message_id": conv_id,
        "task_id": uuid.uuid4(),
        "iteration_count": 0,
        "sub_tasks": [spec],
        "plan_id": new_plan_id,
        "plan_attempts": 1,
        "regenerate": False,
    }
    result = await asyncio.to_thread(lambda: agent._execute_node(state))

    # b) 确实重新执行而非复用缓存：事件流出现 SUB_TASK_START
    kinds = [e.event for e in agent.agent_queue_manager.events]
    assert kinds.count(QE.SUB_TASK_START) == 1, \
        f"代际失效后子任务应重新执行（发布 SUB_TASK_START），实际事件: {kinds}"
    sub_results = result["sub_results"]
    assert len(sub_results) == 1 and sub_results[0].status == "normal"

    # a) 旧 complete 断点被覆盖为新代际的 complete，partial_answer 不是旧计划答案
    ck = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert ck is not None and ck.status == "complete"
    assert ck.partial_answer != "旧计划答案", "代际失效后断点答案应来自重新执行而非旧缓存"
    assert ck.plan_id == new_plan_id, "新落库断点应携带本代 plan_id（代际失效后）"
    assert sub_results[0].answer == ck.partial_answer, "断点答案应与本次执行结果一致"


@pytest.mark.asyncio
async def test_stream_replan_generation_invalidates_old_complete_checkpoint(monkeypatch):
    """（全图 stream 版）plan_attempts=1 输入 + 预置旧 complete 断点 → 清断点并重新执行

    plan_attempts/regenerate 已声明在 AgentState（agent_entity.py），langgraph 输入映射不再丢弃，
    全图可携带 replan 语义；execute 节点代际失效分支在真实图运行中可达。
    """
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM

    conv_id = uuid.uuid4()
    spec = _make_spec()
    await _run_worker(_save_complete_checkpoint(conv_id, spec))
    agent = _make_agent(monkeypatch, FakeOrchestratorLLM(subtasks=[spec]))
    events = await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "message_id": conv_id,
        "query": "写报告", "resume_trigger": False,
        "plan_attempts": 1,
    })))
    kinds = [e.event for e in events]
    assert kinds.count(QE.SUB_TASK_START) == 1, f"代际失效后应重新执行，实际: {kinds}"
    ck = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert ck is not None and ck.partial_answer != "旧计划答案"


# ---------------------------------------------------------------------------
# 7) run（全新执行，plan_attempts=0）落库的断点携带 plan_id（非空）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_execution_persists_checkpoint_with_plan_id(monkeypatch):
    """全新执行（plan_attempts=0，普通 resume 语义不清断点）完成后，新落库断点 plan_id 非空

    验证 _run_subtask_inner 各 save_checkpoint 落盘带 plan_id=state.get("plan_id") 的联动：
    plan 节点每次产出新计划生成 plan_id，执行完成写入断点后该代际标识随行落库。
    """
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM

    conv_id = uuid.uuid4()
    spec = _make_spec()
    agent = _make_agent(monkeypatch, FakeOrchestratorLLM(subtasks=[spec]))

    events = await asyncio.to_thread(lambda: list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "message_id": conv_id,
        "query": "写报告", "resume_trigger": False,
    })))
    kinds = [e.event for e in events]
    assert kinds.count(QE.SUB_TASK_START) == 1  # 无断点 → 全新执行
    assert kinds.count(QE.AGENT_END) == 1

    ck = await _run_worker(_get_checkpoint(conv_id), commit=False)
    assert ck is not None and ck.status == "complete", f"全新执行应落 complete 断点，实际: {ck}"
    assert ck.plan_id is not None, "新落库断点 plan_id 应为非空（本代计划标识）"
