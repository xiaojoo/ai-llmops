#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : chat.py
"""
import os

from langchain_openai import ChatOpenAI
from pydantic import Field

from internal.core.language_model.entities.model_entity import BaseLanguageModel


def _openai_base_factory() -> str | None:
    """base_url 缺省值：读环境变量 OPENAI_API_BASE，缺省用 OpenAI 官方端点。

    兼容裸域名写法（如 https://api.openai.com / https://api.deepseek.com）：
    自动补全 /v1 后缀，与 OpenAI SDK 拼接 /chat/completions 的路径要求一致。
    """
    base = os.getenv("OPENAI_API_BASE")
    if not base:
        return None
    base = base.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


class Chat(ChatOpenAI, BaseLanguageModel):
    """OpenAI聊天模型（走 Responses API）

    GPT-5.6 系列主推 Responses API（不再是 Chat Completions），
    这里固定 use_responses_api=True，让该 provider 下所有模型的
    message 与结构化输出都经 /v1/responses 路由。
    """

    # 强制走 Responses API（langchain-openai 内置支持；gpt-5 推理模型会
    # 自动去掉 temperature，见 _construct_responses_api_payload）
    use_responses_api: bool = True

    openai_api_base: str | None = Field(
        default_factory=_openai_base_factory,
        alias="base_url",
        description="OpenAI 兼容端点，缺省读环境变量 OPENAI_API_BASE（自动补全 /v1）",
    )
