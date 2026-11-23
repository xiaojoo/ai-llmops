#!/usr/bin/env python
"""AgentState 真实图集成测试（回归防护）。

修复前：AgentState 未声明 user_profile / episodic_memory 键，langgraph 1.2.11 的
map_input 对 schema 外的输入键静默丢弃，导致两个 Agent 的
state.get("episodic_memory", "") 恒为空 —— 情景记忆与用户画像在生产静默失效。

本测试构造真实 FunctionCallAgent（真实 langgraph 编译图 + 假 LLM 流式一段固定文本），
仅把依赖 Redis 的 AgentQueueManager 替换为进程内收集事件的替身，
断言产出的 AGENT_MESSAGE 事件中 system 消息真实包含 <用户画像> 与 <情景记忆> 块内容。
"""
import threading
import time
import uuid

from langchain_core.messages import AIMessageChunk, HumanMessage
from pydantic import ConfigDict

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class FakeStreamLLM(BaseLanguageModel):
    """真实 Agent 图可接受的假 LLM：支持 tool_call，流式产出一段固定文本"""
    # langchain-core 1.6.0 的 BaseLanguageModel model_config 为 extra='ignore'，
    # 需显式开启 extra='allow'（与 test_conversation_compact.BudgetLLM 同模式）
    model_config = ConfigDict(extra="allow")

    def stream(self, messages):
        yield AIMessageChunk(content="好的", tool_calls=[])

    def get_num_tokens_safe(self, messages):
        return 10

    # langchain BaseLanguageModel 抽象方法：测试路径不会走到（节点只调 stream）
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class StubQueueManager:
    """队列管理器替身：进程内收集事件，避免真实实现 publish 时写 Redis"""

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

    def stop_listen(self, task_id):
        self._done.set()

    def listen(self, task_id):
        deadline = time.time() + 10
        while time.time() < deadline:
            if self._done.is_set():
                yield from self.events
                return
            time.sleep(0.01)
        raise AssertionError("Agent 图 10s 内未完成推理")


def _collect_system_prompts(events) -> list[str]:
    """从产出事件的消息列表中提取所有 system 消息内容

    AgentThought.message 为 messages_to_dict 输出（{type, data:{content,...}}），
    内容需从 data.content 读取。
    """
    return [
        m.get("data", {}).get("content", "")
        for thought in events
        if thought.event == QueueEvent.AGENT_MESSAGE
        for m in thought.message
        if m.get("type") == "system"
    ]


def test_real_agent_graph_passes_user_profile_and_episodic_memory(monkeypatch):
    """真实 FunctionCallAgent 图：user_profile / episodic_memory 透传到系统提示词"""
    monkeypatch.setattr(
        "internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager,
    )

    agent = FunctionCallAgent(
        name="test-agent",
        llm=FakeStreamLLM(features=[ModelFeature.TOOL_CALL]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(),
            invoke_from=InvokeFrom.WEB_APP,
            preset_prompt="你是客服助手",
            tools=[],
        ),
    )

    events = list(agent.stream({
        "messages": [HumanMessage(content="你好")],
        "history": [],
        "long_term_memory": "",
        "user_profile": "用户常驻北京",
        "episodic_memory": "用户正在准备搬家到北京，已完成房源搜索",
    }))

    system_prompts = _collect_system_prompts(events)
    assert system_prompts, "AGENT_MESSAGE 事件应携带 system 消息"
    joined = "\n".join(system_prompts)
    assert "用户常驻北京" in joined, "系统提示词应包含 <用户画像> 块"
    assert "用户正在准备搬家到北京，已完成房源搜索" in joined, "系统提示词应包含 <情景记忆> 块"
