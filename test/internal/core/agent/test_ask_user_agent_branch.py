import uuid
from unittest.mock import MagicMock

from pydantic import ConfigDict

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig, ASK_USER_TOOL_NAME
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class _FakeLLM(BaseLanguageModel):
    """可被 pydantic 校验的假 LLM（_handle_ask_user 不调用 LLM，仅需合法实例）"""
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


def _make_agent(monkeypatch, wait_result=("RBAC", False, "")):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_choice", MagicMock(return_value=wait_result),
    )
    agent = FunctionCallAgent(
        name="ask-user-agent",
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
    # 真实 publish 会写任务队列，测试中替换为记录调用的 mock（断言用 call_args）
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    return agent


def test_handle_ask_user_publishes_event_and_returns_choice(monkeypatch):
    agent = _make_agent(monkeypatch)
    task_id = uuid.uuid4()
    state = {"task_id": task_id, "messages": []}
    tool_call = {
        "name": ASK_USER_TOOL_NAME,
        "args": {"question": "选择哪种授权模型？", "options": ["RBAC", "ABAC"], "allow_custom": True},
        "id": "call_1",
    }
    result = agent._handle_ask_user(state, tool_call)
    assert result == "用户选择了：RBAC"
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.ASK_USER
    assert published.question == "选择哪种授权模型？"
    assert published.options == ["RBAC", "ABAC"]
    assert published.allow_custom is True
    assert published.tool == ASK_USER_TOOL_NAME
    # wait_for_choice 必须携带本次 ask_user 事件的 event_id（防残留载荷污染）
    wait_kwargs = AgentQueueManager.wait_for_choice.call_args.kwargs
    assert wait_kwargs.get("event_id") == str(published.id)


def test_handle_ask_user_skip(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=(None, True, ""))
    result = agent._handle_ask_user({"task_id": uuid.uuid4(), "messages": []}, {"name": ASK_USER_TOOL_NAME, "args": {"question": "q"}, "id": "c1"})
    assert "跳过" in result


def test_handle_ask_user_re_publishes_event_with_choice(monkeypatch):
    """用户选择后，同一 event_id 重新发布带 choice 的 ASK_USER 事件（落库回显）"""
    agent = _make_agent(monkeypatch, wait_result=("ABAC", False, ""))
    task_id = uuid.uuid4()
    state = {"task_id": task_id, "messages": []}
    tool_call = {"name": ASK_USER_TOOL_NAME, "args": {"question": "q", "options": ["RBAC", "ABAC"], "allow_custom": True}, "id": "c3"}
    result = agent._handle_ask_user(state, tool_call)
    assert result == "用户选择了：ABAC"
    published = [c.args[1] for c in agent.agent_queue_manager.publish.call_args_list]
    ask_events = [t for t in published if t.event == QueueEvent.ASK_USER]
    assert len(ask_events) == 2
    assert ask_events[0].id == ask_events[1].id  # 同一 event_id
    assert ask_events[0].choice == "" or ask_events[0].choice is None  # 首次发布无 choice
    assert ask_events[1].choice == "ABAC"  # 二次发布带 choice


def test_handle_ask_user_timeout_treated_as_skip(monkeypatch):
    """等待用户选择超时（wait_for_choice 返回 (None, True, "")）时按跳过处理"""
    agent = _make_agent(monkeypatch, wait_result=(None, True, ""))
    result = agent._handle_ask_user({"task_id": uuid.uuid4(), "messages": []}, {"name": ASK_USER_TOOL_NAME, "args": {"question": "q"}, "id": "c2"})
    assert "跳过" in result
