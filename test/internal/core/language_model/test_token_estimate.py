#!/usr/bin/env python
"""多模态 token 估算：图片按固定 token 计入。

口径变更（2026-10-04）：以前"没有词表就按 utf-8 字节估"，中文会算成 3 倍字符数
（同一份真实语料实测比官方多 3.81 倍）；现在认不出官方口径就返回 None（前端不显示），
图片加成也随整体未知而不给——不给"看着像真的"的估算值。
"""
import tiktoken
from langchain_core.messages import HumanMessage

from internal.core.language_model.entities.model_entity import BaseLanguageModel


class SimpleLLM(BaseLanguageModel):
    """无 tiktoken 的最小 LLM；model_name 决定官方口径，认不出就不给数"""

    model_name: str = "unknown-local-model"

    def get_num_tokens(self, text: str) -> int:
        raise NotImplementedError("no vocab")

    # langchain BaseLanguageModel 抽象方法：测试不实际调用，仅满足实例化
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class TestMultimodalTokenEstimate:
    def test_image_blocks_count_fixed_tokens(self):
        llm = SimpleLLM(model_name="gpt-4o", context_window=32768)
        msg = HumanMessage(content=[
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
            {"type": "text", "text": "这是什么？"},
        ])
        # 官方口径（gpt-4o → o200k_base）的文本 token + 2 * IMAGE_TOKEN_ESTIMATE
        text_tokens = len(tiktoken.get_encoding("o200k_base").encode("这是什么？"))
        assert llm.get_num_tokens_safe([msg]) == text_tokens + 2 * llm.IMAGE_TOKEN_ESTIMATE

    def test_plain_text_message_unchanged(self):
        llm = SimpleLLM(model_name="gpt-4o", context_window=32768)
        msg = HumanMessage(content="你好")
        assert llm.get_num_tokens_safe([msg]) == len(
            tiktoken.get_encoding("o200k_base").encode("你好"))

    def test_unrecognized_model_uses_the_cl100k_fallback(self):
        """认不出官方口径时退回 cl100k 估算档，而不是字节长度（3.81 倍）也不是 0"""
        llm = SimpleLLM(context_window=32768)
        msg = HumanMessage(content="你好")
        assert llm.get_num_tokens_safe([msg]) == len(
            tiktoken.get_encoding("cl100k_base").encode("你好"))
