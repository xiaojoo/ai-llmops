#!/usr/bin/env python
"""自定义 API 模型 provider：常量 + ModelEntity 构建 + 协议分发。

本包（custom_api）面向用户自行添加的 OpenAI/Responses/Anthropic 兼容端点，
后续任务将由 LanguageModelManager 注册本包提供的常量与 builder。

对外导出：
- 常量：CUSTOM_API_PROVIDER / MODEL_PROTOCOL_OPENAI / MODEL_PROTOCOL_RESPONSES /
  MODEL_PROTOCOL_ANTHROPIC / ALL_PROTOCOLS
- build_custom_model_entity(record, model_uuid) -> ModelEntity
- build_model_class(protocol) -> type[BaseLanguageModel]（见 chat.py）
"""
from .models import (
    CUSTOM_API_PROVIDER,
    MODEL_PROTOCOL_OPENAI,
    MODEL_PROTOCOL_RESPONSES,
    MODEL_PROTOCOL_ANTHROPIC,
    ALL_PROTOCOLS,
    build_custom_model_entity,
)
from .chat import build_model_class

__all__ = [
    "CUSTOM_API_PROVIDER",
    "MODEL_PROTOCOL_OPENAI",
    "MODEL_PROTOCOL_RESPONSES",
    "MODEL_PROTOCOL_ANTHROPIC",
    "ALL_PROTOCOLS",
    "build_custom_model_entity",
    "build_model_class",
]
