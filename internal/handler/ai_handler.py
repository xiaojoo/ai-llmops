#!/usr/bin/env python
"""
@Time    : 2026/1/6 0:22
@author  : sunxiaojie
@File    : ai_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from internal.server.deps import CurrentUser
from internal.schema.ai_schema import GenerateSuggestedQuestionsReq, OptimizePromptReq
from internal.service import AIService
from package.response import compact_generate_response, success_json


@dataclass
class AIHandler:
    """AI辅助模块处理器"""
    ai_service: AIService

    async def optimize_prompt(self, user: CurrentUser, req: OptimizePromptReq) -> None:
        """根据传递的预设prompt进行优化"""
        # optimize_prompt 为 async generator（SSE 流），不可 await——直接传 compact_generate_response
        resp = self.ai_service.optimize_prompt(req.prompt)
        return compact_generate_response(resp)

    async def generate_suggested_questions(self, user: CurrentUser, req: GenerateSuggestedQuestionsReq) -> None:
        """根据传递的信息id生成建议问题列表"""
        suggested_questions = await self.ai_service.generate_suggested_questions_from_message_id(
            UUID(req.message_id), user,
        )
        return success_json(suggested_questions)
