#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : completion.py
"""
import os

from langchain_openai import OpenAI
from pydantic import Field

from internal.core.language_model.entities.model_entity import BaseLanguageModel


def _openai_base_factory() -> str | None:
    """base_url 缺省值：读环境变量 OPENAI_API_BASE，缺省用 OpenAI 官方端点。

    兼容裸域名写法：自动补全 /v1 后缀，与 OpenAI SDK 拼接路径的要求一致。
    """
    base = os.getenv("OPENAI_API_BASE")
    if not base:
        return None
    base = base.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


class Completion(OpenAI, BaseLanguageModel):
    """OpenAI聊天模型基类"""

    openai_api_base: str | None = Field(
        default_factory=_openai_base_factory,
        alias="base_url",
        description="OpenAI 兼容端点，缺省读环境变量 OPENAI_API_BASE（自动补全 /v1）",
    )
