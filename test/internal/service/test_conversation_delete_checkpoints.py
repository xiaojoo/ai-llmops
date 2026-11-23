"""delete_conversation 级联清理子任务断点（async 化）。

SubTaskService 本体仍为同步 + Flask-SQLAlchemy，无法在 AsyncSession 上直跑；
此处以类级 monkeypatch 替身注入 clear_checkpoints，验证 conversation_service 的级联调用契约。
"""
import uuid
from unittest.mock import MagicMock

import pytest

from internal.model import Conversation
from internal.service import ConversationService, SubTaskService
from internal.entity.conversation_entity import InvokeFrom


@pytest.mark.asyncio
async def test_delete_conversation_clears_checkpoints(db_session, monkeypatch):
    account_id = uuid.uuid4()
    app_id = uuid.uuid4()

    # SubTaskService 仍同步，类级替身：记录 clear_checkpoints 调用，避免 Flask db.session 依赖
    cleared = []
    monkeypatch.setattr(
        SubTaskService, "clear_checkpoints",
        lambda self, message_id=None, conversation_id=None: cleared.append(
            conversation_id if conversation_id is not None else message_id
        ),
    )

    conv_service = ConversationService(
        db=db_session,
        language_model_service=MagicMock(),
        reflection_service=MagicMock(),
    )
    conversation = await conv_service.create(
        Conversation, app_id=app_id, name="测试", invoke_from=InvokeFrom.DEBUGGER,
        created_by=account_id, updated_by=account_id,
    )

    await conv_service.delete_conversation(
        conversation.id, account=type("A", (), {"id": account_id})()
    )

    assert (await db_session.get(Conversation, conversation.id)).is_deleted is True
    assert cleared == [conversation.id], "delete_conversation 应级联调用 clear_checkpoints"


@pytest.mark.asyncio
async def test_delete_message_clears_checkpoints(db_session, monkeypatch):
    """删除消息同样级联清理会话断点"""
    from internal.model import Message

    account_id = uuid.uuid4()
    app_id = uuid.uuid4()

    cleared = []
    monkeypatch.setattr(
        SubTaskService, "clear_checkpoints",
        lambda self, message_id=None, conversation_id=None: cleared.append(
            conversation_id if conversation_id is not None else message_id
        ),
    )

    conv_service = ConversationService(
        db=db_session,
        language_model_service=MagicMock(),
        reflection_service=MagicMock(),
    )
    conversation = await conv_service.create(
        Conversation, app_id=app_id, name="测试", invoke_from=InvokeFrom.DEBUGGER,
        created_by=account_id, updated_by=account_id,
    )
    message = await conv_service.create(
        Message, app_id=app_id, conversation_id=conversation.id,
        invoke_from=InvokeFrom.DEBUGGER, created_by=account_id, updated_by=account_id,
        query="q", status="normal",
    )

    await conv_service.delete_message(
        conversation.id, message.id, account=type("A", (), {"id": account_id})()
    )

    assert (await db_session.get(Message, message.id)).is_deleted is True
    assert cleared == [message.id], "delete_message 应级联调用 clear_checkpoints（按消息清理）"
