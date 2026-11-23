#!/usr/bin/env python
"""JwtService 无 session 单例——generate/parse 往返 + 异常路径。

jwt_service 无 db 依赖、无 injector/flask 引用；此处补行为回归。
"""
import os
import time

import jwt
import pytest

from internal.exception import UnauthorizedException
from internal.service.jwt_service import JwtService


def test_generate_and_parse_roundtrip():
    token = JwtService.generate_token({"sub": "abc", "iss": "llmops"})
    payload = JwtService.parse_token(token)
    assert payload["sub"] == "abc"
    assert payload["iss"] == "llmops"


def test_parse_expired_token_raises_unauthorized():
    token = jwt.encode(
        {"sub": "abc", "exp": int(time.time()) - 10},
        os.getenv("JWT_SECRET_KEY"),
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedException):
        JwtService.parse_token(token)


def test_parse_invalid_token_raises_unauthorized():
    with pytest.raises(UnauthorizedException):
        JwtService.parse_token("not-a-jwt")
