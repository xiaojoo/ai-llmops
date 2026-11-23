"""本地工具运行时分支：验证 _tools_node 对 LOCAL_TOOL_NAMES 工具走本地运行时拦截。

关键回归：若 local_tool_runtime=True，fs_list 必须发 LOCAL_TOOL_CALL 事件并等 tool_result，
绝不能落到 stub 的 func（服务器执行、返回"本地工具运行时接管"提示）。
"""
import uuid
from unittest.mock import MagicMock

from pydantic import ConfigDict

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import (
    AgentConfig,
    LOCAL_TOOL_TIMEOUT_STREAK_LIMIT,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.core.tools.workspace_tools import build_local_tool_stubs
from internal.entity.conversation_entity import InvokeFrom


class _FakeLLM(BaseLanguageModel):
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


def _make_agent(monkeypatch, local_tool_runtime=True, wait_result=('{"success":true}', "")):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_tool_result", MagicMock(return_value=wait_result),
    )
    agent = FunctionCallAgent(
        name="local-tool-agent",
        llm=_FakeLLM(features=[ModelFeature.TOOL_CALL]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(),
            invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="",
            enable_long_term_memory=False,
            tools=build_local_tool_stubs(),
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config={},
            local_tool_runtime=local_tool_runtime,
        ),
    )
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    return agent


def test_local_tool_runtime_intercepts_fs_read(monkeypatch):
    """local_tool_runtime=True 时 fs_read 走本地运行时（发 LOCAL_TOOL_CALL），不执行桩 func。"""
    agent = _make_agent(monkeypatch, local_tool_runtime=True, wait_result=('{"success":true,"content":"x"}', ""))
    state = {"task_id": uuid.uuid4(), "messages": []}
    tool_call = {"name": "fs_read", "args": {"path": "src/App.vue"}, "id": "call_1"}
    result = agent._handle_local_tool(state, tool_call)
    assert result == '{"success":true,"content":"x"}'
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.LOCAL_TOOL_CALL
    assert published.tool == "fs_read"
    assert published.tool_call_id == "call_1"
    assert published.tool_input == {"path": "src/App.vue"}
    # 必须等待工具结果（含 tool_call_id 关联）
    wait_kwargs = AgentQueueManager.wait_for_tool_result.call_args.args
    assert wait_kwargs[0] == state["task_id"]
    assert wait_kwargs[1] == "call_1"


def test_local_tool_runtime_off_uses_stub_func(monkeypatch):
    """local_tool_runtime=False 时 fs_read 落到桩 func——桩被服务器直接调用应抛错。

    该用例锁定：桩 func 绝不应"安静地"返回一条会被 LLM 当成结果的提示；
    一旦被直接调用（=分发拦截失效），必须抛 RuntimeError 暴露问题。
    """
    import pytest
    agent = _make_agent(monkeypatch, local_tool_runtime=False)
    stubs = {t.name: t for t in build_local_tool_stubs()}
    with pytest.raises(RuntimeError):
        stubs["fs_read"].invoke({"path": "src/App.vue"})


def test_local_tool_call_timeout_reports_error(monkeypatch):
    """插件未回传（超时）时返回"本地工具执行出错"，不抛异常。"""
    agent = _make_agent(monkeypatch, local_tool_runtime=True, wait_result=("", "本地工具执行超时"))
    result = agent._handle_local_tool(
        {"task_id": uuid.uuid4(), "messages": []},
        {"name": "fs_search", "args": {"pattern": "*.py"}, "id": "call_2"},
    )
    assert "本地工具执行出错" in result
    assert "超时" in result


def test_local_tool_call_timeout_is_not_silent(monkeypatch):
    """超时不能只回给 LLM：必须额外发布一条 AGENT_MESSAGE 回显超时，让用户侧可见。"""
    agent = _make_agent(monkeypatch, local_tool_runtime=True, wait_result=("", "本地工具执行超时"))
    agent._handle_local_tool(
        {"task_id": uuid.uuid4(), "messages": []},
        {"name": "fs_write", "args": {"path": "x.cpp"}, "id": "call_3"},
    )
    events = [c.args[1] for c in agent.agent_queue_manager.publish.call_args_list]
    # 第一条是工具请求事件 LOCAL_TOOL_CALL
    assert events[0].event == QueueEvent.LOCAL_TOOL_CALL
    # 超时后额外发布 AGENT_MESSAGE 把超时反馈到输出（不许静默）
    message_events = [e for e in events if e.event == QueueEvent.AGENT_MESSAGE]
    assert message_events, "超时后应发布一条 AGENT_MESSAGE 回显，而不是静默"
    assert "本地工具" in message_events[-1].answer
    assert "超时" in message_events[-1].answer


def _streak_state():
    return {"task_id": uuid.uuid4(), "messages": [], "local_tool_timeout_streak": 0}


def test_local_tool_consecutive_timeout_breaks_after_limit(monkeypatch):
    """连续"超时类"错误计数到 LOCAL_TOOL_TIMEOUT_STREAK_LIMIT 后熔断：

    第 1/2 次各等 60s 超时并累计计数；第 3 次触发熔断（内容含熔断指引，可见 AGENT_MESSAGE 含原因）；
    第 4 次起快速失败：不再 wait_for_tool_result（无 60s 开销）、不再发布任何事件。
    """
    agent = _make_agent(monkeypatch, wait_result=("", "本地工具执行超时"))
    state = _streak_state()
    results = []
    for i in range(LOCAL_TOOL_TIMEOUT_STREAK_LIMIT):
        state["local_tool_timeout_streak"] = results[-1][1] if results else 0
        content, streak = agent._exec_local_tool(
            state,
            {"name": "fs_write", "args": {"path": f"f{i}.cpp"}, "id": f"call_streak_{i}"},
        )
        results.append((content, streak))
    # 前两轮普通超时错误；第 3 轮（达上限）内容切换为熔断指引
    assert results[0][1] == 1 and "本地工具执行出错" in results[0][0]
    assert results[1][1] == 2 and "本地工具执行出错" in results[1][0]
    assert results[2][1] == LOCAL_TOOL_TIMEOUT_STREAK_LIMIT
    assert "熔断" in results[2][0]
    assert "兜底" in results[2][0]
    assert "原因" in results[2][0]
    waits_after_crossing = AgentQueueManager.wait_for_tool_result.call_count
    publishes_after_crossing = agent.agent_queue_manager.publish.call_count

    # 熔断后（计数保持 >= 上限）后续本地工具快速失败：0 次等待、0 次新发布
    state["local_tool_timeout_streak"] = results[-1][1]
    content, streak = agent._exec_local_tool(
        state,
        {"name": "fs_read", "args": {"path": "x.cpp"}, "id": "call_fastfail"},
    )
    assert "熔断生效中" in content
    assert streak == LOCAL_TOOL_TIMEOUT_STREAK_LIMIT
    assert AgentQueueManager.wait_for_tool_result.call_count == waits_after_crossing
    assert agent.agent_queue_manager.publish.call_count == publishes_after_crossing


def test_local_tool_circuit_break_note_is_visible(monkeypatch):
    """熔断触发时可见的 AGENT_MESSAGE 必须包含失败原因与熔断字样（不静默结束）。"""
    agent = _make_agent(monkeypatch, wait_result=("", "本地工具执行超时"))
    state = _streak_state()
    streak = 0
    for i in range(LOCAL_TOOL_TIMEOUT_STREAK_LIMIT):
        state["local_tool_timeout_streak"] = streak
        _, streak = agent._exec_local_tool(
            state,
            {"name": "fs_write", "args": {"path": "x.cpp"}, "id": f"call_break_{i}"},
        )
    events = [c.args[1] for c in agent.agent_queue_manager.publish.call_args_list]
    message_events = [e for e in events if e.event == QueueEvent.AGENT_MESSAGE]
    assert message_events
    last_note = message_events[-1].answer
    assert "熔断" in last_note
    assert "连续" in last_note
    assert any(marker in last_note for marker in ("未回传", "重启", "断流", "插件"))  # 输出为什么失败


def test_local_tool_success_resets_streak(monkeypatch):
    """成功结果（或普通执行错误=插件存活）应把连续超时计数复位为 0。"""
    results = [("", "本地工具执行超时"), ("", "本地工具执行超时"), ('{"success":true}', "")]
    agent = _make_agent(monkeypatch)
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_tool_result", MagicMock(side_effect=results),
    )
    state = _streak_state()
    streak = 0
    for i in range(3):
        state["local_tool_timeout_streak"] = streak
        content, streak = agent._exec_local_tool(
            state,
            {"name": "fs_write", "args": {"path": f"f{i}.cpp"}, "id": f"call_reset_{i}"},
        )
        if i < 2:
            assert "本地工具执行出错" in content
    assert streak == 0  # 成功 → 复位
    assert "success" in content

    # 插件看门狗回传的"本地工具执行超时（插件看门狗 …）"同样属于超时类错误（startswith 命中）
    state["local_tool_timeout_streak"] = 0
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_tool_result",
        MagicMock(return_value=("", "本地工具执行超时（插件看门狗 40s 未完成）")),
    )
    content, streak = agent._exec_local_tool(
        state,
        {"name": "fs_read", "args": {"path": "x.cpp"}, "id": "call_wd"},
    )
    assert streak == 1
    assert "熔断" not in content
