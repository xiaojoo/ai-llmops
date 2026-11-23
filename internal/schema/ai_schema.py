#!/usr/bin/env python
"""
@Time    : 2026/1/6 0:25
@Author  : sunxiaojie
@File    : ai_schema.py
"""
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class GenerateSuggestedQuestionsReq(BaseModel):
    """生成建议问题列表请求结构体"""
    message_id: str = Field(description="消息id格式必须为uuid")

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("消息id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("消息id格式必须为uuid")
        return v


class OptimizePromptReq(BaseModel):
    """优化预设prompt请求结构体"""
    prompt: str = Field(description="预设prompt的长度不能超过20000个")

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("预设prompt不能为空")
        if len(v) > 20000:
            raise ValueError("预设prompt的长度不能超过20000个")
        return v
