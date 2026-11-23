#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : reflection_service.py
"""
import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from anyio import to_thread
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy.ext.asyncio import AsyncSession

from .base_service import BaseService
from .language_model_service import LanguageModelService
from .procedural_memory_service import ProceduralMemoryService

logger = logging.getLogger(__name__)


# 反思提示词：从负面反馈中提炼可改写的行为规则
REFLECTION_TEMPLATE = """你是一个 Agent 行为反思器。用户对以下回答点了"不喜欢"，请分析回答失败的原因，并产出一条可执行的改进规则（行为指令），供 Agent 下次遵循。

规则：
1. 只输出对 Agent 行为有指导意义的指令（如"先给结论再展开""回答控制在 3 条以内"）；
2. 指令要具体、可执行，不要泛泛而谈；
3. 如果无法提炼（如用户单纯情绪化），输出空对象；
4. 严禁把用户隐私/情绪写入规则。

用户问题：{query}
Agent 回答：{answer}
反馈：dislike

输出严格 JSON，不要输出其他内容：
{{"instruction": "..."}}"""


@dataclass
class ReflectionService(BaseService):
    """反馈反思服务：根据 dislike 反馈提炼并改写程序记忆"""
    db: AsyncSession
    language_model_service: LanguageModelService
    procedural_memory_service: ProceduralMemoryService

    async def reflect_on_feedback(
            self,
            *,
            app_id: UUID,
            user_id: UUID,
            query: str,
            answer: str,
            feedback: str,
    ) -> None:
        """根据反馈触发反思：dislike 时提炼行为规则写入程序记忆"""
        if feedback != "dislike":
            return
        try:
            import asyncio
            prompt = ChatPromptTemplate.from_template(REFLECTION_TEMPLATE)
            llm = await self.language_model_service.load_default_language_model()
            llm.temperature = 0
            chain = prompt | llm | StrOutputParser()
            # asyncio.to_thread 替代 to_thread.run_sync(limiter=...)，避免后台线程跨 loop 死锁
            raw = await asyncio.to_thread(
                lambda: chain.invoke({"query": query, "answer": answer})
            )

            instruction = self._parse_instruction(raw)
            if not instruction:
                return
            await self.procedural_memory_service.upsert_instruction(
                app_id, user_id, instruction, source="feedback_reflection",
            )
        except Exception:
            logger.exception("反馈反思失败，app_id=%s, user_id=%s", app_id, user_id)

    def _parse_instruction(self, raw: str) -> str:
        """容错解析反思输出"""
        if not raw:
            return ""
        text = raw.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return ""
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return ""
        return str(data.get("instruction", "")).strip()
