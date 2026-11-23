#!/usr/bin/env python
"""AppConfigService DB 行为测试——get_draft_app_config 创建/复用默认草稿 + 工具校验/剔除（真实 Postgres）。

覆盖 task brief 的 "app_config_service（tools 校验/转换）" 非 chat 路径。
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from internal.entity.app_entity import AppConfigType, DEFAULT_APP_CONFIG
from internal.model import Account, ApiTool, ApiToolProvider, App, AppConfigVersion
from internal.service.app_config_service import AppConfigService


def _svc(db) -> AppConfigService:
    return AppConfigService(
        db=db,
        api_provider_manager=MagicMock(),
        builtin_provider_manager=MagicMock(),
        language_model_manager=MagicMock(),
        language_model_service=MagicMock(),
    )


@pytest.mark.asyncio
async def test_get_draft_app_config_creates_default_draft_when_missing(db_session):
    """草稿缺失时创建默认草稿（原 App.draft_app_config 属性语义）并返回转换后的配置字典"""
    account = Account(name="t", email="t@t.com")
    db_session.add(account)
    await db_session.flush()
    app = App(account_id=account.id, name="a", icon="", description="")
    db_session.add(app)
    await db_session.flush()

    svc = _svc(db_session)
    result = await svc.get_draft_app_config(app)

    assert result["id"]
    assert result["orchestrator_config"]["enable"] is False  # DEFAULT_APP_CONFIG 默认编排器配置透传
    assert result["model_config"]["provider"] == "deepseek"
    drafts = (await db_session.scalars(
        select(AppConfigVersion).where(AppConfigVersion.app_id == app.id)
    )).all()
    assert len(drafts) == 1
    assert drafts[0].config_type == AppConfigType.DRAFT.value


@pytest.mark.asyncio
async def test_get_draft_app_config_reuses_existing_draft(db_session):
    """草稿已存在时不重复创建"""
    account = Account(name="t2", email="t2@t.com")
    db_session.add(account)
    await db_session.flush()
    app = App(account_id=account.id, name="a2", icon="", description="")
    db_session.add(app)
    await db_session.flush()
    draft = AppConfigVersion(app_id=app.id, version=0, config_type=AppConfigType.DRAFT, **DEFAULT_APP_CONFIG)
    db_session.add(draft)
    await db_session.flush()

    svc = _svc(db_session)
    result = await svc.get_draft_app_config(app)

    drafts = (await db_session.scalars(
        select(AppConfigVersion).where(AppConfigVersion.app_id == app.id)
    )).all()
    assert len(drafts) == 1, "草稿已存在时不应重复创建"
    assert result["id"] == str(draft.id)


@pytest.mark.asyncio
async def test_process_validate_tools_filters_deleted_api_tool(db_session):
    """api_tool 路径：存在的工具保留并组装展示信息，不存在的被剔除"""
    account = Account(name="t3", email="t3@t.com")
    db_session.add(account)
    await db_session.flush()
    provider = ApiToolProvider(
        account_id=account.id, name="my-provider", icon="", description="", openapi_schema="{}",
    )
    db_session.add(provider)
    await db_session.flush()
    tool = ApiTool(
        account_id=account.id, provider_id=provider.id, name="weather",
        description="", url="https://x", method="GET", parameters=[],
    )
    db_session.add(tool)
    await db_session.flush()

    svc = _svc(db_session)
    tools, validate_tools = await svc._process_and_validate_tools([
        {"type": "api_tool", "provider_id": str(provider.id), "tool_id": "weather", "params": {}},
        {"type": "api_tool", "provider_id": str(provider.id), "tool_id": "missing", "params": {}},
    ])

    assert len(validate_tools) == 1
    assert validate_tools[0]["tool_id"] == "weather"
    assert tools[0]["tool"]["name"] == "weather"
    assert tools[0]["provider"]["id"] == str(provider.id)


@pytest.mark.asyncio
async def test_get_draft_app_config_filters_removed_api_tool(db_session):
    """草稿 tools 引用已删除的 api_tool → 校验后从草稿中剔除并落库"""
    account = Account(name="t4", email="t4@t.com")
    db_session.add(account)
    await db_session.flush()
    app = App(account_id=account.id, name="a3", icon="", description="")
    db_session.add(app)
    await db_session.flush()
    draft = AppConfigVersion(
        app_id=app.id, version=0, config_type=AppConfigType.DRAFT,
        **{**DEFAULT_APP_CONFIG, "tools": [{"type": "api_tool", "provider_id": str(uuid4()), "tool_id": "gone", "params": {}}]},
    )
    db_session.add(draft)
    await db_session.flush()

    svc = _svc(db_session)
    result = await svc.get_draft_app_config(app)

    assert result["tools"] == [], "已删除工具应从草稿中剔除"
    refreshed = await db_session.get(AppConfigVersion, draft.id)
    assert refreshed.tools == []
