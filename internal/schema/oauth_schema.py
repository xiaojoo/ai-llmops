#!/usr/bin/env python
"""
@Time    : 2025/12/21 0:50
@Author  : sunxiaojie
@File    : oauth_schema.py
"""
from pydantic import BaseModel, Field, field_validator


class AuthorizeReq(BaseModel):
    """第三方授权认证请求体"""
    code: str = Field(description="code代码不能为空")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("code代码不能为空")
        return v


class AuthorizeResp(BaseModel):
    """第三方授权认证响应结构"""
    access_token: str = ""
    expire_at: int = 0
