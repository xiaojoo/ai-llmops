#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""AppConfigService._process_and_transformer_app_config 编排器配置透传测试（不依赖数据库）"""
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from internal.service.app_config_service import AppConfigService


def _stub_app_config(**extra):
    """真实对象形态的 AppConfig 桩（避免 MagicMock 自动补属性掩盖缺失字段）"""
    base = dict(
        id=uuid4(),
        dialog_round=5,
        preset_prompt="prompt",
        retrieval_config={},
        long_term_memory={},
        opening_statement="",
        opening_questions=[],
        speech_to_text={},
        text_to_speech={},
        suggested_after_answer={},
        review_config={"enable": False},
        updated_at=datetime.now(),
        created_at=datetime.now(),
    )
    base.update(extra)
    return SimpleNamespace(**base)


class TestTransformerOrchestratorConfig:
    def test_runtime_dict_includes_orchestrator_config(self):
        """转换结果必须包含 orchestrator_config，且透传运行配置中的值"""
        app_config = _stub_app_config(orchestrator_config={"enable": True, "max_sub_tasks": 3})

        result = AppConfigService._process_and_transformer_app_config(
            model_config={},
            tools=[],
            skills=[],
            workflows=[],
            datasets=[],
            app_config=app_config,
        )

        assert result["orchestrator_config"]["enable"] is True
        assert result["orchestrator_config"]["max_sub_tasks"] == 3

    def test_runtime_dict_orchestrator_config_defaults_to_empty(self):
        """未配置编排器时（空字典），转换结果中返回空字典默认值"""
        app_config = _stub_app_config(orchestrator_config={})

        result = AppConfigService._process_and_transformer_app_config(
            model_config={},
            tools=[],
            skills=[],
            workflows=[],
            datasets=[],
            app_config=app_config,
        )

        assert result["orchestrator_config"] == {}
