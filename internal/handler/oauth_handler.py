#!/usr/bin/env python
"""
@Time    : 2025/12/21 0:14
@Author  : sunxiaojie
@File    : oauth_handler.py
"""
from dataclasses import dataclass

from internal.schema.oauth_schema import AuthorizeReq, AuthorizeResp
from internal.service import OAuthService
from package.response import success_json


@dataclass
class OAuthHandler:
    """第三方授权认证处理器"""
    oauth_service: OAuthService

    async def provider(self, provider_name: str) -> None:
        """根据传递的提供商名字获取授权认证重定向地址"""
        # get_oauth_by_provider_name 为同步 classmethod（无 IO），不可 await
        oauth = self.oauth_service.get_oauth_by_provider_name(provider_name)
        redirect_url = oauth.get_authorization_url()
        return success_json({"redirect_url": redirect_url})

    async def authorize(self, provider_name: str, req: AuthorizeReq) -> None:
        """根据传递的提供商名字+code获取第三方授权信息"""
        credential = await self.oauth_service.oauth_login(provider_name, req.code)
        resp = AuthorizeResp.model_validate(credential)
        return success_json(resp.model_dump(mode="json"))
