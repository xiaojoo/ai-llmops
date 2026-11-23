#!/usr/bin/env python
"""应用逻辑删除测试：delete_app 置 is_deleted 而非物理删除，查询侧过滤已删除应用

async 化——db_session async fixture，BaseService CRUD 全 await，PaginatorReq 已 Pydantic 化。
"""
import uuid
from unittest.mock import MagicMock

import pytest

from internal.entity.app_entity import AppStatus
from internal.exception import NotFoundException
from internal.model import App
from internal.service.app_service import AppService
from internal.service.web_app_service import WebAppService

APP_SERVICE_DEPS = [
    "conversation_service", "builtin_provider_manager", "api_provider_manager",
    "retrieval_service", "redis_client", "cos_service", "app_config_service",
    "language_model_service", "language_model_manager", "chat_runner",
    "memory_provider_resolver",
]


def _app_service(db) -> AppService:
    return AppService(db=db, **{d: MagicMock() for d in APP_SERVICE_DEPS})


async def _create_app(db, account_id, **kwargs) -> App:
    service = _app_service(db)
    return await service.create(
        App,
        name=kwargs.get("name", "逻辑删除测试应用"),
        icon=kwargs.get("icon", "https://example.com/icon.png"),
        description=kwargs.get("description", ""),
        account_id=account_id,
        created_by=str(account_id),  # created_by 为 VARCHAR
        updated_by=str(account_id),
        status=kwargs.get("status", AppStatus.DRAFT),
        app_type=kwargs.get("app_type", "agent"),
    )


@pytest.mark.asyncio
async def test_delete_app_sets_is_deleted_not_physical_delete(db_session):
    """delete_app 后记录仍在且 is_deleted=True；get_app 对已删除应用抛 NotFound"""
    service = _app_service(db_session)
    account = MagicMock(id=uuid.uuid4())
    app_row = await _create_app(db_session, account.id)

    await service.delete_app(app_row.id, account)

    row = await db_session.get(App, app_row.id)
    assert row is not None, "逻辑删除不应物理删除记录"
    assert row.is_deleted is True

    try:
        await service.get_app(app_row.id, account)
        raise AssertionError("已删除应用应抛出 NotFoundException")
    except NotFoundException:
        pass


@pytest.mark.asyncio
async def test_get_apps_with_page_excludes_deleted(db_session):
    """列表查询过滤已删除应用"""
    from internal.schema.app_schema import GetAppsWithPageReq

    service = _app_service(db_session)
    account = MagicMock(id=uuid.uuid4())
    keep = await _create_app(db_session, account.id, name="保留应用")
    await _create_app(db_session, account.id, name="待删除应用")
    await service.delete_app((await _create_app(db_session, account.id, name="删除目标")).id, account)

    req = GetAppsWithPageReq()
    req.current_page = 1
    req.page_size = 20
    req.search_word = ""
    apps, _ = await service.get_apps_with_page(req, account)

    ids = [a.id for a in apps]
    assert keep.id in ids
    assert "删除目标" not in [a.name for a in apps]


@pytest.mark.asyncio
async def test_get_web_app_excludes_deleted(db_session):
    """WebApp 按 token 获取时过滤已删除应用"""
    account_id = uuid.uuid4()
    app_row = await _create_app(db_session, account_id, status=AppStatus.PUBLISHED)
    service = _app_service(db_session)
    await service.update(app_row, token="test-token-xyz", status=AppStatus.PUBLISHED)

    web_service = WebAppService(
        db=db_session, retrieval_service=MagicMock(), app_service=MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(), language_model_service=MagicMock(),
        chat_runner=MagicMock(), memory_provider_resolver=MagicMock(),
        attachment_service=MagicMock(),
    )

    found = await web_service.get_web_app("test-token-xyz")
    assert found.id == app_row.id

    await service.update(app_row, is_deleted=True)
    try:
        await web_service.get_web_app("test-token-xyz")
        raise AssertionError("已删除应用的 token 不应可访问")
    except NotFoundException:
        pass
