#!/usr/bin/env python
"""
@Time    : 2026/1/6 0:36
@Author  : sunxiaojie
@File    : ai_service.py
"""
import json
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.ai_entity import OPTIMIZE_PROMPT_TEMPLATE
from internal.exception import ForbiddenException
from internal.model import Account, Message
from starlette.concurrency import run_in_threadpool

from .base_service import BaseService
from .conversation_service import ConversationService


@dataclass
class AIService(BaseService):
    """AI服务"""
    db: AsyncSession
    conversation_service: ConversationService

    async def generate_suggested_questions_from_message_id(self, message_id: UUID, account: Account) -> list[str]:
        """根据传递的消息id+账号生成建议问题列表"""
        # 1、查询消息并校验权限信息
        message = await self.get(Message, message_id)
        if message is None or message.created_by != account.id:
            raise ForbiddenException("该条消息不存在或无权限")

        # 2、构建对话历史列表
        histories = f"Human: {message.query} \nAI: {message.answer}"
        # 3、调用服务生成建议问题
        return await self.conversation_service.generate_suggested_questions(histories)

    @classmethod
    async def optimize_prompt(cls, prompt: str) -> AsyncGenerator:
        """根据传递的prompt进行优化生成（增量流式，逐块 yield）"""
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_deepseek import ChatDeepSeek

        # 1、构建优化prompt的提示词模板
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", OPTIMIZE_PROMPT_TEMPLATE),
            ("human", "{prompt}")
        ])

        # 2、构建LLM
        llm = ChatDeepSeek(model="deepseek-v4-flash", temperature=0.5)

        # 3、组装优化链
        optimize_chain = prompt_template | llm | StrOutputParser()

        # 4、调用链并增量流式事件返回（langchain stream 同步生成器，经 _aiter_sync 桥接逐块产出）
        _SENTINEL = object()
        sync_gen = optimize_chain.stream({"prompt": prompt})

        def _next():
            try:
                return next(sync_gen)
            except StopIteration:
                return _SENTINEL

        while True:
            chunk = await run_in_threadpool(_next)
            if chunk is _SENTINEL:
                break
            data = {"optimize_prompt": chunk}
            yield f"event: optimize_prompt\ndata: {json.dumps(data)} \n\n"
