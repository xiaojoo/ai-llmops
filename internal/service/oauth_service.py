#!/usr/bin/env python
"""
@Time    : 2025/12/21 0:16
@Author  : sunxiaojie
@File    : oauth_service.py
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from internal.core.request_context import get_request_context
from internal.exception import NotFoundException
from internal.model import AccountOAuth
from package.oauth import GithubOAuth, OAuth

from .account_service import AccountService
from .base_service import BaseService
from .jwt_service import JwtService


@dataclass
class OAuthService(BaseService):
    """第三方授权认证服务"""
    db: AsyncSession
    account_service: AccountService
    jwt_service: JwtService

    @classmethod
    def get_all_oauth(cls) -> dict[str, OAuth]:
        """获取LLMops集成的所有第三方授权认证方式"""
        # 1、实例化集成的第三方授权认证OAuth
        github = GithubOAuth(
            client_id=os.getenv("GITHUB_CLIENT_ID"),
            client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
            redirect_uri=os.getenv("GITHUB_CLIENT_REDIRECT_URI"),
        )

        return {
            "github": github,
        }

    @classmethod
    def get_oauth_by_provider_name(cls, provider_name: str) -> OAuth:
        """根据传递的服务提供商命中获取授权服务"""
        all_oauth = cls.get_all_oauth()
        oauth = all_oauth.get(provider_name)

        if oauth is None:
            raise NotFoundException(f"该授权方式[{provider_name}]不存在")

        return oauth

    async def oauth_login(self, provider_name: str, code: str) -> dict[str, Any]:
        """第三方OAuth授权认证登录，返回授权凭证以及过期时间"""
        oauth = self.get_oauth_by_provider_name(provider_name)

        # GithubOAuth 的 get_access_token/get_user_info 为同步 requests 网络 IO，
        # async 方法内经 run_in_threadpool 桥接，避免阻塞事件循环。
        oauth_access_token = await run_in_threadpool(oauth.get_access_token, code)
        oauth_user_info = await run_in_threadpool(oauth.get_user_info, oauth_access_token)
        account_oauth = await self.account_service.get_account_oauth_by_provider_name_and_openid(
            provider_name,
            oauth_user_info.id,
        )
        if not account_oauth:
            account = await self.account_service.get_account_by_email(oauth_user_info.email)
            if account is None:
                account = await self.account_service.create_account(
                    name=oauth_user_info.name,
                    email=oauth_user_info.email,
                )
            account_oauth = await self.create(
                AccountOAuth,
                # AccountOAuth.account_id 为 String(255) 列——必须传 str：
                # asyncpg 对 VARCHAR 列绑定 UUID 对象抛 DataError
                account_id=str(account.id),
                provider=provider_name,
                openid=oauth_user_info.id,
                encrypted_token=oauth_access_token,
            )
        else:
            account = await self.account_service.get_account(str(account_oauth.account_id))
            if account is None:
                raise NotFoundException("账号不存在")

        await self.update(
            account,
            last_login_at=datetime.now(),
            last_login_ip=get_request_context().remote_addr,
        )
        await self.update(
            account_oauth,
            encrypted_token=oauth_access_token,
        )

        expire_at = int((datetime.now() + timedelta(days=30)).timestamp())
        payload = {
            "sub": str(account.id),
            "iss": "llmops",
            "exp": expire_at,
        }

        access_token = self.jwt_service.generate_token(payload)
        return {
            "expire_at": expire_at,
            "access_token": access_token,
        }
