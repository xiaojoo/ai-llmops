import uuid
from unittest.mock import MagicMock

from pydantic import ConfigDict

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class _FakeLLM(BaseLanguageModel):
    """可被 pydantic 校验的假 LLM（_confirm_plan_node 不调用 LLM，仅需合法实例，与既有 ask_user 测试同款）"""
    model_config = ConfigDict(extra="allow")

    def stream(self, messages):
        raise NotImplementedError

    def get_num_tokens_safe(self, messages):
        return 10

    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


def _make_agent(monkeypatch, wait_result=("confirm", [1, 3], "", False)):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_plan_choice", MagicMock(return_value=wait_result),
    )
    agent = OrchestratorAgent(
        name="test-orch",
        llm=_FakeLLM(features=[ModelFeature.TOOL_CALL]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(),
            invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="",
            enable_long_term_memory=False,
            tools=[],
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config={},
        ),
    )
    # 实例 publish 替换为 mock（断言发布内容用）；AgentQueueManager 依赖 injector 拿 Redis，
    # 但 __init__ 惰性构造不连库（与既有 ask_user 测试同款处理）
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    return agent


def _specs():
    from internal.core.agent.entities.agent_entity import SubTaskSpec
    return [
        SubTaskSpec(order=1, title="检索资料", role_prompt="你是检索专家"),
        SubTaskSpec(order=2, title="撰写报告", role_prompt="你是报告专家"),
        SubTaskSpec(order=3, title="复核", role_prompt="你是复核专家"),
    ]


def test_confirm_plan_publishes_ask_user_with_sub_task_options(monkeypatch):
    agent = _make_agent(monkeypatch)
    task_id = uuid.uuid4()
    state = {"task_id": task_id, "sub_tasks": _specs(), "messages": []}
    result = agent._confirm_plan_node(state)
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.ASK_USER
    assert published.sub_task_options == [
        {"order": 1, "title": "检索资料", "role_prompt": "你是检索专家", "expect_output": "", "required_tools": [], "depends_on": []},
        {"order": 2, "title": "撰写报告", "role_prompt": "你是报告专家", "expect_output": "", "required_tools": [], "depends_on": []},
        {"order": 3, "title": "复核", "role_prompt": "你是复核专家", "expect_output": "", "required_tools": [], "depends_on": []},
    ]
    assert [o for o in published.options] == ["检索资料", "撰写报告", "复核"]
    # confirm [1,3] → 保留 order 1,3
    assert [s.order for s in result["sub_tasks"]] == [1, 3]


def test_confirm_plan_no_subtasks_skips(monkeypatch):
    agent = _make_agent(monkeypatch)
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": [], "messages": []})
    agent.agent_queue_manager.publish.assert_not_called()
    assert result["sub_tasks"] == []


def test_confirm_plan_replan(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=("replan", [], "第二个子任务改用ABAC", False))
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert result["plan_feedback"] == "第二个子任务改用ABAC"
    assert result["sub_tasks"] == []


def test_confirm_plan_replan_increments_plan_attempts(monkeypatch):
    """replan 递增 plan_attempts（_replan_condition 的 2 轮上限依赖此计数）"""
    # 无既有计数：从 0 → 1
    agent = _make_agent(monkeypatch, wait_result=("replan", [], "改方案", False))
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert result["plan_attempts"] == 1
    # 已有计数：1 → 2
    agent2 = _make_agent(monkeypatch, wait_result=("replan", [], "再改", False))
    result2 = agent2._confirm_plan_node(
        {"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": [], "plan_attempts": 1},
    )
    assert result2["plan_attempts"] == 2
    # 确认（无 custom）/超时分支不递增（无 plan_attempts 键；custom 非空会走 replan 分支）
    agent3 = _make_agent(monkeypatch, wait_result=("confirm", [], "", False))
    result3 = agent3._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert "plan_attempts" not in result3
    agent4 = _make_agent(monkeypatch, wait_result=("confirm", [], "", True))
    result4 = agent4._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert "plan_attempts" not in result4


def test_confirm_plan_timeout_keeps_all(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=("confirm", [], "", True))
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert [s.order for s in result["sub_tasks"]] == [1, 2, 3]


def test_confirm_plan_clears_plan_feedback_on_confirm(monkeypatch):
    """确认分支清除 plan_feedback，否则 _replan_condition 见 feedback 恒回 plan 死循环"""
    agent = _make_agent(monkeypatch, wait_result=("confirm", [1, 2], "", False))
    result = agent._confirm_plan_node({
        "task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": [],
        "plan_feedback": "上轮补充要求",
    })
    assert result["plan_feedback"] == ""
    assert [s.order for s in result["sub_tasks"]] == [1, 2]


def test_confirm_plan_timeout_clears_plan_feedback(monkeypatch):
    """超时（按确认全量执行）同样清除 plan_feedback，防 replan→超时 死循环"""
    agent = _make_agent(monkeypatch, wait_result=("confirm", [], "", True))
    result = agent._confirm_plan_node({
        "task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": [],
        "plan_feedback": "上轮补充要求",
    })
    assert result["plan_feedback"] == ""
    assert [s.order for s in result["sub_tasks"]] == [1, 2, 3]


def test_confirm_plan_republish_choice_after_confirm(monkeypatch):
    """确认后同 event_id republish 带 choice（JSON 含 keep_orders），供落库/历史回显"""
    import json
    agent = _make_agent(monkeypatch, wait_result=("confirm", [1, 3], "", False))
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    calls = agent.agent_queue_manager.publish.call_args_list
    assert len(calls) == 2  # 首次发布 + 确认后 republish
    first, second = calls[0].args[1], calls[1].args[1]
    assert first.id == second.id  # 同 event_id
    assert second.event == QueueEvent.ASK_USER
    assert second.choice  # 非空
    payload = json.loads(second.choice)
    assert payload["action"] == "confirm"
    assert payload["keep_orders"] == [1, 3]
    assert [s.order for s in result["sub_tasks"]] == [1, 3]


def test_confirm_plan_replan_no_republish(monkeypatch):
    """replan 分支不 republish（回 plan 重拆，无需回显最终选择）"""
    agent = _make_agent(monkeypatch, wait_result=("replan", [], "改方案", False))
    agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert len(agent.agent_queue_manager.publish.call_args_list) == 1
