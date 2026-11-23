#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 15:13
@Author : sunxiaojie
@File   : update_file_schema.py
"""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from internal.lib.helper import datetime_to_timestamp

# UploadFileReq / UploadImageReq 的文件字段不进 Pydantic body 模型。
# handler 用 UploadFile 参数处理文件（T4），非文件字段如下已转 Pydantic。
# 文件上传约束（大小/类型）由 handler 侧验证或服务层验证。


class UploadFileResp(BaseModel):
    """上传文件接口响应结构"""
    id: UUID | None = None
    account_id: UUID | None = None
    name: str = ""
    key: str = ""
    size: int = 0
    extension: str = ""
    mime_type: str = ""
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "mime_type"):
            return {
                "id": data.id,
                "account_id": data.account_id,
                "name": data.name,
                "key": data.key,
                "size": data.size,
                "extension": data.extension,
                "mime_type": data.mime_type,
                "created_at": int(data.created_at.timestamp()),
            }
        return data
