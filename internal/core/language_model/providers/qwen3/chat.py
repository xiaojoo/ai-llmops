#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : chat.py

本地离线聊天模型（vLLM / LM Studio 等 OpenAI 兼容端点，不限定具体模型）。
model / base_url / api_key 缺省读环境变量 LOCAL_LLM_MODEL / LOCAL_LLM_API_BASE / LOCAL_LLM_API_KEY，
模型 ID 可在 /settings 页「本地离线模型（OpenAI 兼容端点）」中配置。
"""
import os

from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr

from internal.core.language_model.entities.model_entity import BaseLanguageModel


def _qwen3_model_factory() -> str:
    """model 缺省值：读环境变量 LOCAL_LLM_MODEL，缺省沿用历史默认（保持旧配置兼容）。

    本地端点实际加载哪个模型由 /settings 中的 LOCAL_LLM_MODEL 决定：
    请求体 model 字段会原样发给 vLLM / LM Studio，必须与端点加载的模型 ID 一致。
    """
    return os.getenv("LOCAL_LLM_MODEL") or "qwen/qwen3.8-27b"


def _qwen3_key_factory() -> SecretStr | None:
    """api_key 缺省值：读环境变量 LOCAL_LLM_API_KEY，缺省用占位 key（本地端点通常不校验）。"""
    key = os.getenv("LOCAL_LLM_API_KEY") or "lm-studio"
    return SecretStr(key)


def _qwen3_base_factory() -> str:
    """base_url 缺省值：读环境变量 LOCAL_LLM_API_BASE，缺省用本地 vLLM 默认端点。

    兼容裸域名写法（如 http://127.0.0.1:1234）：自动补全 /v1 后缀，
    与 OpenAI SDK 拼接 /chat/completions 的路径要求一致。
    """
    base = (os.getenv("LOCAL_LLM_API_BASE") or "http://127.0.0.1:1234/v1").rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


class Chat(ChatOpenAI, BaseLanguageModel):
    """本地离线聊天模型（OpenAI 兼容端点，模型 ID 可配置）"""

    model_name: str = Field(
        default_factory=_qwen3_model_factory,
        alias="model",
        description="本地端点模型 ID，缺省读环境变量 LOCAL_LLM_MODEL",
    )
    openai_api_base: str = Field(
        default_factory=_qwen3_base_factory,
        alias="base_url",
        description="本地 OpenAI 兼容端点，缺省读环境变量 LOCAL_LLM_API_BASE",
    )
    openai_api_key: SecretStr | None = Field(
        default_factory=_qwen3_key_factory,
        alias="api_key",
        description="本地端点 API Key，缺省读环境变量 LOCAL_LLM_API_KEY",
    )
