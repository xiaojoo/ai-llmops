#!/usr/bin/env python
"""
@Time    : 2025/12/21 13:38
@Author  : sunxiaojie
@File    : account_handler.py
"""
from dataclasses import dataclass

from internal.server.deps import CurrentUser
from internal.schema.account_schema import (
    GetCurrentUserResp,
    UpdateAvatarReq,
    UpdateNameReq,
    UpdatePasswordReq,
)
from internal.service import AccountService
from package.response import success_json, success_message_json


@dataclass
class AccountHandler:
    """账号设置处理器"""
    account_service: AccountService

    async def get_current_user(self, user: CurrentUser) -> GetCurrentUserResp:
        """获取当前登录账号信息"""
        resp = GetCurrentUserResp.model_validate(user)
        return success_json(resp.model_dump(mode="json"))

    async def update_password(self, user: CurrentUser, req: UpdatePasswordReq) -> None:
        """更新当前登录账号密码"""
        await self.account_service.update_password(req.password, user)
        return success_message_json("更新账号密码成功")

    async def update_name(self, user: CurrentUser, req: UpdateNameReq) -> None:
        """更新当前登录账号名称"""
        await self.account_service.update_account(user, name=req.name)
        return success_message_json("更新账号名称成功")

    async def update_avatar(self, user: CurrentUser, req: UpdateAvatarReq) -> None:
        """更新当前账号头像"""
        await self.account_service.update_account(user, avatar=req.avatar)
        return success_message_json("更新账号头像成功")
