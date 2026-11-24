#!/usr/bin/env python
"""
自定义 API 大语言模型服务：用户按账号添加的 OpenAI/Anthropic/Responses 兼容模型。

- CRUD + 逻辑删除（is_deleted）；
- api_key 用主密钥 AES 加密入库（CONFIG_MASTER_KEY 优先，回退 JWT_SECRET_KEY），
  读取时不回显明文（schema 层 API 响应统一掩码为 ********）；
- 账号隔离：get_by_id / list_by_account 强制过滤 account_id，且仅返回未删除记录。

命名说明：`create` / `update` / `delete` 是 BaseService 的 ORM 助手（`self.create(model, **kwargs)`、
`self.update(instance, **kwargs)`、`self.delete(instance)`），签名不同。为避免覆盖/阴影歧义，
本服务的公开业务方法使用 `create` / `update_model` / `delete_model`，其中 `update_model` 与
`delete_model` 不覆盖基类助手；内部落库统一走 `BaseService.create` / `self.update`。
"""
import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.exception import NotFoundException
from internal.lib.crypto import build_master_key, encrypt_value
from internal.model import ApiLlmModel
from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq, UpdateCustomLlmModelReq
from internal.service.base_service import BaseService


def _master_key() -> bytes:
    """获取加密主密钥（32 字节）：CONFIG_MASTER_KEY 优先，回退 JWT_SECRET_KEY。"""
    secret = os.getenv("CONFIG_MASTER_KEY") or os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("CONFIG_MASTER_KEY 或 JWT_SECRET_KEY 至少配置一个")
    return build_master_key(secret)


@dataclass
class CustomLlmModelService(BaseService):
    """自定义 API 大语言模型服务"""
    db: AsyncSession

    @staticmethod
    def _encrypt(plain: str) -> str:
        """AES-CBC 加密，返回 base64(iv + ciphertext)。"""
        return encrypt_value(plain, _master_key())

    async def create(self, req: CreateCustomLlmModelReq, user) -> ApiLlmModel:
        """新建模型：api_key 加密入库，归属当前账号。"""
        fields = {
            "account_id": user.id,
            "name": req.name,
            "protocol": req.protocol,
            "model_id": req.model_id,
            "base_url": req.base_url or "",
            "api_key": self._encrypt(req.api_key) if req.api_key else "",
            "features": req.features or [],
            "context_window": req.context_window,
            "max_output_tokens": req.max_output_tokens,
            "remark": req.remark or "",
            "icon": req.icon or "",
        }
        # 本类覆盖了 create（业务签名），显式调用基类助手
        return await BaseService.create(self, ApiLlmModel, **fields)

    async def update_model(self, model_id: UUID, req: UpdateCustomLlmModelReq, user) -> ApiLlmModel:
        """更新模型：仅限当前账号且未删除的记录。"""
        record = await self.get_by_id(model_id, user)
        if record is None:
            raise NotFoundException("自定义模型不存在或不属于当前账号")
        return await self._update_record(record, req)

    async def _update_record(self, record: ApiLlmModel, req: UpdateCustomLlmModelReq) -> ApiLlmModel:
        """更新记录字段。api_key 仅在传入非空时更新（不变更则保留原加密值）。"""
        kwargs = {
            "name": req.name,
            "protocol": req.protocol,
            "model_id": req.model_id,
            "base_url": req.base_url or "",
            "features": req.features or [],
            "context_window": req.context_window,
            "max_output_tokens": req.max_output_tokens,
            "remark": req.remark or "",
            "icon": req.icon or "",
        }
        if req.api_key:
            kwargs["api_key"] = self._encrypt(req.api_key)
        return await self.update(record, **kwargs)

    async def delete_model(self, model_id: UUID, user) -> None:
        """逻辑删除：仅限当前账号且未删除的记录。"""
        record = await self.get_by_id(model_id, user)
        if record is None:
            raise NotFoundException("自定义模型不存在或不属于当前账号")
        await self.update(record, is_deleted=True)

    async def get_by_id(self, model_id: UUID, user) -> ApiLlmModel | None:
        """按 id 获取未删除模型，且强制校验归属账号。"""
        stmt = select(ApiLlmModel).where(
            ApiLlmModel.id == model_id,
            ApiLlmModel.account_id == user.id,
            ApiLlmModel.is_deleted.is_(False),
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def list_by_account(self, user) -> list[ApiLlmModel]:
        """列出当前账号下未删除的模型。"""
        stmt = select(ApiLlmModel).where(
            ApiLlmModel.account_id == user.id,
            ApiLlmModel.is_deleted.is_(False),
        ).order_by(ApiLlmModel.created_at)
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_models_for_account(self, account_id) -> list[ApiLlmModel]:
        """供 manager 懒加载：按账号返回未删除模型。"""
        stmt = select(ApiLlmModel).where(
            ApiLlmModel.account_id == account_id,
            ApiLlmModel.is_deleted.is_(False),
        ).order_by(ApiLlmModel.created_at)
        return list((await self.db.execute(stmt)).scalars().all())
