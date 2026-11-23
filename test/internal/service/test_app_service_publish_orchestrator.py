#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""AppService.publish_draft_app_config 编排器配置透传到运行时配置测试（不依赖数据库；async 化）"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.service.app_service import AppService


def _build_service() -> AppService:
    """构造 AppService（全部依赖使用 MagicMock，避免数据库/外部依赖）

    db 用 AsyncMock：publish 内的 `await self.db.execute(...)`（删除关联/取最大版本）需要可 await；
    execute 的返回值用普通 MagicMock，使 `.scalar_one()` 保持同步返回（AsyncMock 链会得到协程）。
    """
    svc = AppService(
        db=AsyncMock(),
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
    svc.db.execute.return_value = MagicMock()
    return svc


def _draft_config(**overrides) -> dict:
    """publish_draft_app_config 消费的草稿配置字典（含全部必需键）"""
    config = {
        "model_config": {},
        "dialog_round": 5,
        "preset_prompt": "prompt",
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
    config.update(overrides)
    return config


class TestPublishOrchestratorConfig:
    @pytest.mark.asyncio
    async def test_publish_passes_orchestrator_config_to_runtime_config(self):
        """发布时创建运行时 AppConfig 必须携带草稿中的 orchestrator_config"""
        svc = _build_service()
        svc.get_app = AsyncMock(return_value=SimpleNamespace(draft_app_config=SimpleNamespace()))
        svc.get_draft_app_config = AsyncMock(return_value=_draft_config())
        svc.get_or_create_draft_app_config = AsyncMock(return_value=SimpleNamespace())
        svc.update = AsyncMock()
        svc.create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

        await svc.publish_draft_app_config(uuid4(), MagicMock())

        # 第一次 create 是运行时 AppConfig（随后是 AppDatasetJoin、AppConfigVersion）
        create_kwargs = svc.create.call_args_list[0].kwargs
        assert create_kwargs["orchestrator_config"] == {"enable": True, "max_sub_tasks": 3}

    @pytest.mark.asyncio
    async def test_publish_passes_empty_orchestrator_config(self):
        """草稿未配置编排器时，运行时 AppConfig 仍显式写入空字典默认值"""
        svc = _build_service()
        svc.get_app = AsyncMock(return_value=SimpleNamespace(draft_app_config=SimpleNamespace()))
        svc.get_draft_app_config = AsyncMock(return_value=_draft_config(orchestrator_config={}))
        svc.get_or_create_draft_app_config = AsyncMock(return_value=SimpleNamespace())
        svc.update = AsyncMock()
        svc.create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

        await svc.publish_draft_app_config(uuid4(), MagicMock())

        create_kwargs = svc.create.call_args_list[0].kwargs
        assert create_kwargs["orchestrator_config"] == {}
