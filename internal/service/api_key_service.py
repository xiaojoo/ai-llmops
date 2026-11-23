#!/usr/bin/env python
"""
@Time    : 2026/1/20 21:38
@Author  : sunxiaojie
@File    : api_key_service.py
"""
import math
import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.exception import ForbiddenException
from internal.model import Account, ApiKey
from internal.schema.api_key_schema import CreateApiKeyReq
from package.paginator import Paginator, PaginatorReq

from .base_service import BaseService


@dataclass
class ApiKeyService(BaseService):
    """API秘钥服务"""
    db: AsyncSession

    async def create_api_key(self, req: CreateApiKeyReq, account: Account) -> ApiKey:
        """根据传递的信息创建API秘钥"""
        return await self.create(
            ApiKey,
            account_id=account.id,
            api_key=self.generate_api_key(),
            is_active=req.is_active,
            remark=req.remark,
        )

    async def get_account(self, api_key: ApiKey) -> Account | None:
        """根据 API 秘钥查询其归属账号。"""
        return await self.db.get(Account, api_key.account_id)

    async def get_api_key(self, api_key_id: UUID, account: Account) -> ApiKey:
        """根据传递的秘钥id+账号信息获取记录"""
        api_key = await self.get(ApiKey, api_key_id)
        if api_key is None or api_key.account_id != account.id:
            raise ForbiddenException("API秘钥不存在或无权限")
        return api_key

    async def get_api_by_by_credential(self, api_key: str) -> ApiKey:
        """根据传递的凭证信息获取ApiKey记录"""
        # 1. 构建 select 语句
        stmt = select(ApiKey).where(ApiKey.api_key == api_key)

        # 2. 执行并获取单个结果（如果不存在则返回 None）
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def update_api_key(self, api_key_id: UUID, account: Account, **kwargs) -> ApiKey:
        """根据传递的信息更新API秘钥"""
        api_key = await self.get_api_key(api_key_id, account)
        await self.update(api_key, **kwargs)
        return api_key

    async def delete_api_key(self, api_key_id: UUID, account: Account) -> ApiKey:
        """根据传递的id删除API秘钥"""
        api_key = await self.get_api_key(api_key_id, account)
        await self.delete(api_key)
        return api_key

    async def get_api_keys_with_page(self, req: PaginatorReq, account: Account) -> tuple[list[ApiKey], Paginator]:
        """根据传递的信息获取API秘钥分页列表数据"""
        # 1. 构建分页器
        paginator = Paginator(db=None, req=req)

        # 2. 计数 + 分页查询
        stmt = select(ApiKey).where(
            ApiKey.account_id == account.id
        ).order_by(
            ApiKey.created_at.desc()
        )
        total_record = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        api_keys = (
            await self.db.scalars(
                stmt.offset((paginator.current_page - 1) * paginator.page_size).limit(paginator.page_size)
            )
        ).all()
        paginator.total_record = total_record
        paginator.total_page = math.ceil(total_record / paginator.page_size) if total_record else 0

        return list(api_keys), paginator

    @classmethod
    def generate_api_key(cls, api_key_prefix: str = "llmops-v1/") -> str:
        """生成一个长度为48的API秘钥，并携带前缀"""
        return api_key_prefix + secrets.token_urlsafe(48)
