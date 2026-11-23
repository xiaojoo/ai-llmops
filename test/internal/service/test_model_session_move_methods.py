#!/usr/bin/env python
"""属性上移的服务方法验证：模型层查库属性已删除，新服务方法（async + 显式 AsyncSession）语义等价。

覆盖 docs/migration/model-session-callers.md 登记的映射；行数据在 db_session 事务内创建，
测试结束回滚不落库。AccountService/ApiKeyService 已 async 化——
方法并入 self.db（显式 db 参数移除）；其余服务类本体仍在逐步 async 化。
"""
from dataclasses import fields
from uuid import uuid4

import pytest

from internal.entity.app_entity import AppConfigType, AppStatus
from internal.entity.conversation_entity import InvokeFrom
from internal.model import (
    Account,
    ApiKey,
    App,
    AppConfigVersion,
    AppDatasetJoin,
    Conversation,
    Dataset,
    Document,
    Message,
    ProcessRule,
    Segment,
    UploadFile,
)
from internal.service.account_service import AccountService
from internal.service.api_key_service import ApiKeyService
from internal.service.app_service import AppService
from internal.service.conversation_service import ConversationService
from internal.service.dataset_service import DatasetService
from internal.service.document_service import DocumentService
from internal.service.segment_service import SegmentService


def _svc(cls, **overrides):
    """构造服务实例：新方法只依赖显式 db: AsyncSession 参数，其余依赖填 None。"""
    kwargs = {f.name: None for f in fields(cls)}
    kwargs.update(overrides)
    return cls(**kwargs)


@pytest.mark.asyncio
async def test_get_assistant_agent_conversation_creates_when_missing(db_session):
    account = Account(name="t", email="t@t.com")
    db_session.add(account)
    await db_session.flush()
    # 方法已并入 self.db（显式 db 参数随服务类 async 化移除）
    svc = _svc(AccountService, db=db_session)

    conversation = await svc.get_assistant_agent_conversation(
        account, assistant_agent_id=str(uuid4())
    )
    assert conversation is not None
    assert conversation.invoke_from == InvokeFrom.ASSISTANT_AGENT.value
    assert account.assistant_agent_conversation_id == conversation.id, "账号应回填 assistant_agent_conversation_id"


@pytest.mark.asyncio
async def test_get_assistant_agent_conversation_returns_existing(db_session):
    account = Account(name="t2", email="t2@t.com")
    db_session.add(account)
    await db_session.flush()
    existing = Conversation(
        app_id=str(uuid4()), name="New Conversation",
        invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
        created_by=account.id, updated_by=account.id,
    )
    db_session.add(existing)
    await db_session.flush()
    account.assistant_agent_conversation_id = existing.id
    svc = _svc(AccountService, db=db_session)

    conversation = await svc.get_assistant_agent_conversation(account)
    assert conversation.id == existing.id, "已存在会话应直接返回，不重复创建"


@pytest.mark.asyncio
async def test_api_key_get_account(db_session):
    account = Account(name="t3", email="t3@t.com")
    db_session.add(account)
    await db_session.flush()
    api_key = ApiKey(account_id=account.id, api_key="llmops-v1/test", is_active=True, remark="")
    db_session.add(api_key)
    await db_session.flush()
    svc = _svc(ApiKeyService, db=db_session)

    assert (await svc.get_account(api_key)).id == account.id


@pytest.mark.asyncio
async def test_dataset_counters(db_session):
    dataset = Dataset(account_id=uuid4(), name="d", icon="", description="")
    db_session.add(dataset)
    await db_session.flush()
    doc1 = Document(
        account_id=uuid4(), dataset_id=dataset.id,
        upload_file_id=uuid4(), process_rule_id=uuid4(), batch="", name="a.md",
    )
    doc2 = Document(
        account_id=uuid4(), dataset_id=dataset.id,
        upload_file_id=uuid4(), process_rule_id=uuid4(), batch="", name="b.md",
    )
    db_session.add_all([doc1, doc2])
    await db_session.flush()
    db_session.add_all([
        Segment(account_id=uuid4(), dataset_id=dataset.id, document_id=doc1.id,
                node_id=uuid4(), content="c1", character_count=10, hit_count=3),
        Segment(account_id=uuid4(), dataset_id=dataset.id, document_id=doc1.id,
                node_id=uuid4(), content="c2", character_count=20, hit_count=0),
    ])
    await db_session.flush()
    db_session.add(AppDatasetJoin(app_id=uuid4(), dataset_id=dataset.id))
    await db_session.flush()

    svc = _svc(DatasetService)
    assert await svc.get_document_count(dataset, db_session) == 2
    assert await svc.get_hit_count(dataset, db_session) == 3
    assert await svc.get_character_count(dataset, db_session) == 30
    assert await svc.get_related_app_count(dataset, db_session) == 1


@pytest.mark.asyncio
async def test_document_related(db_session):
    upload_file = UploadFile(
        account_id=uuid4(), name="a.md", key="k", size=10,
        extension=".md", mime_type="text/markdown", hash="h",
    )
    db_session.add(upload_file)
    await db_session.flush()
    process_rule = ProcessRule(account_id=uuid4(), dataset_id=uuid4(), mode="automic", rule={})
    db_session.add(process_rule)
    await db_session.flush()
    document = Document(
        account_id=uuid4(), dataset_id=uuid4(),
        upload_file_id=upload_file.id, process_rule_id=process_rule.id, batch="", name="a.md",
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add_all([
        Segment(account_id=uuid4(), dataset_id=document.dataset_id, document_id=document.id,
                node_id=uuid4(), content="c1", character_count=5, hit_count=1),
        Segment(account_id=uuid4(), dataset_id=document.dataset_id, document_id=document.id,
                node_id=uuid4(), content="c2", character_count=7, hit_count=2),
    ])
    await db_session.flush()

    svc = _svc(DocumentService)
    assert (await svc.get_upload_file(document, db_session)).id == upload_file.id
    assert (await svc.get_process_rule(document, db_session)).id == process_rule.id
    assert await svc.get_segment_count(document, db_session) == 2
    assert await svc.get_document_hit_count(document, db_session) == 3


@pytest.mark.asyncio
async def test_segment_get_document(db_session):
    document = Document(
        account_id=uuid4(), dataset_id=uuid4(),
        upload_file_id=uuid4(), process_rule_id=uuid4(), batch="", name="a.md",
    )
    db_session.add(document)
    await db_session.flush()
    segment = Segment(
        account_id=uuid4(), dataset_id=document.dataset_id, document_id=document.id,
        node_id=uuid4(), content="c",
    )
    db_session.add(segment)
    await db_session.flush()

    svc = _svc(SegmentService)
    assert (await svc.get_document(segment, db_session)).id == document.id


@pytest.mark.asyncio
async def test_conversation_is_new_and_message_conversation(db_session):
    account = Account(name="t4", email="t4@t.com")
    db_session.add(account)
    await db_session.flush()
    conversation = Conversation(
        app_id=uuid4(), name="c", invoke_from=InvokeFrom.DEBUGGER.value,
        created_by=account.id, updated_by=account.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    message = Message(
        created_by=account.id, updated_by=account.id, app_id=conversation.app_id,
        conversation_id=conversation.id, invoke_from=InvokeFrom.DEBUGGER.value, query="q",
    )
    db_session.add(message)
    await db_session.flush()

    svc = _svc(ConversationService)
    assert await svc.is_conversation_new(conversation, db_session) is True, "1 条消息应视为新会话"
    db_session.add(Message(
        created_by=account.id, updated_by=account.id, app_id=conversation.app_id,
        conversation_id=conversation.id, invoke_from=InvokeFrom.DEBUGGER.value, query="q2",
    ))
    await db_session.flush()
    assert await svc.is_conversation_new(conversation, db_session) is False, "2 条消息不应视为新会话"
    assert (await svc.get_message_conversation(message, db_session)).id == conversation.id


@pytest.mark.asyncio
async def test_app_config_and_draft(db_session):
    app = App(account_id=uuid4(), name="a", icon="", description="")
    db_session.add(app)
    await db_session.flush()
    svc = _svc(AppService, db=db_session)

    assert await svc.get_app_config(app) is None, "app_config_id 为空时应返回 None"
    draft = await svc.get_or_create_draft_app_config(app)
    assert draft.app_id == app.id and draft.config_type == AppConfigType.DRAFT.value
    again = await svc.get_or_create_draft_app_config(app)
    assert again.id == draft.id, "草稿已存在时不应重复创建"


@pytest.mark.asyncio
async def test_app_token_with_default(db_session):
    svc = _svc(AppService, db=db_session)
    unpublished = App(account_id=uuid4(), name="u", icon="", description="", token="t", status="draft")
    db_session.add(unpublished)
    await db_session.flush()
    assert await svc.get_token_with_default(unpublished) == ""
    assert unpublished.token is None, "非发布状态应清空 token"

    published = App(account_id=uuid4(), name="p", icon="", description="", status=AppStatus.PUBLISHED.value)
    db_session.add(published)
    await db_session.flush()
    token = await svc.get_token_with_default(published)
    assert token and len(token) == 16, "发布状态应生成 16 位 token"
    assert await svc.get_token_with_default(published) == token, "已生成 token 应复用"


@pytest.mark.asyncio
async def test_app_debug_conversation_and_dataset_joins(db_session):
    account = Account(name="t5", email="t5@t.com")
    db_session.add(account)
    await db_session.flush()
    conversation = Conversation(
        app_id=uuid4(), name="debug", invoke_from=InvokeFrom.DEBUGGER.value,
        created_by=account.id, updated_by=account.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    app = App(account_id=account.id, name="a2", icon="", description="", debug_conversation_id=conversation.id)
    db_session.add(app)
    await db_session.flush()
    app_config = AppConfigVersion(app_id=app.id, version=1, config_type=AppConfigType.PUBLISHED.value)
    db_session.add(app_config)
    await db_session.flush()
    db_session.add(AppDatasetJoin(app_id=app.id, dataset_id=uuid4()))
    db_session.add(AppDatasetJoin(app_id=app.id, dataset_id=uuid4()))
    await db_session.flush()

    svc = _svc(AppService, db=db_session)
    assert (await svc.get_debug_conversation(app)).id == conversation.id
    joins = await svc.get_app_dataset_joins(app_config)
    assert len(joins) == 2, "AppConfig.app_id 关联的 AppDatasetJoin 应全部返回"
