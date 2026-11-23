#!/usr/bin/env python
"""
@Time    : 2026/1/20 22:31
@Author  : sunxiaojie
@File    : open_api_handler.py
"""
from dataclasses import dataclass

from internal.server.deps import ApiKeyUser
from internal.schema.open_api_schema import OpenAIChatReq
from internal.service import OpenAPIService
from package.response import compact_generate_response


@dataclass
class OpenAPIHandler:
    """开放API处理器"""
    open_api_service: OpenAPIService

    async def chat(self, user: ApiKeyUser, req: OpenAIChatReq) -> None:
        """开放Chat对话接口"""
        # chat 为 async generator（SSE 流），不可 await——直接传 compact_generate_response
        resp = self.open_api_service.chat(req, user)
        return compact_generate_response(resp)
