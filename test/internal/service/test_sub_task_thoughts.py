import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from internal.model import Conversation, Message, MessageAgentThought
from internal.service import ConversationService as CS


@pytest.mark.asyncio
async def test_save_agent_thoughts_persists_sub_task_events(db_session):
    # ConversationService 的 dataclass 需要 language_model_service / reflection_service
    # 两个协作对象；本测试路径（SUB_TASK_* 事件）不会触达它们，用 MagicMock 即可
    service = CS(db=db_session, language_model_service=MagicMock(), reflection_service=MagicMock())
    account_id = uuid.uuid4()
    app_id = uuid.uuid4()
    conversation = await service.create(
        Conversation, app_id=app_id, name="测试", invoke_from=InvokeFrom.DEBUGGER,
        created_by=str(account_id), updated_by=str(account_id),
    )
    message = await service.create(
        Message, app_id=app_id, conversation_id=conversation.id,
        query="写报告", created_by=str(account_id), updated_by=str(account_id),
    )
    sub_task_id = uuid.uuid4()
    thoughts = [
        AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.SUB_TASK_PLAN,
                     thought='[{"title": "调研"}]', message=[]),
        AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.SUB_TASK_START,
                     thought="调研员", sub_task_id=sub_task_id, sub_task_title="调研", message=[]),
        AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.SUB_TASK_END,
                     observation="完成", latency=1.2, sub_task_id=sub_task_id, sub_task_title="调研", message=[]),
    ]
    await service.save_agent_thoughts(
        account_id=account_id, app_id=app_id, app_config={},
        conversation_id=conversation.id, message_id=message.id,
        agent_thoughts=thoughts, invoke_from=InvokeFrom.DEBUGGER,
    )
    stmt = (
        select(MessageAgentThought)
        .where(MessageAgentThought.message_id == message.id)
        .order_by(MessageAgentThought.position)
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    assert len(rows) == 3
    start_row = rows[1]
    assert start_row.sub_task_id == sub_task_id
    assert start_row.sub_task_title == "调研"
