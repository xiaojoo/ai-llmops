#!/usr/bin/env python
"""AssistantAgentService async 化测试——非 chat 路径（消息分页 + 会话 get-or-create + delete_conversation）。

chat() 为 chat 链（依赖 FunctionCallAgent/TokenBufferMemory），当前保持同步 + TODO(plan2-chat)，
此处断言其仍为同步函数且带 TODO 标记。
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.entity.conversation_entity import InvokeFrom, MessageStatus
from internal.model import Account, Conversation, Message
from internal.service.assistant_agent_service import AssistantAgentService


def _svc(db) -> AssistantAgentService:
    return AssistantAgentService(
        db=db,
        chroma_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        attachment_service=MagicMock(),
    )


from package.paginator import PaginatorReq


class _PageReq:
    """PaginatorReq 已转 Pydantic —— 用真实 PaginatorReq + created_at 原始值。"""

    def __init__(self, current_page=1, page_size=10, created_at=None):
        self._req = PaginatorReq(current_page=current_page, page_size=page_size)
        self.current_page = self._req.current_page
        self.page_size = self._req.page_size
        self.created_at = created_at


@pytest.mark.asyncio
async def test_get_conversation_messages_with_page_creates_conversation(db_session):
    """会话缺失时创建（原 Account.assistant_agent_conversation 属性语义）并回填 account"""
    account = Account(name="t", email="t@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _svc(db_session)

    messages, paginator = await svc.get_conversation_messages_with_page(_PageReq(), account)

    assert messages == []
    assert paginator.total_record == 0
    assert account.assistant_agent_conversation_id is not None, "会话应创建并回填账号"
    conv = await db_session.get(Conversation, account.assistant_agent_conversation_id)
    assert conv.invoke_from == InvokeFrom.ASSISTANT_AGENT.value


@pytest.mark.asyncio
async def test_get_conversation_messages_with_page_filters_and_paginates(db_session):
    account = Account(name="t2", email="t2@t.com")
    db_session.add(account)
    await db_session.flush()
    conversation = Conversation(
        app_id=str(uuid4()), name="New Conversation",
        invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        created_by=account.id, updated_by=account.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    account.assistant_agent_conversation_id = conversation.id
    for i in range(3):
        db_session.add(Message(
            app_id=conversation.app_id, conversation_id=conversation.id,
            created_by=account.id, updated_by=account.id,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
            query=f"q{i}", answer=f"a{i}", status=MessageStatus.NORMAL.value,
        ))
    # 空 answer 的消息应被过滤（Message.answer != ""）
    db_session.add(Message(
        app_id=conversation.app_id, conversation_id=conversation.id,
        created_by=account.id, updated_by=account.id,
        invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        query="q3", answer="", status=MessageStatus.NORMAL.value,
    ))
    await db_session.flush()

    svc = _svc(db_session)
    messages, paginator = await svc.get_conversation_messages_with_page(_PageReq(), account)

    assert paginator.total_record == 3, "空 answer 消息应被过滤"
    assert len(messages) == 3
    assert paginator.total_page == 1
    assert {m.query for m in messages} == {"q0", "q1", "q2"}


@pytest.mark.asyncio
async def test_delete_conversation_clears_account_id(db_session):
    account = Account(name="t3", email="t3@t.com", assistant_agent_conversation_id=uuid4())
    db_session.add(account)
    await db_session.flush()
    svc = _svc(db_session)

    await svc.delete_conversation(account)

    assert account.assistant_agent_conversation_id is None


def test_chat_is_async_after_t8():
    """chat() 已 async 化（async def + async generator）"""
    import inspect

    # chat() is `async def` returning an AsyncGenerator
    # For class methods, check the unwrapped function via __func__
    method = AssistantAgentService.chat
    assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method), \
        "chat() 应为 async def"
