#!/usr/bin/env python
"""本地离线模型（qwen3 provider）模型 ID 由环境变量 LOCAL_LLM_MODEL 驱动。

/settings 页保存 LOCAL_LLM_MODEL 后经 apply_to_env 注入 os.environ，
chat.py 构造时以 default_factory 读取，因此本地端点加载任意 OpenAI
兼容模型（不限定 Qwen）时无需改代码，改设置即可。
"""
import os

from internal.core.language_model.providers.qwen3.chat import (
    _qwen3_model_factory,
)


class TestQwen3ModelFactory:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
        assert _qwen3_model_factory() == "qwen/qwen3.8-27b"

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_MODEL", "Qwen3-14B-AWQ:14b")
        assert _qwen3_model_factory() == "Qwen3-14B-AWQ:14b"

    def test_chat_model_name_uses_env(self, monkeypatch):
        from internal.core.language_model.providers.qwen3.chat import Chat

        monkeypatch.setenv("LOCAL_LLM_MODEL", "custom/local-llm")
        model = Chat()
        try:
            assert model.model_name == "custom/local-llm"
        finally:
            # ChatOpenAI 构造的 httpx client 无需显式关闭（无连接建立）
            pass

    def test_model_attr_not_hardcoded_in_yaml(self):
        """qwen3.yaml 不再写死 attributes.model（交由环境变量/构造参数决定）。"""
        import yaml

        from internal.config.settings import get_settings

        yaml_path = os.path.join(
            str(get_settings().project_root),
            "internal", "core", "language_model", "providers", "qwen3", "qwen3.yaml",
        )
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "model" not in data.get("attributes", {})
        assert data["metadata"]["model_name_env"] == "LOCAL_LLM_MODEL"

    def test_resolve_model_config_display_uses_env(self, monkeypatch):
        """应用列表/详情显示名解析：qwen3 model 展示名跟随 LOCAL_LLM_MODEL。"""
        from internal.core.language_model import LanguageModelManager

        manager = LanguageModelManager()
        # 未设置 env → 回退模型 label
        monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
        display = manager.resolve_model_config_display("qwen3", "qwen3")
        assert display is not None
        assert display["provider_label"] == "本地离线模型"
        assert display["model_label"] == "本地模型（OpenAI 兼容）"

        # 设置 env → model 展示名取实际配置值（应用列表/详情同步变化）
        monkeypatch.setenv("LOCAL_LLM_MODEL", "Qwen3-14B-AWQ:14b")
        display = manager.resolve_model_config_display("qwen3", "qwen3")
        assert display["model_label"] == "Qwen3-14B-AWQ:14b"

    def test_resolve_model_config_display_unknown_returns_none(self):
        """未知 provider/model → None，前端回退显示原始 key。"""
        from internal.core.language_model import LanguageModelManager

        manager = LanguageModelManager()
        assert manager.resolve_model_config_display("no-such-provider", "qwen3") is None
        assert manager.resolve_model_config_display("qwen3", "no-such-model") is None

    def test_language_model_label_uses_env(self, monkeypatch):
        """语言模型列表/详情的 model.label 也跟随 LOCAL_LLM_MODEL（模型选择器显示实际名）。"""
        from unittest.mock import MagicMock

        from internal.core.language_model import LanguageModelManager
        from internal.service.language_model_service import LanguageModelService

        manager = LanguageModelManager()
        svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
        model_entity = manager.get_provider("qwen3").get_model_entity("qwen3")

        # 未设置 env → 回退静态 label
        monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
        assert svc._resolve_model_label("qwen3", model_entity) == "本地模型（OpenAI 兼容）"

        # 设置 env → 取实际模型名（下拉候选/选中项显示一致）
        monkeypatch.setenv("LOCAL_LLM_MODEL", "openai/gpt-oss-20b MXFP4")
        assert svc._resolve_model_label("qwen3", model_entity) == "openai/gpt-oss-20b MXFP4"

        # 其它 provider 不带 model_name_env → label 不变
        deepseek = manager.get_provider("deepseek").get_model_entity("deepseek-v4-flash")
        assert svc._resolve_model_label("deepseek", deepseek) == "deepseek-v4-flash"
