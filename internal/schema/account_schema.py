#!/usr/bin/env python
"""
@Time    : 2025/12/21 13:48
@Author  : sunxiaojie
@File    : account_schema.py
"""
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.lib.helper import datetime_to_timestamp
from package.password import password_pattern


class GetCurrentUserResp(BaseModel):
    """获取当前用户信息响应结构"""
    id: UUID | None = None
    name: str = ""
    email: str = ""
    avatar: str = ""
    last_login_at: int = 0
    last_login_ip: str = ""
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "last_login_at"):
            return {
                "id": data.id,
                "name": data.name,
                "email": data.email,
                "avatar": data.avatar,
                "last_login_at": datetime_to_timestamp(data.last_login_at),
                "last_login_ip": data.last_login_ip,
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class UpdatePasswordReq(BaseModel):
    """更新密码请求结构体"""
    password: str = Field(description="密码最少包含一个字母，一个数字，并且长度为8-16")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("密码不能为空")
        if not re.fullmatch(password_pattern, v):
            raise ValueError("密码最少包含一个字母，一个数字，并且长度为8-16")
        return v


class UpdateNameReq(BaseModel):
    """更新用户名请求结构体"""
    name: str = Field(description="用户名称长度在1-25个字符")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) < 1 or len(v) > 25:
            raise ValueError("用户名称长度在1-25个字符")
        return v


class UpdateAvatarReq(BaseModel):
    """更新头像请求结构体"""
    avatar: str = Field(
        description="用户头像必须是uri地址",
    )

    @field_validator("avatar")
    @classmethod
    def validate_avatar_url(cls, v: str) -> str:
        from urllib.parse import urlparse
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("用户头像必须是uri地址")
        return v
