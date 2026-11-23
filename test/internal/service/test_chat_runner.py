#!/usr/bin/env python
"""ChatRunner 统一对话执行器 async 化测试——SSE 产出、异常兜底、落库调用。

run() 为 async generator（async for 产出 SSE 事件）；全部依赖以 mock 替身化，不真实调用 LLM。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.service import ChatRunner
from internal.service.memory_provider.base import MemoryReadContext


class StubProvider:
    """记忆 Provider 测试替身：可控读侧/写侧行为（读侧与 trigger_write 为 async）"""
    def __init__(self, *, user_profile="", episodic_memory="", procedural_instructions="", tools=None):
        self.user_profile = user_profile
        self.episodic_memory = episodic_memory
        self.procedural_instructions = procedural_instructions
        self.tools = tools or []
        self.triggered = None

    def get_user_profile(self, app_config, app_id, user_id):
        return self.user_profile

    async def get_read_context(self, app_config, app_id, user_id, query):
        return MemoryReadContext(
            episodic_memory=self.episodic_memory,
            procedural_instructions=self.procedural_instructions,
        )

    async def get_memory_tools(self, app_config, app_id, user_id):
        return self.tools

    async def trigger_write(self, **kwargs):
        self.triggered = kwargs


def _stub_tools(names):
    """工具替身：AgentConfig.tools 为 list[BaseTool]（pydantic 严格校验），需真实 BaseTool 实例"""
    from langchain_core.tools import StructuredTool
    return [
        StructuredTool(
            name=n, description=f"{n} 测试替身",
            args_schema={"title": n.capitalize(), "type": "object", "properties": {}},
            func=lambda **kw: "",
        )
        for n in names
    ]


async def _drain_bg_tasks():
    """trigger_write 为 fire-and-forget（asyncio.create_task + _BG_MEMORY_TASKS）——
    流结束后排空后台任务，保证 trigger_write 断言确定可见。"""
    from internal.service import chat_runner as chat_runner_mod

    tasks = list(chat_runner_mod._BG_MEMORY_TASKS)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


class FakeLLM:
    """支持 tool_call 的假 LLM"""
    features = (ModelFeature.TOOL_CALL,)
    context_window = None
    max_tokens = 8192

    def convert_to_human_message(self, query, image_urls=None):
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=query)


class FakeAgent:
    """流式产出一个 AGENT_MESSAGE 后结束的假 Agent"""
    def __init__(self, *args, **kwargs):
        pass

    def stream(self, *args, **kwargs):
        yield AgentThought(
            id=uuid4(), task_id=uuid4(),
            event=QueueEvent.AGENT_MESSAGE,
            thought="你好", message=[], answer="你好", latency=0.1,
        )


MOCK_CONFIG = {
    "model_config": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    "dialog_round": 5,
    "tools": [],
    "datasets": [],
    "workflows": [],
    "skills": [],
    "preset_prompt": "",
    "long_term_memory": {"enable": False},
    "review_config": {},
}


def _make_runner(monkeypatch, *, stub_provider=None, agent_class=None, saved=None) -> ChatRunner:
    """构造 ChatRunner（纯 mock 依赖）+ 标准替身化（load/history/compact/save/memory resolve）。

    所有被 run() await 的依赖均为 AsyncMock；save_agent_thoughts 捕获到 saved 字典。
    """
    runner = ChatRunner(
        db=MagicMock(),
        retrieval_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        memory_provider_resolver=MagicMock(),
    )
    # 进入 Agent 循环前 run() 会 await self.db.commit()——db mock 需 async commit
    runner.db.commit = AsyncMock()
    runner.language_model_service.load_language_model = AsyncMock(return_value=FakeLLM())
    runner.app_config_service.get_langchain_tools_by_tools_config = AsyncMock(return_value=[])
    runner._build_history = AsyncMock(return_value=[])
    runner.conversation_service.compact_if_needed = AsyncMock(return_value=False)

    def _fake_save(**kwargs):
        if saved is not None:
            saved.update(kwargs)
    runner.conversation_service.save_agent_thoughts = AsyncMock(side_effect=_fake_save)

    stub = stub_provider or StubProvider()
    runner.memory_provider_resolver.resolve = AsyncMock(return_value=stub)
    if agent_class is not None:
        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", agent_class)
    return runner, stub


class TestChatRunner:
    @pytest.mark.asyncio
    async def test_run_streams_sse_and_persists(self, monkeypatch):
        saved = {}
        runner, _ = _make_runner(monkeypatch, agent_class=FakeAgent, saved=saved)
        account = MagicMock(id=uuid4())
        app_id = uuid4()
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        events = [e async for e in runner.run(
            app=MagicMock(id=app_id),
            app_config=dict(MOCK_CONFIG),
            conversation=conversation,
            message=message,
            account=account,
            invoke_from=InvokeFrom.DEBUGGER,
        )]

        assert any("event: agent_message" in e for e in events), "应产出 agent_message 事件"
        assert saved.get("invoke_from") == InvokeFrom.DEBUGGER
        assert saved.get("conversation_id") == conversation.id


class TestChatRunnerProfile:
    @pytest.mark.asyncio
    async def test_run_passes_user_profile_to_agent(self, monkeypatch):
        captured = {}

        class CapturingAgent(FakeAgent):
            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        runner, _ = _make_runner(monkeypatch, agent_class=CapturingAgent)
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        [e async for e in runner.run(
            app=MagicMock(id=uuid4()),
            app_config=dict(MOCK_CONFIG),
            conversation=conversation,
            message=message,
            account=MagicMock(id=uuid4()),
            invoke_from=InvokeFrom.WEB_APP,
            user_profile="location: {\"city\": \"北京\"}",
        )]

        assert captured["input"]["user_profile"] == "location: {\"city\": \"北京\"}"


class TestChatRunnerEpisodicMemory:
    @pytest.mark.asyncio
    async def test_run_passes_episodic_memory_to_agent(self, monkeypatch):
        captured = {}

        class CapturingAgent(FakeAgent):
            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        stub = StubProvider(episodic_memory="用户正在准备搬家到北京")
        runner, _ = _make_runner(monkeypatch, stub_provider=stub, agent_class=CapturingAgent)
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[], attachment_text="")

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": True}

        [e async for e in runner.run(
            app=MagicMock(id=uuid4()),
            app_config=config,
            conversation=conversation,
            message=message,
            account=MagicMock(id=uuid4()),
            invoke_from=InvokeFrom.WEB_APP,
        )]

        assert "用户正在准备搬家到北京" in captured["input"].get("episodic_memory", "")


class TestChatRunnerMemoryExtraction:
    @pytest.mark.asyncio
    async def test_extraction_triggered_after_stream(self, monkeypatch):
        runner, stub = _make_runner(monkeypatch, agent_class=FakeAgent)
        account = MagicMock(id=uuid4())
        message = MagicMock(id=uuid4(), query="北京天气怎么样", image_urls=[])
        mock_app = MagicMock(id=uuid4())

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": True}

        [e async for e in runner.run(
            app=mock_app,
            app_config=config,
            conversation=MagicMock(id=uuid4(), summary=""),
            message=message,
            account=account,
            invoke_from=InvokeFrom.WEB_APP,
        )]
        await _drain_bg_tasks()

        assert stub.triggered is not None
        assert stub.triggered.get("app_config", {}).get("long_term_memory", {}).get("enable") is True
        # 抽取线程只收纯值，不再持有请求线程的 ORM 对象
        assert "conversation" not in stub.triggered and "message" not in stub.triggered
        assert stub.triggered.get("app_id") == mock_app.id
        assert stub.triggered.get("user_id") == account.id
        assert stub.triggered.get("query") == message.query
        assert stub.triggered.get("answer") is not None


class TestChatRunnerProceduralMemory:
    @pytest.mark.asyncio
    async def test_tools_injected_when_long_term_memory_enabled(self, monkeypatch):
        captured = {}

        class CapturingAgent(FakeAgent):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured["agent_config"] = kwargs.get("agent_config")

            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        stub = StubProvider(
            procedural_instructions="回答用户时先给结论再给细节",
            tools=_stub_tools(("search_memory", "write_memory", "update_memory", "forget_memory")),
        )
        runner, _ = _make_runner(monkeypatch, stub_provider=stub, agent_class=CapturingAgent)
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": True}

        [e async for e in runner.run(
            app=MagicMock(id=uuid4()),
            app_config=config,
            conversation=conversation,
            message=message,
            account=MagicMock(id=uuid4()),
            invoke_from=InvokeFrom.WEB_APP,
        )]

        # 记忆工具已注入（MemoryTools.get_tools 返回 4 个工具）
        injected_names = {t.name for t in captured["agent_config"].tools}
        assert {"search_memory", "write_memory", "update_memory", "forget_memory"} <= injected_names
        # 程序记忆注入 system prompt
        assert "先给结论再给细节" in captured["input"].get("procedural_instructions", "")


class TestChatRunnerMemoryProvider:
    @pytest.mark.asyncio
    async def test_run_reads_and_writes_through_resolved_provider(self, monkeypatch):
        captured = {}

        class CapturingAgent(FakeAgent):
            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        stub = StubProvider(
            episodic_memory="用户正在准备搬家到北京",
            procedural_instructions="先给结论",
            tools=_stub_tools(("search_memory",)),
        )
        runner, _ = _make_runner(monkeypatch, stub_provider=stub, agent_class=CapturingAgent)
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="北京天气怎么样", image_urls=[])

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": True}

        [e async for e in runner.run(
            app=MagicMock(id=uuid4()),
            app_config=config,
            conversation=conversation,
            message=message,
            account=MagicMock(id=uuid4()),
            invoke_from=InvokeFrom.WEB_APP,
        )]
        await _drain_bg_tasks()

        assert "用户正在准备搬家到北京" in captured["input"].get("episodic_memory", "")
        assert captured["input"].get("procedural_instructions") == "先给结论"
        assert stub.triggered is not None
        assert stub.triggered.get("app_id") is not None

    @pytest.mark.asyncio
    async def test_write_not_triggered_when_memory_disabled(self, monkeypatch):
        """写侧随 enable 门控：长期记忆关闭时 trigger_write 不得触发（与旧行为一致）"""
        stub = StubProvider(episodic_memory="用户正在准备搬家到北京")
        runner, _ = _make_runner(monkeypatch, stub_provider=stub, agent_class=FakeAgent)
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="北京天气怎么样", image_urls=[])

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": False}

        [e async for e in runner.run(
            app=MagicMock(id=uuid4()),
            app_config=config,
            conversation=conversation,
            message=message,
            account=MagicMock(id=uuid4()),
            invoke_from=InvokeFrom.WEB_APP,
        )]

        assert stub.triggered is None, "长期记忆关闭时不应触发写侧 trigger_write"

    @pytest.mark.asyncio
    async def test_write_triggered_when_memory_enabled(self, monkeypatch):
        """写侧随 enable 门控：长期记忆开启时 trigger_write 触发并携带 app_id"""
        stub = StubProvider(episodic_memory="用户正在准备搬家到北京")
        runner, _ = _make_runner(monkeypatch, stub_provider=stub, agent_class=FakeAgent)
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="北京天气怎么样", image_urls=[])
        app_id = uuid4()

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": True}

        [e async for e in runner.run(
            app=MagicMock(id=app_id),
            app_config=config,
            conversation=conversation,
            message=message,
            account=MagicMock(id=uuid4()),
            invoke_from=InvokeFrom.WEB_APP,
        )]
        await _drain_bg_tasks()

        assert stub.triggered is not None, "长期记忆开启时应触发写侧 trigger_write"
        assert stub.triggered.get("app_id") == app_id


def test_chat_runner_run_is_async_generator():
    """run() 应为 async generator（async def + yield），供 StreamingResponse 直接消费"""
    import inspect

    assert inspect.isasyncgenfunction(ChatRunner.run)
    assert not inspect.iscoroutinefunction(ChatRunner.run)
