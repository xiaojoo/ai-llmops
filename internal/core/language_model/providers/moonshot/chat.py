#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : chat.py

Moonshot（Kimi）聊天模型。
"""

import os

from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr

from internal.core.language_model.entities.model_entity import BaseLanguageModel


def _moonshot_key_factory() -> SecretStr:
    """api_key 缺省值：读环境变量 MOONSHOT_API_KEY，缺失时构造即失败。"""
    key = os.getenv("MOONSHOT_API_KEY")
    if not key:
        raise ValueError("Did not find api_key, please add an environment variable MOONSHOT_API_KEY")
    return SecretStr(key)


def _moonshot_base_factory() -> str:
    """base_url 缺省值：读环境变量 MOONSHOT_API_BASE，缺省用 Kimi 官方端点。

    兼容裸域名写法（如 https://api.moonshot.cn）：自动补全 /v1 后缀，
    与 OpenAI SDK 拼接 /chat/completions 的路径要求一致。
    """
    base = (os.getenv("MOONSHOT_API_BASE") or "https://api.moonshot.cn/v1").rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


class Chat(ChatOpenAI, BaseLanguageModel):
    """Moonshot聊天模型"""

    fallback_model: str = "gpt-3.5-turbo"

    # Kimi 官方 OpenAI 兼容端点（可被 MOONSHOT_API_BASE 环境变量覆盖）
    openai_api_base: str = Field(
        default_factory=_moonshot_base_factory,
        alias="base_url",
        description="Kimi 官方 OpenAI 兼容端点，缺省读环境变量 MOONSHOT_API_BASE",
    )
    openai_api_key: SecretStr | None = Field(
        default_factory=_moonshot_key_factory,
        alias="api_key",
        description="Moonshot API KEY，缺省读环境变量 MOONSHOT_API_KEY",
    )
