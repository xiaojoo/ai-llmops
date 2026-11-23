#!/usr/bin/env python
"""按账号懒合并 custom_api provider。

Provider 是文件型静态 provider：其构造器 validate_provider 会动态导入 chat 符号并读取
positions.yaml（custom_api 目录两者均不存在）。custom_api 是用户按账号动态添加的「虚拟」
provider，因此这里用 model_construct 跳过文件型校验，改由 custom_model_class_provider
按模型实体 metadata["protocol"] 分发对应的模型类（见 provider_entity.Provider.get_model_class）。
"""
from internal.core.language_model.entities.provider_entity import Provider, ProviderEntity
from internal.core.language_model.providers.custom_api.models import (
    build_custom_model_entity, CUSTOM_API_PROVIDER,
)
from internal.core.language_model.providers.custom_api.chat import build_model_class


def build_custom_provider(records) -> Provider:
    """根据自定义模型记录构建 custom_api Provider（含 model_entity_map + 协议分发模型类）。

    - model_entity_map 键为 `custom_api/<model_uuid>`；
    - custom_model_class_provider 按模型实体 metadata["protocol"] 调 build_model_class 分发。
      注意：此处不设置 model_class_map["chat"]（模型类不能按单个协议静态映射）。
    """
    provider_entity = ProviderEntity(
        name=CUSTOM_API_PROVIDER,
        position="999",
        label="自定义API模型",
        description="用户按账号添加的 OpenAI / Anthropic / Responses 兼容模型",
        icon="",
        background="#FFFFFF",
        supported_model_types=["chat"],
    )
    provider = Provider.model_construct(
        name=CUSTOM_API_PROVIDER,
        position=999,
        provider_entity=provider_entity,
    )

    for record in records:
        model_uuid = str(record.id)
        entity = build_custom_model_entity(record, model_uuid)
        provider.model_entity_map[f"{CUSTOM_API_PROVIDER}/{model_uuid}"] = entity

    provider.custom_model_class_provider = lambda e: build_model_class(e.metadata["protocol"])
    return provider
