#!/usr/bin/env python
"""
@Time    : 2026/1/2 15:50
@Author  : sunxiaojie
@File    : token_buffer_memory.py
"""
from dataclasses import dataclass

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    get_buffer_string,
    trim_messages,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message


@dataclass
class TokenBufferMemory:
    """基于token计数的缓冲记忆组件（db: AsyncSession）"""

    db: AsyncSession  # 数据库实例
    conversation: Conversation  # 会话模型
    model_instance: BaseLanguageModel  # LLM大语言模型

    def _derive_max_token_limit(self) -> int:
        """依据模型上下文窗口推导历史消息的token预算。

        预算 = 上下文窗口 − 输出预留(max_tokens) − 系统提示词/工具定义/当前提问及安全余量(15%)，
        保底 1000；模型窗口未知(<=0)时回退为旧的默认值 2000。
        """
        context_window = self.model_instance.context_window or 0
        if context_window <= 0:
            return 2000

        max_tokens = self.model_instance.max_tokens or 0
        reserve = max_tokens + int(context_window * 0.15)
        return max(context_window - reserve, 1000)

    async def get_history_prompt_messages(
            self,
            max_token_limit: int | None = None,
            message_limit: int = 10,
    ) -> list[AnyMessage]:
        """根据传递的token限制+消息条数限制获取指定会话模型的历史消息列表"""
        # 1、判断会话模型是否存在，如果不存在则直接返回空列表
        if self.conversation is None:
            return []

        # 2、查询改会话的消息列表，并且使用时间进行排序，同时匹配答案不为空、匹配会话id、没有软删除、状态是正常
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == self.conversation.id,
                Message.answer != "",
                Message.is_deleted.is_(False),
                Message.is_archived.is_(False),  # 窗口内只含未归档消息
                Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP]),
            )
            .order_by(Message.created_at.desc())
            .limit(message_limit)
        )
        records = (await self.db.execute(stmt)).scalars().all()
        messages = list(reversed(records))

        # 将messages转换成LangChain消息列表
        prompt_messages = []
        for message in messages:
            prompt_messages.extend([
                self.model_instance.convert_to_human_message(message.query, message.image_urls),
                # 携带 DeepSeek thinking 的 reasoning_content：跨轮次重建历史时回传给后端，
                # 否则续聊/多轮场景会触发 400（"The `reasoning_content` ... must be passed back"）。
                AIMessage(
                    content=message.answer,
                    additional_kwargs=(
                        {"reasoning_content": message.reasoning_content}
                        if getattr(message, "reasoning_content", "")
                        else {}
                    ),
                ),
            ])

        # 3、未显式指定token上限时，依据模型上下文窗口推导历史预算
        if max_token_limit is None:
            max_token_limit = self._derive_max_token_limit()

        # 4、基于token计数截断历史消息，避免超出模型上下文窗口；
        #    token_counter 使用安全包装：兼容无词表的本地模型
        #    （langchain-core>=1.6 对未知模型抛 NotImplementedError，这里统一走估算兜底）
        def _safe_counter(messages: list[AnyMessage]) -> int:
            msgs = messages if isinstance(messages, list) else [messages]
            return self.model_instance.get_num_tokens_safe(msgs) or 0

        try:
            return trim_messages(
                messages=prompt_messages,
                max_tokens=max_token_limit,
                token_counter=_safe_counter,
                strategy='last',
                start_on="human",
                end_on="ai",
            )
        except Exception:
            return prompt_messages

    async def get_history_prompt_text(
            self,
            human_prefix: str = "Human",
            ai_prefix: str = "AI",
            max_token_limit: int = 2000,
            message_limit: int = 10,
    ) -> str:
        """根据传递的数据获取指定会话历史消息提示文本（短期记忆的文本形式，用于文本生成模型"""
        # 1、根据传递的信息获取历史消息列表
        messages = await self.get_history_prompt_messages(max_token_limit, message_limit)

        # 2、调用LangChain集成的get_buffer_string（函数将消息列表转换成文本)
        return get_buffer_string(messages, human_prefix, ai_prefix)
