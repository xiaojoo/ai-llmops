#!/usr/bin/env python
"""LanguageModelService async 化测试——load_language_model 的线程池桥接 + 兜底 + 图标读取。

load_language_model 为同步模型构造经 _MODEL_LIMITER（CapacityLimiter(2)）桥接：
- 成功路径按 model_config 构造模型实例（entity attributes + parameters + context/metadata）；
- 失败路径兜底 load_default_language_model（deepseek）；
- get_language_model_icon 文件 IO 经 run_in_threadpool 读取。
"""
from unittest.mock import MagicMock

import pytest

from internal.service.language_model_service import LanguageModelService


class FakeModel:
    """捕获构造参数的模型桩"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeProvider:
    def __init__(self, entity=None, model_class=None):
        self._entity = entity
        self._model_class = model_class

    def get_model_entity(self, model_name):
        return self._entity

    def get_model_class(self, model_type, model_entity=None):
        return self._model_class


class FakeEntity:
    def __init__(self, model_type="chat"):
        self.model_type = model_type
        self.model_name = "fake-model"
        self.label = "Fake"
        self.context_window = 8192
        self.max_output_tokens = 2048
        self.features = []
        self.attributes = {"api_key": "k"}
        self.metadata = {}
        self.parameters = []


def _svc(manager) -> LanguageModelService:
    return LanguageModelService(db=MagicMock(), language_model_manager=manager)


@pytest.mark.asyncio
async def test_load_language_model_constructs_with_config():
    """成功路径：model_class(**entity.attributes, **parameters, context_window/features/metadata)"""
    entity = FakeEntity()
    provider = FakeProvider(entity=entity, model_class=FakeModel)
    manager = MagicMock()
    manager.get_provider.return_value = provider

    svc = _svc(manager)
    model = await svc.load_language_model({"provider": "fake", "model": "fake-model", "parameters": {"temperature": 0.5}})

    assert isinstance(model, FakeModel)
    assert model.kwargs["api_key"] == "k"
    assert model.kwargs["temperature"] == 0.5
    assert model.kwargs["context_window"] == 8192
    assert model.kwargs["features"] == []
    assert model.kwargs["metadata"] == {}


@pytest.mark.asyncio
async def test_load_language_model_falls_back_to_default():
    """失败路径：provider 查找异常 → 兜底默认模型（deepseek 路径）"""
    manager = MagicMock()

    def _provider_for(name):
        if name == "nope":
            raise RuntimeError("provider missing")
        return MagicMock()

    manager.get_provider.side_effect = _provider_for

    svc = _svc(manager)
    await svc.load_language_model({"provider": "nope", "model": "x", "parameters": {}})

    # 兜底走 _load_default_sync：get_provider("deepseek") → get_model_entity("deepseek-v4-flash") → 构造
    assert manager.get_provider.call_args_list[1].args == ("deepseek",)


@pytest.mark.asyncio
async def test_get_language_model_returns_dict():
    entity = FakeEntity()
    provider = FakeProvider(entity=entity, model_class=FakeModel)
    manager = MagicMock()
    manager.get_provider.return_value = provider

    svc = _svc(manager)
    result = await svc.get_language_model("fake", "fake-model")

    assert result["model"] == "fake-model"
    assert result["context_window"] == 8192


@pytest.mark.asyncio
async def test_get_language_model_raises_when_provider_missing():
    from internal.exception import NotFoundException

    manager = MagicMock()
    manager.get_provider.return_value = None
    svc = _svc(manager)

    with pytest.raises(NotFoundException):
        await svc.get_language_model("missing", "m")


@pytest.mark.asyncio
async def test_get_language_model_icon_reads_file(monkeypatch):
    """图标文件 IO 经 run_in_threadpool 读取：路径 = project_root/internal/core/language_model/providers/{name}/_asset/{icon}

    注：环境沙箱拒绝 pytest 默认 tmp_path（WinError 5），改用 workspace 内 storage/ 临时目录（沿用 skill 测试模式）。
    """
    import shutil
    from pathlib import Path

    from internal.config.settings import get_settings

    tmp_root = Path("storage/test-language-model-icon")
    if tmp_root.exists():
        shutil.rmtree(tmp_root, ignore_errors=True)
    try:
        class FakeProviderEntity:
            icon = "icon.png"

        provider_dir = tmp_root / "internal" / "core" / "language_model" / "providers" / "fake"
        asset_dir = provider_dir / "_asset"
        asset_dir.mkdir(parents=True)
        (asset_dir / "icon.png").write_bytes(b"\x89PNG-fake")

        monkeypatch.setattr(get_settings(), "project_root", tmp_root)
        manager = MagicMock()
        provider = MagicMock()
        provider.provider_entity = FakeProviderEntity()
        manager.get_provider.return_value = provider

        svc = _svc(manager)
        icon, mimetype = await svc.get_language_model_icon("fake")

        assert icon == b"\x89PNG-fake"
        assert mimetype == "image/png"
    finally:
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)


def test_load_language_model_is_async_function():
    """load_language_model/load_default_language_model 应为协程函数（async def）"""
    import inspect

    assert inspect.iscoroutinefunction(LanguageModelService.load_language_model)
    assert inspect.iscoroutinefunction(LanguageModelService.load_default_language_model)
