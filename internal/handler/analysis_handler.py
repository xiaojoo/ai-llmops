#!/usr/bin/env python
"""
@Time    : 2026/2/7 17:54
@Author  : sunxiaojie
@File    : analysis_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from internal.server.deps import CurrentUser
from internal.service import AnalysisService
from package.response import success_json


@dataclass
class AnalysisHandler:
    """统计分析处理器"""
    analysis_service: AnalysisService

    async def get_app_analysis(self, user: CurrentUser, app_id: UUID) -> None:
        """根据传递的应用id获取应用的统计信息"""
        app_analysis = await self.analysis_service.get_app_analysis(app_id, user)
        return success_json(app_analysis)
