"""ChatRunner 编排器分支 async 化测试——orchestrator_config.enable 时选择 OrchestratorAgent"""
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.service import ChatRunner
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
    features = (ModelFeature.TOOL_CALL,)
    context_window = None
    max_tokens = 8192

    def convert_to_human_message(self, query, image_urls=None):
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=query)


class CapturingOrchestrator:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        captured_agent["instance"] = self

    def stream(self, input, **kwargs):
        captured["input"] = input
        yield AgentThought(
            id=uuid4(), task_id=uuid4(), event=QueueEvent.SUB_TASK_PLAN,
            thought='[]', message=[],
        )
        yield AgentThought(
            id=uuid4(), task_id=uuid4(), event=QueueEvent.AGENT_MESSAGE,
            thought="汇总", message=[], answer="汇总",
            sub_task_id=uuid4(), sub_task_title="子任务",
        )
        yield AgentThought(id=uuid4(), task_id=uuid4(), event=QueueEvent.AGENT_END)


captured = {}
captured_agent = {}

MOCK_CONFIG = {
    "model_config": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    "dialog_round": 5, "tools": [], "datasets": [], "workflows": [], "skills": [],
    "preset_prompt": "", "long_term_memory": {"enable": False}, "review_config": {},
    "orchestrator_config": {"enable": True, "resume_mode": "auto"},
}


def _make_runner(monkeypatch) -> ChatRunner:
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
    runner.conversation_service.save_agent_thoughts = AsyncMock()
    runner.memory_provider_resolver.resolve = AsyncMock(return_value=StubProvider())
    monkeypatch.setattr("internal.service.chat_runner.OrchestratorAgent", CapturingOrchestrator)
    return runner


@pytest.mark.asyncio
async def test_chat_runner_selects_orchestrator_and_injects_input(monkeypatch):
    captured.clear()
    captured_agent.clear()
    runner = _make_runner(monkeypatch)
    account = MagicMock(id=uuid4())
    conversation = MagicMock(id=uuid4(), summary="")
    # attachment_text 显式置空：MagicMock 属性缺省为真值，会触发附件拼接污染 query
    message = MagicMock(id=uuid4(), query="写报告", image_urls=[], resume_trigger=False, attachment_text="")

    mock_app = MagicMock(id=uuid4(), app_type="orchestrator")
    events = [e async for e in runner.run(
        app=mock_app,
        app_config=dict(MOCK_CONFIG),
        conversation=conversation, message=message, account=account,
        invoke_from=InvokeFrom.DEBUGGER,
    )]

    assert captured["input"]["conversation_id"] == conversation.id
    assert captured["input"]["app_id"] == mock_app.id
    assert captured["input"]["message_id"] == message.id
    assert captured["input"]["query"] == "写报告"
    assert captured["input"]["resume_trigger"] is False
    assert captured_agent["instance"].kwargs["agent_config"].orchestrator_config["enable"] is True
    sse = "\n".join(events)
    assert '"sub_task_id"' in sse
    assert '"sub_task_id": "' in sse  # 非 null：成功路径真的序列化了 UUID（区分被异常兜底掩盖的崩溃）
    assert '"sub_task_title"' in sse


@pytest.mark.asyncio
async def test_agent_type_app_with_enable_uses_orchestrator(monkeypatch):
    """任务编排不再按 app_type 写死：agent 类型应用开启编排同样走 OrchestratorAgent（LLM 自判断拆解/直答）"""
    captured.clear()
    captured_agent.clear()
    runner = _make_runner(monkeypatch)
    account = MagicMock(id=uuid4())
    conversation = MagicMock(id=uuid4(), summary="")
    message = MagicMock(id=uuid4(), query="写报告", image_urls=[], resume_trigger=False, attachment_text="")

    # 关键：app_type=agent（旧门控会走 FunctionCallAgent，新门控只看 orchestrator_config.enable）
    mock_app = MagicMock(id=uuid4(), app_type="agent")
    events = [e async for e in runner.run(
        app=mock_app,
        app_config=dict(MOCK_CONFIG),
        conversation=conversation, message=message, account=account,
        invoke_from=InvokeFrom.DEBUGGER,
    )]

    assert captured_agent["instance"].kwargs["agent_config"].orchestrator_config["enable"] is True
    assert captured["input"]["app_id"] == mock_app.id
    assert '"sub_task_id"' in "\n".join(events)
