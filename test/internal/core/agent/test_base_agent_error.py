"""回归测试：模型 API 异常（402 余额不足等）不再静默吞掉/前端无限转圈。

修复前：图线程内 self._agent.invoke() 抛异常 → 线程静默死亡 →
AgentQueueManager.listen() 空等至 600s 超时，前端一直转圈。
修复后：BaseAgent.stream 捕获图线程异常并发布 ERROR 事件
（observation 为面向用户的中文提示），监听端立即终止。
"""
import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from internal.core.agent.agents import OrchestratorAgent
from internal.core.agent.agents.base_agent import _format_agent_error
from internal.core.agent.entities.agent_entity import AgentConfig, SubTaskSpec
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager


@pytest.fixture(autouse=True)
def _mock_confirm_waits(monkeypatch):
    """图级测试聚焦异常透出机制：确认节点真实执行，但把阻塞在 Redis 的
    wait_for_plan_choice 替换为"确认全量"（真实实现会 blpop 300s 挂起测试）"""
    monkeypatch.setattr(
        "internal.core.agent.agents.agent_queue_manager.AgentQueueManager.wait_for_plan_choice",
        MagicMock(return_value=("confirm", [], "", False)),
    )


class FakeAPIError(Exception):
    """模拟 openai SDK API 错误：带 status_code"""

    def __init__(self, status_code, message):
        self.status_code = status_code
        super().__init__(message)


class RaisingLLM(FakeOrchestratorLLM):
    """stream 直接抛错：走 direct_answer 路径触发图线程异常"""

    def __init__(self, *, exc, **kwargs):
        super().__init__(subtasks=[], **kwargs)
        self._exc = exc

    def stream(self, messages):
        raise self._exc


def _run(monkeypatch, exc):
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch",
        llm=RaisingLLM(exc=exc),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
            preset_prompt="", tools=[],
        ),
    )
    return list(agent.stream({
        "messages": [HumanMessage(content="写报告")],
        "history": [],
        "query": "写报告",
    }))


def _error_observations(events):
    return [e.observation for e in events if e.event == QueueEvent.ERROR]


def test_llm_402_insufficient_balance_publishes_friendly_error(monkeypatch):
    """402 余额不足 → ERROR 事件 observation 为中文充值提示（不再无限转圈）"""
    events = _run(monkeypatch, FakeAPIError(402, "Error code: 402 - Insufficient Balance"))
    obs = _error_observations(events)
    assert obs, "图线程异常应发布 ERROR 事件"
    assert "模型 API 余额不足，请充值后重试" in obs[0], obs


def test_llm_402_by_text_feature(monkeypatch):
    """无 status_code 的供应商错误按文本特征识别余额不足"""
    events = _run(monkeypatch, RuntimeError("insufficient_quota: balance exhausted"))
    obs = _error_observations(events)
    assert obs and "模型 API 余额不足" in obs[0], obs


def test_llm_429_rate_limit_friendly(monkeypatch):
    events = _run(monkeypatch, FakeAPIError(429, "Rate limit reached for requests"))
    obs = _error_observations(events)
    assert obs and "请求过于频繁" in obs[0], obs


def test_llm_401_invalid_key_friendly(monkeypatch):
    events = _run(monkeypatch, FakeAPIError(401, "Incorrect API key provided"))
    obs = _error_observations(events)
    assert obs and "API Key 无效" in obs[0], obs


def test_llm_timeout_friendly(monkeypatch):
    events = _run(monkeypatch, TimeoutError("request timed out"))
    obs = _error_observations(events)
    assert obs and "请求超时" in obs[0], obs


def test_llm_5xx_friendly(monkeypatch):
    events = _run(monkeypatch, FakeAPIError(503, "service unavailable"))
    obs = _error_observations(events)
    assert obs and "服务暂时不可用" in obs[0], obs


def test_generic_error_truncated(monkeypatch):
    """未归类异常保留原文并截断，避免长报文刷屏"""
    events = _run(monkeypatch, RuntimeError("x" * 2000))
    obs = _error_observations(events)
    assert obs
    assert obs[0] == "x" * 500, "超长异常应截断到 500 字符"


def test_format_agent_error_custom_exception():
    """业务自定义异常（消息在 .message 属性）直接透传中文消息"""
    from internal.exception import FailedException

    assert _format_agent_error(FailedException("智能体历史消息列表格式错误")) == "智能体历史消息列表格式错误"


def test_orchestrator_subtask_error_surfaces(monkeypatch):
    """子 Agent 图线程异常 → SUB_TASK_END 以 error 透出，不再静默 normal 空答案完成"""
    class SubErrorLLM(FakeOrchestratorLLM):
        def __init__(self, **kwargs):
            super().__init__(
                subtasks=[SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")],
                **kwargs,
            )

        def stream(self, messages):
            raise FakeAPIError(402, "Insufficient Balance")

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch", llm=SubErrorLLM(),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
            preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    events = list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [], "query": "写报告",
    }))
    end_events = [e for e in events if e.event == QueueEvent.SUB_TASK_END]
    assert end_events, "应发布 SUB_TASK_END"
    assert end_events[0].observation.startswith("error:"), end_events[0].observation
    assert "模型 API 余额不足" in end_events[0].observation, end_events[0].observation
