#!/usr/bin/env python
"""插件兜底 bootstrap_web_app 测试：
- 已有已发布应用 → 复用（不新建），返回其 token；
- 没有已发布应用 → 走创建+发布+生成 token 路径。
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.entity.app_entity import AppStatus
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
        name=kwargs.get("name", "bootstrap 测试应用"),
        icon=kwargs.get("icon", "https://example.com/icon.png"),
        description=kwargs.get("description", ""),
        account_id=account_id,
        created_by=str(account_id),
        updated_by=str(account_id),
        status=kwargs.get("status", AppStatus.DRAFT),
        app_type=kwargs.get("app_type", "agent"),
    )


def _web_app_service(db, app_service=None) -> WebAppService:
    return WebAppService(
        db=db,
        retrieval_service=MagicMock(),
        app_service=app_service or MagicMock(),
        app_config_service=MagicMock(),
        conversation_service=MagicMock(),
        language_model_service=MagicMock(),
        chat_runner=MagicMock(),
        memory_provider_resolver=MagicMock(),
        attachment_service=MagicMock(),
    )


@pytest.mark.asyncio
async def test_bootstrap_reuses_existing_published_app(db_session):
    """已有已发布应用 → 复用，不新建，返回其 token。"""
    account_id = uuid.uuid4()
    app_row = await _create_app(db_session, account_id, status=AppStatus.PUBLISHED)
    app_service = MagicMock()
    app_service.get_token_with_default = AsyncMock(return_value="token-abc")

    info = await _web_app_service(db_session, app_service).bootstrap_web_app(
        MagicMock(id=account_id),
    )

    assert info["token"] == "token-abc"
    assert info["id"] == str(app_row.id)
    app_service.create_app.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_creates_when_no_published_app(db_session):
    """无已发布应用 → 创建 + 发布 + 生成 token。"""
    account_id = uuid.uuid4()
    created = await _create_app(db_session, account_id)  # DRAFT app row
    app_service = MagicMock()
    app_service.create_app = AsyncMock(return_value=created)
    app_service.publish_draft_app_config = AsyncMock()
    app_service.get_app = AsyncMock(return_value=created)
    app_service.get_token_with_default = AsyncMock(return_value="token-xyz")

    info = await _web_app_service(db_session, app_service).bootstrap_web_app(
        MagicMock(id=account_id),
    )

    app_service.create_app.assert_awaited_once()
    app_service.publish_draft_app_config.assert_awaited_once()
    app_service.get_token_with_default.assert_awaited_once()
    assert info["token"] == "token-xyz"
