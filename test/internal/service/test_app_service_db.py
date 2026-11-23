#!/usr/bin/env python
"""AppService 非 chat 路径 DB 行为测试（真实 Postgres，db_session 事务回滚隔离）。

覆盖 task brief 的 create_app/update_app/copy/delete/get_apps_with_page/draft/publish/fallback 等非 chat 路径。
req 用真实 Pydantic 模型（schema 已转 Pydantic，服务层消费属性访问）。
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from internal.entity.app_entity import AppConfigType, AppStatus
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import ForbiddenException, NotFoundException
from internal.model import Account, App, AppConfig, AppConfigVersion, AppDatasetJoin, Conversation
from internal.schema.app_schema import CreateAppReq, GetAppsWithPageReq
from internal.service.app_service import AppService

APP_SERVICE_DEPS = [
    "conversation_service", "builtin_provider_manager", "api_provider_manager",
    "retrieval_service", "redis_client", "cos_service", "app_config_service",
    "language_model_service", "language_model_manager", "chat_runner",
    "memory_provider_resolver",
]


def _app_service(db, **overrides) -> AppService:
    deps = {d: MagicMock() for d in APP_SERVICE_DEPS}
    deps.update(overrides)
    return AppService(db=db, attachment_service=MagicMock(), **deps)


def _create_app_req(**kwargs) -> CreateAppReq:
    defaults = {"name": "测试应用", "icon": "https://example.com/icon.png", "description": "描述", "app_type": "agent"}
    defaults.update(kwargs)
    return CreateAppReq(**defaults)


def _page_req(current_page=1, page_size=10, search_word="") -> GetAppsWithPageReq:
    return GetAppsWithPageReq(current_page=current_page, page_size=page_size, search_word=search_word)


_DRAFT_CONFIG = {
    "model_config": {"provider": "deepseek", "model": "deepseek-v4-flash", "parameters": {"temperature": 0.5}},
    "dialog_round": 5,
    "preset_prompt": "preset",
    "tools": [],
    "skills": [],
    "workflows": [],
    "retrieval_config": {},
    "long_term_memory": {},
    "opening_statement": "",
    "opening_questions": [],
    "speech_to_text": {},
    "text_to_speech": {},
    "suggested_after_answer": {},
    "review_config": {"enable": False},
    "orchestrator_config": {"enable": True, "max_sub_tasks": 3},
    "datasets": [],
}


@pytest.mark.asyncio
async def test_create_app_creates_app_and_draft(db_session):
    account = Account(name="t", email="t@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)

    app = await svc.create_app(_create_app_req(), account)

    assert app.account_id == account.id
    assert app.status == AppStatus.DRAFT
    assert app.draft_app_config_id is not None
    draft = await db_session.get(AppConfigVersion, app.draft_app_config_id)
    assert draft.config_type == AppConfigType.DRAFT.value
    assert draft.model_config["provider"] == "deepseek"


@pytest.mark.asyncio
async def test_get_app_permission_and_deleted(db_session):
    account = Account(name="t2", email="t2@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(name="可见应用"), account)

    # 权限校验：他人账号访问被拒
    with pytest.raises(ForbiddenException):
        await svc.get_app(app.id, MagicMock(id=uuid4()))

    # 逻辑删除后 get_app 抛 NotFound
    await svc.delete_app(app.id, account)
    assert app.is_deleted is True
    with pytest.raises(NotFoundException):
        await svc.get_app(app.id, account)


@pytest.mark.asyncio
async def test_update_app_updates_fields(db_session):
    account = Account(name="t3", email="t3@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(name="原名"), account)

    updated = await svc.update_app(app.id, account, name="新名")

    assert updated.name == "新名"
    assert (await db_session.get(App, app.id)).name == "新名"


@pytest.mark.asyncio
async def test_copy_app_copies_draft(db_session):
    account = Account(name="t4", email="t4@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(name="被拷贝应用"), account)

    new_app = await svc.copy_app(app.id, account)

    assert new_app.id != app.id
    assert new_app.name == app.name
    assert new_app.status == AppStatus.DRAFT
    assert new_app.draft_app_config_id is not None
    draft = await db_session.get(AppConfigVersion, new_app.draft_app_config_id)
    assert draft.config_type == AppConfigType.DRAFT.value
    assert draft.model_config == (await db_session.get(AppConfigVersion, app.draft_app_config_id)).model_config


@pytest.mark.asyncio
async def test_get_apps_with_page_excludes_deleted(db_session):
    account = Account(name="t5", email="t5@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    keep = await svc.create_app(_create_app_req(name="保留应用"), account)
    gone = await svc.create_app(_create_app_req(name="待删除应用"), account)
    await svc.delete_app(gone.id, account)

    apps, paginator = await svc.get_apps_with_page(_page_req(), account)

    ids = [a.id for a in apps]
    assert keep.id in ids
    assert gone.id not in ids
    assert paginator.total_record == 1


@pytest.mark.asyncio
async def test_publish_draft_app_config_full_flow(db_session):
    """发布全流程：运行时 AppConfig + 发布历史 + app 状态/关联更新"""
    account = Account(name="t6", email="t6@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(), account)
    svc.app_config_service.get_draft_app_config = AsyncMock(return_value=dict(_DRAFT_CONFIG))
    # 草稿记录为 orchestrator_config 权威来源（get_draft_app_config 透传真实草稿值）
    draft = await db_session.get(AppConfigVersion, app.draft_app_config_id)
    draft.orchestrator_config = {"enable": True, "max_sub_tasks": 3}
    await db_session.flush()

    published = await svc.publish_draft_app_config(app.id, account)

    assert published.status == AppStatus.PUBLISHED
    assert published.app_config_id is not None
    runtime = await db_session.get(AppConfig, published.app_config_id)
    assert runtime.orchestrator_config == {"enable": True, "max_sub_tasks": 3}
    # 发布历史 version=1
    versions = (await db_session.scalars(
        select(AppConfigVersion).where(
            AppConfigVersion.app_id == app.id,
            AppConfigVersion.config_type == AppConfigType.PUBLISHED,
        )
    )).all()
    assert len(versions) == 1
    assert versions[0].version == 1


@pytest.mark.asyncio
async def test_cancel_publish_app_config(db_session):
    account = Account(name="t7", email="t7@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(), account)
    svc.app_config_service.get_draft_app_config = AsyncMock(return_value=dict(_DRAFT_CONFIG))
    await svc.publish_draft_app_config(app.id, account)

    cancelled = await svc.cancel_publish_app_config(app.id, account)

    assert cancelled.status == AppStatus.DRAFT
    assert cancelled.app_config_id is None


@pytest.mark.asyncio
async def test_fallback_history_to_draft(db_session):
    account = Account(name="t8", email="t8@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(), account)
    svc.app_config_service.get_draft_app_config = AsyncMock(return_value=dict(_DRAFT_CONFIG))
    await svc.publish_draft_app_config(app.id, account)
    # 修改草稿，制造与发布历史的差异
    draft = await db_session.get(AppConfigVersion, app.draft_app_config_id)
    await svc.update(draft, preset_prompt="draft-changed")
    published_version = (await db_session.scalars(
        select(AppConfigVersion).where(
            AppConfigVersion.app_id == app.id,
            AppConfigVersion.config_type == AppConfigType.PUBLISHED,
        )
    )).one()

    restored = await svc.fallback_history_to_draft(app.id, published_version.id, account)

    assert restored.id == draft.id
    assert restored.preset_prompt == published_version.preset_prompt, "草稿应回退为发布历史的值"


@pytest.mark.asyncio
async def test_get_or_create_debug_conversation_and_delete(db_session):
    account = Account(name="t9", email="t9@t.com")
    db_session.add(account)
    await db_session.flush()
    svc = _app_service(db_session)
    app = await svc.create_app(_create_app_req(), account)

    conv = await svc.get_or_create_debug_conversation(app, account)
    assert conv.invoke_from == InvokeFrom.DEBUGGER.value
    # 二次调用复用同一会话
    assert (await svc.get_or_create_debug_conversation(app, account)).id == conv.id

    await svc.delete_debug_conversation(app.id, account)
    assert (await db_session.get(Conversation, conv.id)).is_deleted is True
