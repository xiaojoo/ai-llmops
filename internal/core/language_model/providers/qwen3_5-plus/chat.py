#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : chat.py

千问多模态模型（qwen3.7-plus，DashScope OpenAI 兼容端点）。
base_url / api_key 缺省读环境变量 QWEN3_5_PLUS_API_BASE / QWEN3_5_PLUS_API_KEY，
未配置时回退 DASHSCOPE_API_BASE / DASHSCOPE_API_KEY。
"""
import os

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr

from internal.core.language_model.entities.model_entity import BaseLanguageModel


def _qwen35_key_factory() -> SecretStr | None:
    """api_key 缺省值：优先 QWEN3_5_PLUS_API_KEY，回退 DASHSCOPE_API_KEY。"""
    key = os.getenv("QWEN3_5_PLUS_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not key:
        return None
    return SecretStr(key)


def _qwen35_base_factory() -> str:
    """base_url 缺省值：优先 QWEN3_5_PLUS_API_BASE，回退 DASHSCOPE_API_BASE / DashScope 兼容端点。

    兼容裸域名写法（如 https://dashscope.aliyuncs.com）：自动补全
    /compatible-mode/v1 后缀，与 OpenAI SDK 拼接 /chat/completions 的路径要求一致。
    """
    base = (
        os.getenv("QWEN3_5_PLUS_API_BASE")
        or os.getenv("DASHSCOPE_API_BASE")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    return base if base.endswith("/compatible-mode/v1") else f"{base}/compatible-mode/v1"


class Chat(ChatOpenAI, BaseLanguageModel):
    """千问多模态聊天模型（DashScope OpenAI 兼容接口）"""

    openai_api_base: str = Field(
        default_factory=_qwen35_base_factory,
        alias="base_url",
        description="DashScope OpenAI 兼容端点，缺省读 QWEN3_5_PLUS_API_BASE / DASHSCOPE_API_BASE",
    )
    openai_api_key: SecretStr | None = Field(
        default_factory=_qwen35_key_factory,
        alias="api_key",
        description="API Key，缺省读 QWEN3_5_PLUS_API_KEY / DASHSCOPE_API_KEY",
    )
