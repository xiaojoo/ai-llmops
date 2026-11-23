#!/usr/bin/env python
"""
@Time    : 2026/2/26 19:18
@Author  : sunxiaojie
@File    : audio_schema.py
"""
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AudioToTextReq(BaseModel):
    """语音转文本请求结构"""
    ossUrl: str = Field(description="OSS URL不能为空")

    @field_validator("ossUrl")
    @classmethod
    def validate_oss_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("OSS URL不能为空")
        return v


class MessageToAudioReq(BaseModel):
    """消息转流式事件语音请求结构"""
    message_id: str = Field(description="消息id格式不正确")

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("消息id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("消息id格式不正确")
        return v
