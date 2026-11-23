#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:12
@Author  : sunxiaojie
@File    : chat.py
"""

from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek

from internal.core.language_model.entities.model_entity import BaseLanguageModel


class Chat(ChatDeepSeek, BaseLanguageModel):
    """DeepSeek聊天模型"""
    fallback_model: str = "gpt-3.5-turbo"
    # v4 系列（thinking 模式）不支持强制 tool_choice，结构化输出需走 json_mode，
    # 否则 function_calling 约束不住模型输出 schema（会误调用工具）。
    supports_forced_tool_choice: bool = False

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        """DeepSeek v4 thinking（推理）模式：多轮/工具调用时必须回传 assistant 消息的
        reasoning_content，否则 API 返回 400（"The `reasoning_content` in the thinking
        mode must be passed back to the API"）。

        langchain-openai 在 _convert_message_to_dict 里会丢弃 additional_kwargs
        （不会把 reasoning_content 写回请求体），这里在构造完 payload 后按原始消息补回。
        """
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        try:
            src_messages = self._convert_input(input_).to_messages()
        except Exception:
            return payload

        out_messages = payload.get("messages", [])
        if len(src_messages) != len(out_messages):
            return payload

        for src, out in zip(src_messages, out_messages):
            if isinstance(src, AIMessage) and out.get("role") == "assistant":
                reasoning = src.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    out["reasoning_content"] = reasoning
        return payload

    def bind_tools(
        self,
        tools,
        *,
        tool_choice=None,
        strict=None,
        parallel_tool_calls=None,
        **kwargs,
    ):
        """v4 系列（thinking 模式）不支持强制 tool_choice：
        API 报 'Thinking mode does not support this tool_choice'。

        官方示例（thinking + tools）只传 tools、由模型自主决定调用；
        这里统一把 tool_choice 置 None，避免结构化输出/Agent 绑定工具时 400。
        """
        return super().bind_tools(
            tools,
            tool_choice=None,
            strict=strict,
            parallel_tool_calls=parallel_tool_calls,
            **kwargs,
        )
