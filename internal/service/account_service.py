#!/usr/bin/env python
"""
@Time    : 2025/12/20 22:47
@Author  : sunxiaojie
@File    : account_service.py
"""
import base64
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config.settings import get_settings
from internal.core.request_context import get_request_context
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import FailedException
from internal.model import Account, AccountOAuth, Conversation
from package.password import compare_password, hash_password

from .base_service import BaseService
from .jwt_service import JwtService


@dataclass
class AccountService(BaseService):
    """账号服务"""
    db: AsyncSession
    jwt_service: JwtService

    async def get_account(self, account_id: str) -> Account | None:
        """根据id获取指定的账号模型，账号不存在时返回None"""
        return await self.get(Account, account_id)

    async def get_assistant_agent_conversation(
        self,
        account: Account,
        assistant_agent_id: str | None = None,
    ) -> Conversation:
        """获取账号的助手 Agent 会话，不存在则创建。"""
        assistant_agent_id = assistant_agent_id or get_settings().assistant_agent_id
        conversation = (
            await self.db.get(Conversation, account.assistant_agent_conversation_id)
            if account.assistant_agent_conversation_id
            else None
        )

        # 会话不存在则创建
        if conversation is None:
            conversation = Conversation(
                app_id=assistant_agent_id,
                name="New Conversation",
                invoke_from=InvokeFrom.ASSISTANT_AGENT,
                created_by=account.id,
                updated_by=account.id,
            )
            self.db.add(conversation)
            await self.db.flush()

            account.assistant_agent_conversation_id = conversation.id
            await self.db.commit()  # 独立事务边界

        return conversation

    async def get_account_oauth_by_provider_name_and_openid(self, provider_name: str, openid: str) -> AccountOAuth | None:
        """根据传递峨提供者名字+openid获取第三方授权认证记录，不存在时返回None"""
        stmt = (
            select(AccountOAuth)
            .where(
                AccountOAuth.provider == provider_name,
                AccountOAuth.openid == openid,
            )
        )

        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_account_by_email(self, email: str) -> Account | None:
        """根据传递的邮箱查询账号信息，不存在时返回None"""
        stmt = (
            select(Account).where(Account.email == email)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create_account(self, **kwargs) -> Account:
        """根据传递的键值对创建账号信息"""
        return await self.create(Account, **kwargs)

    async def update_password(self, password: str, account: Account) -> Account:
        """ 更新当前账号密码信息"""
        # 1、生成密码随机盐值
        salt = secrets.token_bytes(16)
        base64_salt = base64.b64encode(salt).decode()

        # 2、利用盐值和password进行加密
        password_hashed = hash_password(password, salt)
        base64_password_hashed = base64.b64encode(password_hashed).decode()

        # 3、更新账号信息
        await self.update_account(account, password=base64_password_hashed, password_salt=base64_salt)

        return account

    async def update_account(self, account: Account, **kwargs) -> Account:
        """根据传递的信息更新账号"""
        await self.update(account, **kwargs)
        return account

    async def password_login(self, email: str, password: str) -> dict[str, Any]:
        """根据传递的密码+邮箱登录特定的账号"""
        # 1、根据传递的邮箱查询账号是否存在
        account = await self.get_account_by_email(email)
        if account is None:
            raise FailedException("账号不存在或者密码错误，请核实后重试")

        # 2、检验账号密码是否正确
        if not account.is_password_set or not compare_password(
                password,
                account.password,
                account.password_salt
        ):
            raise FailedException("账号不存在或者密码错误，请核实后重试")

        # 3、生成凭证信息
        expire_at = int((datetime.now() + timedelta(days=30)).timestamp())
        payload = {
            "sub": str(account.id),
            "iss": "llmops",
            "exp": expire_at,
        }
        access_token = self.jwt_service.generate_token(payload)
        await self.update(
            account,
            last_login_at=datetime.now(),
            last_login_ip=get_request_context().remote_addr,
        )
        return {
            "expire_at": expire_at,
            "access_token": access_token,
        }
