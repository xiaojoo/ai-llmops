import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from pydantic import ConfigDict

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.run_context import RunContext
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class FakeLLM(BaseLanguageModel):
    model_config = ConfigDict(extra="allow")

    def stream(self, messages):
        yield AIMessageChunk(content="ok")

    def get_num_tokens_safe(self, messages):
        return 1

    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


def test_run_context_merges_config_and_creates_child_namespace():
    run_id = uuid.uuid4()
    ctx = RunContext(run_id=run_id, task_id=run_id, thread_id="message-1")
    config = ctx.config({"configurable": {"existing": 1}, "tags": ["agent"]})
    assert config["configurable"] == {"existing": 1, "thread_id": "message-1"}
    assert config["tags"] == ["agent"]

    child = ctx.child(uuid.uuid4(), "plan:2")
    assert child.thread_id == "message-1"
    assert child.config()["configurable"]["checkpoint_ns"] == "plan:2"


def test_agent_resume_invokes_checkpoint_without_replaying_input(monkeypatch):
    class StubQueueManager:
        def __init__(self, **_kwargs):
            self.events = [AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.AGENT_END)]

        def listen(self, _task_id):
            yield from self.events

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    llm = FakeLLM(features=[ModelFeature.TOOL_CALL], model_name="fake")
    agent = FunctionCallAgent(
        name="resume",
        llm=llm,
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, tools=[]),
    )
    compiled = MagicMock()
    compiled.get_state.return_value = SimpleNamespace(next=("llm",))
    agent._agent = compiled
    agent._checkpointer = object()
    run_id = uuid.uuid4()
    agent._run_context = RunContext(run_id=run_id, task_id=run_id, thread_id="message-1")

    list(agent.stream({
        "messages": [HumanMessage(content="continue")],
        "history": [],
        "iteration_count": 1,
        "resume": True,
    }))

    assert compiled.invoke.call_args.args[0] is None
    compiled.update_state.assert_called_once()
    assert compiled.update_state.call_args.args[1] == {"task_id": run_id}
    config = compiled.invoke.call_args.args[1]
    assert config["configurable"]["thread_id"] == "message-1"


def test_graph_checkpoint_resumes_after_node_failure(monkeypatch):
    class StubQueueManager:
        def __init__(self, **_kwargs):
            self.events = []
            self.done = threading.Event()

        def publish(self, _task_id, thought):
            self.events.append(thought)
            if thought.event in {QueueEvent.AGENT_END, QueueEvent.ERROR}:
                self.done.set()

        def publish_error(self, task_id, error):
            self.publish(task_id, AgentThought(
                id=uuid.uuid4(), task_id=task_id, event=QueueEvent.ERROR, observation=str(error),
            ))

        def listen(self, _task_id):
            deadline = time.time() + 5
            while not self.done.is_set() and time.time() < deadline:
                time.sleep(0.01)
            yield from self.events

    from internal.core.agent.agents.base_agent import BaseAgent
    from internal.core.agent.entities.agent_entity import AgentState

    calls = []

    class CrashOnceAgent(BaseAgent):
        def _build_agent(self):
            graph = StateGraph(AgentState)
            graph.add_node("step", self._step)
            graph.set_entry_point("step")
            graph.add_edge("step", END)
            return graph.compile(checkpointer=self._checkpointer)

        def _step(self, state):
            calls.append(state["task_id"])
            if len(calls) == 1:
                raise RuntimeError("boom")
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
            ))
            return {"iteration_count": state["iteration_count"] + 1}

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    saver = InMemorySaver()
    run_id = uuid.uuid4()
    ctx = RunContext(run_id=run_id, task_id=run_id, thread_id="message-1")
    config = AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, tools=[])
    state = {
        "messages": [HumanMessage(content="continue")],
        "history": [],
        "iteration_count": 0,
        "long_term_memory": "",
        "resume": False,
    }
    first = CrashOnceAgent(name="first", llm=FakeLLM(features=[]), agent_config=config, checkpointer=saver, run_context=ctx)
    assert any(event.event == QueueEvent.ERROR for event in first.stream(state))

    resumed_run_id = uuid.uuid4()
    resumed_ctx = RunContext(run_id=resumed_run_id, task_id=resumed_run_id, thread_id="message-1")
    second = CrashOnceAgent(
        name="second", llm=FakeLLM(features=[]), agent_config=config,
        checkpointer=saver, run_context=resumed_ctx,
    )
    events = list(second.stream({**state, "task_id": resumed_run_id, "resume": True}))
    assert any(event.event == QueueEvent.AGENT_END for event in events)
    assert calls == [run_id, resumed_run_id]
