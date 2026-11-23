#!/usr/bin/env python
"""
@Time    : 2026/1/21 20:44
@Author  : sunxiaojie
@File    : open_api_schema.py
"""
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OpenAIChatReq(BaseModel):
    """开放API聊天接口请求结构体"""
    app_id: str = Field(description="应用id格式必须为UUID")
    end_user_id: str | None = Field(default=None, description="终端用户id必须为UUID")
    conversation_id: str = ""
    query: str = Field(max_length=2000, description="用户提问query不能为空且长度不能超过2000")
    image_urls: list[str] = Field(default_factory=list)
    stream: bool = True

    @field_validator("app_id")
    @classmethod
    def validate_app_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("应用id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("应用id格式必须为UUID")
        return v

    @field_validator("end_user_id")
    @classmethod
    def validate_end_user_id(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            try:
                UUID(v)
            except ValueError:
                raise ValueError("终端用户id必须为UUID")
        return v

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("用户提问query不能为空")
        return v

    @field_validator("image_urls")
    @classmethod
    def validate_image_urls(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            return []
        if len(v) > 5:
            raise ValueError("上传的图片数量不能超过5，请核实后重试")
        for image_url in v:
            result = urlparse(image_url)
            if not all([result.scheme, result.netloc]):
                raise ValueError("上传的图片URL地址格式错误，请核实后重试")
        return v
