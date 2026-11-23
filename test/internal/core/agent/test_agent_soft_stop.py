#!/usr/bin/env python
"""软停止（soft stop）契约测试：停止标志生效后 Agent 不再续轮，当前步完成后收尾。

背景：停止请求经 set_stop_flag 写 Redis 标志，listen 仅终止 SSE 输出；
langgraph 图线程（self._agent.invoke）不会因此中断——若不在图节点边界显式检查，
停止后 LLM/工具循环仍会跑完，表现为"前端已结束、子任务还在跑"。

本文件用可注入 stopped 状态的 StubQueueManager 验证（不依赖真实 Redis/PG）：
- FunctionCallAgent._llm_node：已停止时不再调用 LLM，直接发布 AGENT_END 收尾（软停止）。
- FunctionCallAgent._tools_node：已停止时跳过工具执行，为 tool_calls 补齐空 ToolMessage。
- _is_task_stopped 异常安全（Redis 未就绪视为未停止）。
- 未停止时正常路径（工具调用/LLM 收尾）行为不变。
"""
import uuid

from langchain_core.messages import AIMessageChunk, HumanMessage

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class _StoppedQueueManager:
    """事件收集 + 可配置 stopped 状态（替代依赖 Redis 的真实管理器）"""

    def __init__(self, user_id=None, invoke_from=None, model_name="", *, stopped=False):
        self.events = []
        self._stopped = stopped

    def set_stopped(self, value: bool):
        self._stopped = value

    def publish(self, task_id, thought):
        self.events.append(thought)

    def publish_error(self, task_id, error):
        self.events.append(AgentThought(
            id=uuid.uuid4(), task_id=task_id, event=QueueEvent.ERROR, observation=str(error),
        ))

    def forward(self, task_id, thought):
        self.events.append(thought)

    def stop_listen(self, task_id):
        pass

    def listen(self, task_id):
        yield from self.events

    def _is_stopped(self, task_id):
        return self._stopped


class _RecordingLLM(BaseLanguageModel):
    """记录是否被调用；stream 返回 tool_calls（模拟工具循环场景）"""
    model_config = {"extra": "allow"}
    stream_calls: int = 0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.features = [ModelFeature.TOOL_CALL]
        self.stream_calls = 0

    def stream(self, messages):
        self.stream_calls += 1
        yield AIMessageChunk(content="需要调用工具", tool_calls=[
            {"name": "fake_tool", "args": {}, "id": "call_1", "type": "tool_call"},
        ])

    def get_num_tokens_safe(self, messages):
        return 10

    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


def _base_state(**over):
    s = {
        "task_id": uuid.uuid4(),
        "messages": [HumanMessage(content="查询")],
        "history": [],
        "iteration_count": 0,
        "long_term_memory": "",
        "user_profile": "",
        "episodic_memory": "",
        "procedural_instructions": "",
        "local_tool_timeout_streak": 0,
        "sub_tasks": [],
        "sub_results": [],
        "final_answer": "",
    }
    s.update(over)
    return s


def test_llm_node_stopped_skips_llm_and_finishes():
    """已停止：_llm_node 不调用 LLM，直接发布 AGENT_END 收尾（不再续轮/不再生成）"""
    qm = _StoppedQueueManager(stopped=True)
    llm = _RecordingLLM()
    agent = FunctionCallAgent(
        name="fc", llm=llm,
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
                                 preset_prompt="", tools=[], max_iteration_count=5),
    )
    agent._agent_queue_manager = qm

    result = agent._llm_node(_base_state())
    assert llm.stream_calls == 0, "已停止时不应再调用 LLM"
    assert any(t.event == QueueEvent.AGENT_END for t in qm.events), \
        f"已停止应发布 AGENT_END 收尾，实际: {[t.event for t in qm.events]}"
    # 状态仍可继续（返回最后一条消息，不破坏 langgraph 消息队列）
    assert len(result["messages"]) >= 1


def test_tools_node_stopped_skips_tool_execution():
    """已停止：_tools_node 跳过工具执行，为 tool_calls 补齐空 ToolMessage 保持序列合法"""
    from langchain_core.messages import AIMessage, ToolMessage
    qm = _StoppedQueueManager(stopped=True)
    llm = _RecordingLLM()
    agent = FunctionCallAgent(
        name="fc", llm=llm,
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
                                 preset_prompt="", tools=[], max_iteration_count=5),
    )
    agent._agent_queue_manager = qm

    state = _base_state(messages=[AIMessage(content="", tool_calls=[
        {"name": "fake_tool", "args": {}, "id": "call_1", "type": "tool_call"},
    ])])
    result = agent._tools_node(state)
    assert len(result["messages"]) == 1, "已停止时应为 tool_calls 补齐一条 ToolMessage"
    assert isinstance(result["messages"][0], ToolMessage)
    assert result["messages"][0].content == ""


def test_is_task_stopped_reflects_flag_and_is_safe():
    """_is_task_stopped 反映停止标志；异常安全（未就绪视为未停止）"""
    qm = _StoppedQueueManager(stopped=False)
    llm = _RecordingLLM()
    agent = FunctionCallAgent(
        name="fc", llm=llm,
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
                                 preset_prompt="", tools=[]),
    )
    agent._agent_queue_manager = qm
    state = {"task_id": uuid.uuid4()}
    assert agent._is_task_stopped(state) is False
    qm.set_stopped(True)
    assert agent._is_task_stopped(state) is True


def test_llm_node_not_stopped_still_calls_llm():
    """未停止：LLM 正常调用（行为不变，工具循环路径不受影响）"""
    qm = _StoppedQueueManager(stopped=False)
    llm = _RecordingLLM()
    agent = FunctionCallAgent(
        name="fc", llm=llm,
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
                                 preset_prompt="", tools=[], max_iteration_count=5),
    )
    agent._agent_queue_manager = qm

    result = agent._llm_node(_base_state())
    assert llm.stream_calls == 1, "未停止时应正常调用 LLM"
    # 本轮 tool_calls 正常返回（进入工具循环）
    assert result["messages"][-1].tool_calls, "未停止时工具调用应正常返回"
