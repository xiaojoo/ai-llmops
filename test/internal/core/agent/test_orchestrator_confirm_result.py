import uuid
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from pydantic import ConfigDict

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig, SubTaskResult
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class _FakeLLM(BaseLanguageModel):
    """可被 pydantic 校验的假 LLM（brief 原用 llm=MagicMock()，但 BaseAgent.llm 字段
    要求 BaseLanguageModel 实例，pydantic 校验不过——与 test_orchestrator_confirm_plan.py 同款处理）"""
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


class _StreamFakeLLM(_FakeLLM):
    """流式假 LLM：_summarize_node 测试用，stream 吐一个 AIMessage chunk"""

    def stream(self, messages):
        yield AIMessage(content="汇总结果文本")


def _make_agent(monkeypatch, verdict=None, wait_result=("确认完成", False, "")):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_choice", MagicMock(return_value=wait_result),
    )
    llm = _FakeLLM(features=[ModelFeature.TOOL_CALL])
    class FakeVerdict:
        need_confirm = verdict.need_confirm if verdict else False
        reason = verdict.reason if verdict else ""
    class FakePlanner:
        def invoke(self, messages):
            return FakeVerdict()
    llm.with_structured_output = MagicMock(return_value=FakePlanner())
    agent = OrchestratorAgent(
        name="test-orch",
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="", enable_long_term_memory=False, tools=[],
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config={},
        ),
    )
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    return agent


def test_confirm_result_no_ambiguity_no_ask(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=False, reason=""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    agent.agent_queue_manager.publish.assert_not_called()
    assert result == {}


def test_confirm_result_ambiguity_publishes_ask(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="方向未定"))
    agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.ASK_USER
    assert published.options == ["确认完成", "重新生成"]
    assert "方向未定" in published.question


def test_confirm_result_confirm_done(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("确认完成", False, ""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert result == {}


def test_confirm_result_regenerate(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("重新生成", False, "重点看方案B"))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert result["regenerate"] is True
    assert result["plan_feedback"] == "重点看方案B"
    assert result["plan_attempts"] == 1  # 递增而非重置 0


def test_confirm_result_regenerate_increments_plan_attempts(monkeypatch):
    """regenerate 递增 plan_attempts（而非重置 0），2 轮上限约束生效"""
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("重新生成", False, "重点看方案B"))
    r1 = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert r1["plan_attempts"] == 1
    r2 = agent._confirm_result_node({
        "task_id": uuid.uuid4(), "query": "q", "final_answer": "a", "plan_attempts": 1,
    })
    assert r2["plan_attempts"] == 2


def test_confirm_result_confirm_done_republish_choice(monkeypatch):
    """确认完成后同 event_id republish 带 choice='确认完成'，供落库/历史回显"""
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("确认完成", False, ""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    calls = agent.agent_queue_manager.publish.call_args_list
    assert len(calls) == 2
    first, second = calls[0].args[1], calls[1].args[1]
    assert first.id == second.id  # 同 event_id
    assert second.choice == "确认完成"
    assert result == {}


def test_confirm_result_regenerate_republish_choice(monkeypatch):
    """重新生成 republish 带 choice（含用户原因）"""
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("重新生成", False, "重点看方案B"))
    agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    second = agent.agent_queue_manager.publish.call_args_list[1].args[1]
    assert second.choice == "重新生成：重点看方案B"


def test_confirm_result_timeout_no_republish(monkeypatch):
    """超时（skipped）不 republish（前端保持原样）"""
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=(None, True, ""))
    agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert len(agent.agent_queue_manager.publish.call_args_list) == 1


def test_confirm_result_timeout_done(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=(None, True, ""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert result == {}


def test_plan_condition_routes_to_confirm_plan_when_subtasks():
    """plan 后有子任务先经 confirm_plan 确认（而非直接 execute）"""
    assert OrchestratorAgent._plan_condition({"sub_tasks": [1]}) == "confirm_plan"


def test_plan_condition_direct_answer_without_subtasks():
    """无子任务仍走 direct_answer"""
    assert OrchestratorAgent._plan_condition({"sub_tasks": []}) == "direct_answer"


def test_summarize_node_writes_final_answer(monkeypatch):
    """_summarize_node 把汇总文本写入 final_answer（confirm_result 依赖此键）"""
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_choice", MagicMock(return_value=("确认完成", False, "")),
    )
    agent = OrchestratorAgent(
        name="test-orch",
        llm=_StreamFakeLLM(features=[ModelFeature.TOOL_CALL]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="", enable_long_term_memory=False, tools=[],
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config={},
        ),
    )
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    result = agent._summarize_node({
        "task_id": uuid.uuid4(), "query": "q", "messages": [],
        "sub_results": [SubTaskResult(order=1, title="子任务1", status="normal", answer="结果A")],
    })
    assert result["final_answer"] == "汇总结果文本"
    assert result["messages"][0].content == "汇总结果文本"
