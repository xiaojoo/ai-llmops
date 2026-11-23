#!/usr/bin/env python
"""
@Time    : 2025/12/13 14:09
@Author  : sunxiaojie
@File    : token_buffer_memory.py
"""
from dataclasses import dataclass

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    get_buffer_string,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message


@dataclass
class TokenBufferMemory:
    """基于token计数的缓冲记忆组件（db: AsyncSession）"""
    db: AsyncSession
    conversation: Conversation
    model_instance: BaseLanguageModel

    # def get_history_prompt_messages(
    #         self,
    #         max_token_limit: int = 2000,
    #         message_limit: int = 10,
    # ) -> list[AnyMessage]:
    #     """根据传递的token限制+消息条数限制获取指定会话模型的历史消息列表"""
    #     # 1、判断会话模型是否存在，如果不存在则直接返回空列表
    #     if self.conversation is None:
    #         return []
    #     # 2.查询该会话的消息列表，并且使用时间进行倒序、同时匹配答案不为空、匹配会话id、没有软删除、状态是正常
    #     messages = self.db.session.scalars(
    #         select(Message).where(
    #             Message.conversation_id == self.conversation.id,
    #             Message.answer != "",
    #             Message.is_deleted.is_(False),
    #             Message.status == MessageStatus.NORMAL,
    #         )
    #         .order_by(Message.created_at.desc())
    #         .limit(message_limit)
    #     ).all()
    #     messages = list(reversed(messages))
    #
    #     # 3、将messages转换成LangChain消息列表
    #     prompt_messages = []
    #     for message in messages:
    #         prompt_messages.extend([
    #             HumanMessage(content=message.query),
    #             AIMessage(content=message.answer),
    #         ])
    #
    #     # 4、调用LangChain继承的trim_messages函数剪切信息列表
    #     return trim_messages(
    #         messages=prompt_messages,
    #         max_tokens=max_token_limit,
    #         token_counter=self.model_instance,
    #         strategy="last",
    #         start_on="human",
    #         end_on="ai",
    #     )
    async def get_history_prompt_messages(
            self,
            message_limit: int = 10,
    ) -> list[AnyMessage]:
        """基于消息条数的历史消息获取（短期记忆）

        规则：
        - 默认取最近 message_limit 轮有效消息（倒序查，再反转）；
        - 点踩（feedback=dislike）的消息永不进入短期记忆；
        - 点赞（feedback=like）的消息一定进入短期记忆，即使超出轮数窗口也会并入。
        """

        # 1. 会话不存在直接返回
        if self.conversation is None:
            return []

        # 2. 查询最近 N 条有效消息（倒序查，再反转；点踩消息排除）
        base_conditions = (
            Message.conversation_id == self.conversation.id,
            Message.answer != "",
            Message.is_deleted.is_(False),
            Message.feedback != "dislike",
            Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP, MessageStatus.TIMEOUT])
        )
        messages = (await self.db.scalars(
            select(Message).where(*base_conditions)
            .order_by(Message.created_at.desc())
            .limit(message_limit)
        )).all()

        messages = list(reversed(messages))

        # 3. 点赞消息一定进入短期记忆：即使超出轮数窗口也并入（按时间序去重）
        liked_messages = (await self.db.scalars(
            select(Message).where(
                *base_conditions,
                Message.feedback == "like",
            ).order_by(Message.created_at.asc())
        )).all()
        if liked_messages:
            seen = {m.id for m in messages}
            messages = [*messages, *(m for m in liked_messages if m.id not in seen)]
            messages.sort(key=lambda m: m.created_at)

        # 4. 转成 LangChain messages
        prompt_messages: list[AnyMessage] = []
        for message in messages:
            if message.query:
                prompt_messages.append(HumanMessage(content=message.query))
            if message.answer:
                prompt_messages.append(AIMessage(content=message.answer))

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
        messages = await self.get_history_prompt_messages(message_limit)

        # 2、调用LangChain集成的get_buffer_string（函数将消息列表转换成文本)
        return get_buffer_string(messages, human_prefix, ai_prefix)
