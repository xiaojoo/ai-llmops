#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""AppService 草稿配置 orchestrator_config 校验与响应测试（不依赖数据库；async 化）"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from internal.exception import ValidateException
from internal.service.app_service import AppService


def _build_service() -> AppService:
    """构造 AppService（全部依赖使用 MagicMock，避免数据库/外部依赖）"""
    return AppService(
        db=MagicMock(),
        conversation_service=MagicMock(),
        builtin_provider_manager=MagicMock(),
        api_provider_manager=MagicMock(),
        retrieval_service=MagicMock(),
        redis_client=MagicMock(),
        cos_service=MagicMock(),
        app_config_service=MagicMock(),
        language_model_service=MagicMock(),
        language_model_manager=MagicMock(),
        chat_runner=MagicMock(),
        memory_provider_resolver=MagicMock(),
        attachment_service=MagicMock(),
    )


class TestDraftAppConfigOrchestratorConfig:
    @pytest.mark.asyncio
    async def test_validate_accepts_orchestrator_config(self):
        """acceptable_fields 必须允许 orchestrator_config 通过校验"""
        svc = _build_service()
        payload = {"orchestrator_config": {"enable": True, "max_sub_tasks": 5}}
        result = await svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    @pytest.mark.asyncio
    async def test_validate_still_rejects_unknown_field(self):
        """未知字段仍然被拒绝，避免校验被放宽"""
        svc = _build_service()
        with pytest.raises(ValidateException):
            await svc._validate_draft_app_config({"unknown_key": 1}, MagicMock())

    @pytest.mark.asyncio
    async def test_update_draft_app_config_persists_orchestrator_config(self):
        """通过校验的 orchestrator_config 必须被下发到更新（BaseService.update 按字段 setattr 落库）"""
        svc = _build_service()
        draft_record = SimpleNamespace()
        svc.get_app = AsyncMock(return_value=SimpleNamespace(draft_app_config=draft_record))
        svc.get_or_create_draft_app_config = AsyncMock(return_value=draft_record)
        payload = {"orchestrator_config": {"enable": True, "max_sub_tasks": 5}}

        with patch.object(svc, "update", new=AsyncMock(return_value=draft_record)) as mock_update:
            await svc.update_draft_app_config(uuid4(), payload, MagicMock())

        assert mock_update.call_args.kwargs["orchestrator_config"] == {
            "enable": True, "max_sub_tasks": 5
        }

    @pytest.mark.asyncio
    async def test_get_draft_app_config_includes_orchestrator_config(self):
        """GET 草稿配置响应必须包含 orchestrator_config，透传草稿中的值"""
        svc = _build_service()
        draft = SimpleNamespace(orchestrator_config={"enable": True, "max_sub_tasks": 5})
        svc.get_app = AsyncMock(return_value=SimpleNamespace(draft_app_config=draft))
        svc.get_or_create_draft_app_config = AsyncMock(return_value=draft)
        svc.app_config_service.get_draft_app_config = AsyncMock(return_value={
            "id": "cfg-id",
            "model_config": {},
            "review_config": {"enable": False},
            "long_term_memory": {"enable": False},
        })

        result = await svc.get_draft_app_config(uuid4(), MagicMock())

        assert result["orchestrator_config"] == {"enable": True, "max_sub_tasks": 5}

    @pytest.mark.asyncio
    async def test_get_draft_app_config_orchestrator_config_defaults_to_empty(self):
        """草稿中 orchestrator_config 为空时，响应中返回空字典默认值"""
        svc = _build_service()
        draft = SimpleNamespace(orchestrator_config=None)
        svc.get_app = AsyncMock(return_value=SimpleNamespace(draft_app_config=draft))
        svc.get_or_create_draft_app_config = AsyncMock(return_value=draft)
        svc.app_config_service.get_draft_app_config = AsyncMock(return_value={})

        result = await svc.get_draft_app_config(uuid4(), MagicMock())

        assert result["orchestrator_config"] == {}


class TestLongTermMemoryProviderValidation:
    @pytest.mark.asyncio
    async def test_validate_accepts_provider_tencent(self):
        svc = _build_service()
        payload = {"long_term_memory": {"enable": True, "provider": "tencent"}}
        result = await svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    @pytest.mark.asyncio
    async def test_validate_accepts_provider_builtin(self):
        svc = _build_service()
        payload = {"long_term_memory": {"enable": False, "provider": "builtin"}}
        result = await svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    @pytest.mark.asyncio
    async def test_validate_accepts_enable_only_still_valid(self):
        """存量格式（仅 enable）保持兼容"""
        svc = _build_service()
        payload = {"long_term_memory": {"enable": True}}
        result = await svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    @pytest.mark.asyncio
    async def test_validate_rejects_unknown_provider(self):
        svc = _build_service()
        with pytest.raises(ValidateException):
            await svc._validate_draft_app_config(
                {"long_term_memory": {"enable": True, "provider": "unknown"}}, MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_enable(self):
        """enable 必填：只有 provider 不合法"""
        svc = _build_service()
        with pytest.raises(ValidateException):
            await svc._validate_draft_app_config(
                {"long_term_memory": {"provider": "tencent"}}, MagicMock(),
            )
