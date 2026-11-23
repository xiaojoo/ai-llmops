#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/16 14:13
@Author : sunxiaojie
@File   : exception.py
"""
from dataclasses import field
from typing import Any

from package.response import HttpCode


def extract_exception_message(e: Exception) -> str:
    """提取异常的真实错误消息。

    项目自定义异常（CustomException）把消息存在 .message 属性而非 args，
    直接 str(e) 会得到空字符串，需要依次兜底。
    """
    return (
        str(e)
        or getattr(e, "message", "")
        or getattr(e, "msg", "")
        or repr(e)
    )


class CustomException(Exception):
    """基础自定义异常信息"""
    code: HttpCode = HttpCode.FAIL
    message: str = ""
    data: Any = field(default_factory=dict)

    def __init__(self, message: str = "", data: Any = None):
        super().__init__()
        self.data = data
        self.message = message


class FailedException(CustomException):
    """通用失败异常"""


class NotFoundException(CustomException):
    """未找到数据异常"""
    code = HttpCode.NOT_FOUND


class UnauthorizedException(CustomException):
    """未授权异常"""
    code = HttpCode.UNAUTHORIZED


class ForbiddenException(CustomException):
    """无权限异常"""
    code = HttpCode.FORBIDDEN


class ValidateException(CustomException):
    """数据验证异常"""
    code = HttpCode.VALIDATION_ERROR
