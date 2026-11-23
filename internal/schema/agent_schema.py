#!/usr/bin/env python
"""
@Time    : 2025/12/13 22:56
@Author  : sunxiaojie
@File    : agent_schema.py
"""
from pydantic import BaseModel, Field, field_validator


class ChatCompletionReq(BaseModel):
    """对话补全请求参数校验类"""
    query: str = Field(max_length=2000, description="提问内容不能为空且必须为字符串，长度不能超过2000")
    user_id: str = Field(description="用户ID不能为空")
    history: list = Field(default_factory=list)

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("提问内容不能为空且必须为字符串")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if not v:
            raise ValueError("用户ID不能为空")
        return v

    @field_validator("history")
    @classmethod
    def validate_history(cls, v) -> list:
        if not isinstance(v, list):
            raise ValueError("历史记录必须为列表格式")
        return v
