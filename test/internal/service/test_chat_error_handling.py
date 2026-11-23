#!/usr/bin/env python
"""
debug_chat / web_app_chat 生产缺陷修复的单元测试（async 化）：
1. agent.stream 抛异常时：产出 error 事件、save_agent_thoughts 收到 ERROR thought 并携带正确 invoke_from
2. get_or_create_debug_conversation 按账号隔离
3. save_agent_thoughts 对 ERROR 事件更新消息状态为 error
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.model import App, Conversation, Message
from internal.service import ConversationService
from internal.service.app_service import AppService
from internal.service.web_app_service import WebAppService
from internal.service.memory_provider.base import MemoryReadContext


class StubProvider:
    def get_user_profile(self, app_config, app_id, user_id):
        return ""

    async def get_read_context(self, app_config, app_id, user_id, query):
        return MemoryReadContext()

    async def get_memory_tools(self, app_config, app_id, user_id):
        return []

    async def trigger_write(self, **kwargs):
        return None


class FakeLLM:
    """模拟支持 tool_call 的 LLM"""
    features = (ModelFeature.TOOL_CALL,)
    # 与 BaseLanguageModel 字段保持一致：上下文窗口未知为 None，输出上限默认 8192
    context_window = None
    max_tokens = 8192

    def convert_to_human_message(self, query, image_urls=None):
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=query)


class FakeAgent:
    """模拟 agent：stream 直接抛异常，用于验证异常兜底逻辑"""

    def __init__(self, *args, **kwargs):
        pass

    def stream(self, *args, **kwargs):
        raise RuntimeError("模拟LLM调用失败")


MOCK_DRAFT_CONFIG = {
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

APP_SERVICE_DEPS = [
    "conversation_service", "builtin_provider_manager", "api_provider_manager",
    "retrieval_service", "redis_client", "cos_service", "app_config_service",
    "language_model_service", "language_model_manager", "chat_runner",
    "memory_provider_resolver",
]


def _app_service(db=None) -> AppService:
    deps = {d: MagicMock() for d in APP_SERVICE_DEPS}
    svc = AppService(db=db or MagicMock(), attachment_service=MagicMock(), **deps)
    return svc


def _web_app_service(db=None) -> WebAppService:
    svc = WebAppService(
        db=db or MagicMock(),
        retrieval_service=MagicMock(),
        app_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        chat_runner=MagicMock(),
        memory_provider_resolver=MagicMock(),
        attachment_service=MagicMock(),
    )
    # prepare_web_app_chat 在 Agent 循环前 await self.db.commit()
    svc.db.commit = AsyncMock()
    return svc


def _stub_chat_runner(monkeypatch, service, *, agent_class=FakeAgent, saved=None):
    """把 service.chat_runner 替换为真实 ChatRunner（mock 依赖 + 替身化），使 run() 执行真实逻辑"""
    from internal.service.chat_runner import ChatRunner

    runner = ChatRunner(
        db=MagicMock(),
        retrieval_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        memory_provider_resolver=MagicMock(),
    )
    # run() 在 Agent 循环前 await self.db.commit()
    runner.db.commit = AsyncMock()
    runner.language_model_service.load_language_model = AsyncMock(return_value=FakeLLM())
    runner.app_config_service.get_langchain_tools_by_tools_config = AsyncMock(return_value=[])
    runner._build_history = AsyncMock(return_value=[])
    runner.conversation_service.compact_if_needed = AsyncMock(return_value=False)

    def _fake_save(**kwargs):
        if saved is not None:
            saved.update(kwargs)
    runner.conversation_service.save_agent_thoughts = AsyncMock(side_effect=_fake_save)

    runner.memory_provider_resolver.resolve = AsyncMock(return_value=StubProvider())
    monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", agent_class)
    service.chat_runner = runner
    return runner


async def _collect_async(agen):
    return [e async for e in agen]


def _error_payload(last_event: str) -> dict:
    """从 SSE 最后一个事件中解析 data 部分（JSON）。帧含 id: 头行。"""
    data_line = next(
        (l for l in last_event.split("\n") if l.startswith("data: ")),
        None,
    )
    assert data_line is not None, f"SSE 帧缺少 data 行: {last_event!r}"
    return json.loads(data_line[len("data: "):])


class TestDebugChatErrorHandling:
    @pytest.mark.asyncio
    async def test_stream_exception_produces_error_event_and_persists(self, monkeypatch):
        service = _app_service()
        account = MagicMock(id=uuid4())
        app_id = uuid4()
        conv = MagicMock(id=uuid4())
        message = MagicMock(id=uuid4())

        service.get_app = AsyncMock(return_value=MagicMock(id=app_id))
        service.get_draft_app_config = AsyncMock(return_value=dict(MOCK_DRAFT_CONFIG))
        service.get_or_create_debug_conversation = AsyncMock(return_value=conv)
        service.create = AsyncMock(return_value=message)
        # attachment_service.load_attachments 已 async——需 AsyncMock（await 解包）
        service.attachment_service.load_attachments = AsyncMock(return_value=([], ""))

        saved = {}
        _stub_chat_runner(monkeypatch, service, agent_class=FakeAgent, saved=saved)

        req = SimpleNamespace(
            query="你好", image_urls=[], file_ids=[], resume=False, resume_message_id="",
        )
        events = [e async for e in service.debug_chat(app_id, req, account)]

        # 1、产出 error 事件
        last_event = events[-1]
        assert "event: error" in last_event, f"最后一个事件应为 error，实际: {last_event[:100]}"
        payload = _error_payload(last_event)
        assert payload["event"] == "error"
        assert "模拟LLM调用失败" in payload["observation"]

        # 2、save_agent_thoughts 收到 ERROR thought + 正确 invoke_from
        assert saved.get("invoke_from") == InvokeFrom.DEBUGGER
        thoughts = saved.get("agent_thoughts", [])
        assert thoughts, "应传入至少一个 agent_thought"
        assert thoughts[-1].event == QueueEvent.ERROR
        assert "模拟LLM调用失败" in thoughts[-1].observation


class TestWebAppChatErrorHandling:
    @pytest.mark.asyncio
    async def test_stream_exception_produces_error_event_and_persists(self, monkeypatch):
        service = _web_app_service()
        account = MagicMock(id=uuid4())
        token = "test-token"
        app_id = uuid4()
        conv = MagicMock(id=uuid4())
        message = MagicMock(id=uuid4())

        service.get_web_app = AsyncMock(return_value=MagicMock(id=app_id))
        service.create = AsyncMock(side_effect=lambda *a, **k: conv if k.get("name") else message)
        service.app_config_service.get_app_config = AsyncMock(return_value=dict(MOCK_DRAFT_CONFIG))
        service.attachment_service.load_attachments = AsyncMock(return_value=([], ""))

        saved = {}
        _stub_chat_runner(monkeypatch, service, agent_class=FakeAgent, saved=saved)

        req = SimpleNamespace(
            query="你好",
            image_urls=[],
            conversation_id=None,
            file_ids=[],
            resume=False,
            resume_message_id="",
            mode="chat",
            project_root="",
        )

        events = [e async for e in service.web_app_chat(token, req, account)]

        # 1、产出 error 事件
        last_event = events[-1]
        assert "event: error" in last_event, f"最后一个事件应为 error，实际: {last_event[:100]}"
        payload = _error_payload(last_event)
        assert payload["event"] == "error"
        assert "模拟LLM调用失败" in payload["observation"]

        # 2、save_agent_thoughts 收到 ERROR thought + 正确 invoke_from（WebApp 应为 WEB_APP）
        assert saved.get("invoke_from") == InvokeFrom.WEB_APP
        thoughts = saved.get("agent_thoughts", [])
        assert thoughts, "应传入至少一个 agent_thought"
        assert thoughts[-1].event == QueueEvent.ERROR


class TestDebugConversationAccountIsolation:
    @pytest.mark.asyncio
    async def test_conversation_is_isolated_by_account(self, db_session):
        service = _app_service(db=db_session)
        owner_id = uuid4()
        account_a = MagicMock(id=uuid4())
        account_b = MagicMock(id=uuid4())

        app_record = App(account_id=owner_id, name="隔离测试应用", icon="", created_by="", updated_by="")
        db_session.add(app_record)
        await db_session.flush()

        # 同一账号：复用同一会话
        conv_a1 = await service.get_or_create_debug_conversation(app_record, account_a)
        conv_a2 = await service.get_or_create_debug_conversation(app_record, account_a)
        assert conv_a1.id == conv_a2.id, "同一账号应复用同一调试会话"
        assert conv_a1.created_by == account_a.id

        # 不同账号：各自独立会话
        conv_b = await service.get_or_create_debug_conversation(app_record, account_b)
        assert conv_b.id != conv_a1.id, "不同账号应拥有独立调试会话"
        assert conv_b.created_by == account_b.id

        # 两个会话都属于同一应用且均为调试会话
        assert conv_a1.app_id == app_record.id
        assert conv_b.app_id == app_record.id


class TestSaveAgentThoughtsErrorStatus:
    @pytest.mark.asyncio
    async def test_error_event_updates_message_status(self, db_session):
        service = ConversationService(
            db=db_session,
            language_model_service=MagicMock(),
            reflection_service=MagicMock(),
        )
        user_id = uuid4()
        app_id = uuid4()

        conv = Conversation(
            app_id=app_id,
            created_by=user_id,
            updated_by=user_id,
            name="测试会话",
            invoke_from=InvokeFrom.WEB_APP,
        )
        db_session.add(conv)
        await db_session.flush()

        msg = Message(
            app_id=app_id,
            conversation_id=conv.id,
            created_by=user_id,
            updated_by=user_id,
            invoke_from=InvokeFrom.WEB_APP,
            query="你好",
        )
        db_session.add(msg)
        await db_session.flush()

        error_thought = AgentThought(
            id=uuid4(),
            task_id=uuid4(),
            event=QueueEvent.ERROR,
            observation="推理过程发生异常：boom",
        )

        await service.save_agent_thoughts(
            account_id=user_id,
            app_id=app_id,
            app_config={"long_term_memory": {"enable": False}},
            conversation_id=conv.id,
            message_id=msg.id,
            agent_thoughts=[error_thought],
            invoke_from=InvokeFrom.WEB_APP,
        )

        await db_session.refresh(msg)
        assert msg.status == "error", f"消息状态应更新为 error，实际: {msg.status}"
        assert msg.error == "推理过程发生异常：boom"
