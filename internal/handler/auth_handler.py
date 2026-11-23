#!/usr/bin/env python
"""
@Time    : 2025/12/21 17:11
@Author  : sunxiaojie
@File    : auth_handler.py
"""
from dataclasses import dataclass

from internal.server.deps import CurrentUser
from internal.schema.auth_schema import PasswordLoginReq, PasswordLoginResp
from internal.service import AccountService
from package.response import success_json, success_message_json


@dataclass
class AuthHandler:
    """LLMOps平台自有授权认证处理器"""
    account_service: AccountService

    async def password_login(self, req: PasswordLoginReq) -> None:
        """账号密码登录"""
        credentials = await self.account_service.password_login(req.email, req.password)
        resp = PasswordLoginResp.model_validate(credentials)
        return success_json(resp.model_dump(mode="json"))

    async def logout(self, user: CurrentUser) -> None:
        """退出登录"""
        # Flask 的 logout_user() 清除 session；FastAPI 无 session 依赖，JWT 由客户端丢弃
        return success_message_json("退出登录成功")
