#!/usr/bin/env python
"""BuiltinAppService async 化测试——add_builtin_app_to_space 独立事务边界 + 分类/列表读取。"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.entity.app_entity import AppConfigType, AppStatus
from internal.model import Account
from internal.service.builtin_app_service import BuiltinAppService


class FakeBuiltinApp:
    """model_dump(include=...) 返回真实 dict 的内置应用桩"""

    language_model_config = {"provider": "deepseek", "model": "deepseek-v4-flash"}

    def __init__(self, name="内置应用", icon="https://example.com/icon.png", description="描述"):
        self._fields = {"name": name, "icon": icon, "description": description}

    def model_dump(self, include=None):
        if include is None:
            return dict(self._fields)
        return {k: self._fields[k] for k in include if k in self._fields}


@pytest.mark.asyncio
async def test_add_builtin_app_to_space_creates_app_and_draft(db_session):
    """添加内置应用到个人空间：App + 草稿 AppConfigVersion 创建，draft_app_config_id 回填"""
    manager = MagicMock()
    manager.get_builtin_app.return_value = FakeBuiltinApp()
    svc = BuiltinAppService(db=db_session, builtin_app_manager=manager)

    account = Account(name="t", email="t@t.com")
    db_session.add(account)
    await db_session.flush()

    app = await svc.add_builtin_app_to_space("builtin-1", account)

    assert app.account_id == account.id
    assert app.status == AppStatus.DRAFT
    assert app.draft_app_config_id is not None, "草稿配置 id 应回填到 app"
    # 草稿配置落库且类型为 DRAFT
    from internal.model import AppConfigVersion
    draft = await db_session.get(AppConfigVersion, app.draft_app_config_id)
    assert draft is not None
    assert draft.config_type == AppConfigType.DRAFT.value
    assert draft.model_config == {"provider": "deepseek", "model": "deepseek-v4-flash"}


@pytest.mark.asyncio
async def test_add_builtin_app_raises_when_missing():
    manager = MagicMock()
    manager.get_builtin_app.return_value = None
    svc = BuiltinAppService(db=MagicMock(), builtin_app_manager=manager)

    with pytest.raises(NotImplementedError):
        await svc.add_builtin_app_to_space("missing", MagicMock())


@pytest.mark.asyncio
async def test_get_categories_and_builtin_apps():
    manager = MagicMock()
    manager.get_categories.return_value = ["分类A"]
    manager.get_builtin_apps.return_value = ["应用A"]
    svc = BuiltinAppService(db=MagicMock(), builtin_app_manager=manager)

    assert await svc.get_categories() == ["分类A"]
    assert await svc.get_builtin_apps() == ["应用A"]
