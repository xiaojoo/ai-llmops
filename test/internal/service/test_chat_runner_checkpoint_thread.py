import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.exception import ForbiddenException, ValidateException
from internal.service.chat_runner import ChatRunner


def _runner():
    return ChatRunner(
        db=MagicMock(),
        retrieval_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        memory_provider_resolver=MagicMock(),
    )


@pytest.mark.asyncio
async def test_checkpoint_thread_uses_current_message_for_new_run():
    runner = _runner()
    message = SimpleNamespace(id=uuid.uuid4(), resume_trigger=False, resume_message_id=None)
    assert await runner._resolve_checkpoint_thread_id(
        message, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4()),
    ) == str(message.id)


@pytest.mark.asyncio
async def test_checkpoint_thread_uses_owned_original_message_on_resume():
    runner = _runner()
    account = SimpleNamespace(id=uuid.uuid4())
    conversation = SimpleNamespace(id=uuid.uuid4())
    original = SimpleNamespace(id=uuid.uuid4(), conversation_id=conversation.id, created_by=account.id)
    runner.db.get = AsyncMock(return_value=original)
    message = SimpleNamespace(
        id=uuid.uuid4(), resume_trigger=True, resume_message_id=original.id,
    )
    assert await runner._resolve_checkpoint_thread_id(message, conversation, account) == str(original.id)


@pytest.mark.asyncio
async def test_checkpoint_thread_requires_original_message_on_resume():
    runner = _runner()
    message = SimpleNamespace(id=uuid.uuid4(), resume_trigger=True, resume_message_id=None)
    with pytest.raises(ValidateException):
        await runner._resolve_checkpoint_thread_id(
            message, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_checkpoint_thread_rejects_other_users_message():
    runner = _runner()
    account = SimpleNamespace(id=uuid.uuid4())
    conversation = SimpleNamespace(id=uuid.uuid4())
    runner.db.get = AsyncMock(return_value=SimpleNamespace(
        id=uuid.uuid4(), conversation_id=conversation.id, created_by=uuid.uuid4(),
    ))
    message = SimpleNamespace(
        id=uuid.uuid4(), resume_trigger=True, resume_message_id=uuid.uuid4(),
    )
    with pytest.raises(ForbiddenException):
        await runner._resolve_checkpoint_thread_id(message, conversation, account)
