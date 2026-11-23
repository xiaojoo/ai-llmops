import uuid

from langchain_core.messages import HumanMessage

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.entity.conversation_entity import InvokeFrom


def test_entry_condition_routes_resume_to_llm():
    state = {"resume": True}
    assert FunctionCallAgent._entry_condition(state) == "llm"


def test_entry_condition_routes_normal_to_preset():
    state = {"resume": False}
    assert FunctionCallAgent._entry_condition(state) == "preset_operation"


def test_build_agent_accepts_resume_state(monkeypatch):
    """真实图编译冒烟：resume=True 的输入能跑通（消息序列不重建）"""
    from langchain_core.messages import AIMessageChunk
    from pydantic import ConfigDict

    from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
    from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent

    class FakeStreamLLM(BaseLanguageModel):
        model_config = ConfigDict(extra="allow")

        def stream(self, messages):
            yield AIMessageChunk(content="续跑完成", tool_calls=[])

        def get_num_tokens_safe(self, messages):
            return 10

        def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
            raise NotImplementedError

        async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
            raise NotImplementedError

        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

    import threading
    import time

    class StubQueueManager:
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

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)

    agent = FunctionCallAgent(
        name="resume-agent",
        llm=FakeStreamLLM(features=[ModelFeature.TOOL_CALL]),
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[]),
    )
    events = list(agent.stream({
        "messages": [HumanMessage(content="原问题")],
        "history": [],
        "iteration_count": 3,
        "resume": True,
    }))
    assert any(e.event == QueueEvent.AGENT_MESSAGE for e in events)
