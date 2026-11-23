#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : chat.py

通义千问聊天模型。
"""
import os

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr

from internal.core.language_model.entities.model_entity import BaseLanguageModel


def _dashscope_key_factory() -> SecretStr:
    """api_key 缺省值：读环境变量 DASHSCOPE_API_KEY，缺失时构造即失败。"""
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise ValueError("Did not find api_key, please add an environment variable DASHSCOPE_API_KEY")
    return SecretStr(key)


def _dashscope_base_factory() -> str:
    """base_url 缺省值：读环境变量 DASHSCOPE_API_BASE，缺省用阿里云百炼兼容端点。

    兼容裸域名写法（如 https://dashscope.aliyuncs.com）：自动补全
    /compatible-mode/v1 后缀，与 OpenAI SDK 拼接 /chat/completions 的路径要求一致。
    """
    base = (
        os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    return base if base.endswith("/compatible-mode/v1") else f"{base}/compatible-mode/v1"


class Chat(ChatOpenAI, BaseLanguageModel):
    """通义千问聊天模型（百炼 OpenAI 兼容接口）"""

    # 阿里云百炼 OpenAI 兼容端点（可被 DASHSCOPE_API_BASE 环境变量覆盖）
    openai_api_base: str = Field(
        default_factory=_dashscope_base_factory,
        alias="base_url",
        description="阿里云百炼 OpenAI 兼容端点，缺省读环境变量 DASHSCOPE_API_BASE",
    )
    openai_api_key: SecretStr | None = Field(
        default_factory=_dashscope_key_factory,
        alias="api_key",
        description="DashScope API KEY，缺省读环境变量 DASHSCOPE_API_KEY",
    )
