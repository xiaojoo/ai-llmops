#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
自定义 API 大语言模型处理器：按账号管理用户自行添加的 OpenAI/Anthropic/Responses 兼容模型。

- 账号隔离由 CustomLlmModelService 强制（get_by_id/list_by_account 过滤 account_id）；
- 未找到/非本账号时服务层抛 NotFoundException，由 app 全局异常处理器映射；
- 本 handler 不做捕获，直接透传。
"""
from dataclasses import dataclass
from uuid import UUID

from internal.core.language_model.providers.custom_api.protocol import PROTOCOL_OPTIONS
from internal.exception import NotFoundException
from internal.schema.custom_llm_model_schema import (
    CreateCustomLlmModelReq,
    GetCustomLlmModelResp,
    UpdateCustomLlmModelReq,
)
from internal.server.deps import CurrentUser
from internal.service import CustomLlmModelService
from package.response import success_json, success_message_json


@dataclass
class CustomLlmModelHandler:
    """自定义 API 大语言模型处理器"""
    custom_llm_model_service: CustomLlmModelService

    async def list_custom_llm_models(self, user: CurrentUser) -> None:
        """列出当前账号下未删除的自定义模型。"""
        records = await self.custom_llm_model_service.list_by_account(user)
        resp = [
            GetCustomLlmModelResp.model_validate(r).model_dump(mode="json")
            for r in records
        ]
        return success_json(resp)

    async def get_custom_llm_model(self, user: CurrentUser, model_id: UUID) -> None:
        """获取指定自定义模型详情。"""
        record = await self.custom_llm_model_service.get_by_id(model_id, user)
        if record is None:
            raise NotFoundException("自定义模型不存在或不属于当前账号")
        resp = GetCustomLlmModelResp.model_validate(record)
        return success_json(resp.model_dump(mode="json"))

    async def create_custom_llm_model(self, user: CurrentUser, req: CreateCustomLlmModelReq) -> None:
        """创建自定义模型。"""
        await self.custom_llm_model_service.create(req, user)
        return success_message_json("创建自定义模型成功")

    async def update_custom_llm_model(self, user: CurrentUser, model_id: UUID, req: UpdateCustomLlmModelReq) -> None:
        """更新自定义模型。"""
        await self.custom_llm_model_service.update_model(model_id, req, user)
        return success_message_json("更新自定义模型成功")

    async def delete_custom_llm_model(self, user: CurrentUser, model_id: UUID) -> None:
        """删除自定义模型。"""
        await self.custom_llm_model_service.delete_model(model_id, user)
        return success_message_json("删除自定义模型成功")

    async def get_custom_llm_model_protocol_options(self, user: CurrentUser) -> None:
        """获取协议下拉选项（供前端协议选择器）。"""
        return success_json(PROTOCOL_OPTIONS)
