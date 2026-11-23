#!/usr/bin/env python
"""custom_api provider 懒合并进 LanguageModelManager 的测试。

按 CONTROLLER RESOLVED DESIGN：
- Provider 新增 custom_model_class_provider（按 model_entity.metadata["protocol"] 分发 per-model 类）。
- Provider.get_model_class(model_type, model_entity=None)：custom_api 走 resolver（需传实体）；
  静态 provider 不设 resolver，行为不变。
- Manager 新增 custom_model_loader / _merged_account / merge_account_custom_models /
  get_provider_async(provider_name, account_id=None)（懒合并）。
"""
import pytest

from internal.core.language_model import LanguageModelManager
from internal.core.language_model.providers.custom_api.models import (
    CUSTOM_API_PROVIDER,
    MODEL_PROTOCOL_ANTHROPIC,
)
from internal.core.language_model.providers.custom_api.chat import build_model_class


async def _make_loader():
    from internal.model import ApiLlmModel

    async def loader(account_id):
        return [
            ApiLlmModel(
                id="e08f4b44-0000-4000-8000-000000000001",
                account_id=account_id,
                name="my-claude",
                protocol="anthropic",
                model_id="claude-3-5-sonnet",
                base_url="https://api.anthropic.com",
                api_key="sk-ant-xxx",
                features=["tool_call"],
                context_window=200000,
                max_output_tokens=8192,
                remark="",
                icon="",
                is_deleted=False,
            )
        ]

    return loader


@pytest.mark.asyncio
async def test_merge_adds_custom_provider():
    manager = LanguageModelManager(custom_model_loader=await _make_loader())
    await manager.merge_account_custom_models("11111111-1111-1111-1111-111111111111")
    provider = manager.get_provider(CUSTOM_API_PROVIDER)
    assert provider is not None
    entity = provider.get_model_entity("custom_api/e08f4b44-0000-4000-8000-000000000001")
    assert entity.label == "my-claude"
    assert entity.metadata["protocol"] == "anthropic"
    # 按记录 protocol 分发的模型类：anthropic 记录 → build_model_class("anthropic")
    cls = provider.get_model_class("chat", entity)
    assert isinstance(cls, type)
    assert cls.__name__ == build_model_class(MODEL_PROTOCOL_ANTHROPIC).__name__


@pytest.mark.asyncio
async def test_get_provider_async_triggers_lazy_merge():
    manager = LanguageModelManager(custom_model_loader=await _make_loader())
    # 未显式 merge 前，provider_map 无 custom_api（懒加载）
    assert manager.provider_map.get(CUSTOM_API_PROVIDER) is None
    provider = await manager.get_provider_async(
        CUSTOM_API_PROVIDER, "11111111-1111-1111-1111-111111111111"
    )
    assert provider is not None
