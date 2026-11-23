#!/usr/bin/env python
"""
@Time    : 2025/12/21 17:22
@Author  : sunxiaojie
@File    : auth_schema.py
"""
import re

from pydantic import BaseModel, Field, field_validator

from package.password import password_pattern


class PasswordLoginReq(BaseModel):
    """账号密码登录请求结构"""
    email: str = Field(description="登录邮箱长度在5-25个字符")
    password: str = Field(description="密码最少包含一个字母，一个数字，并且长度为8-16")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if len(v) < 5 or len(v) > 25:
            raise ValueError("登录邮箱长度在5-25个字符")
        # 按旧 Email() 校验逻辑：必须含 @ 且 @ 不能在首尾、只能有一个 @
        if v.count("@") != 1 or v.startswith("@") or v.endswith("@"):
            raise ValueError("登录邮箱格式错误")
        local, domain = v.split("@")
        if not local or not domain or "." not in domain:
            raise ValueError("登录邮箱格式错误")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("账号密码不能为空")
        if not re.fullmatch(password_pattern, v):
            raise ValueError("密码最少包含一个字母，一个数字，并且长度为8-16")
        return v


class PasswordLoginResp(BaseModel):
    """账号密码授权认证响应结构"""
    access_token: str = ""
    expire_at: int = 0
