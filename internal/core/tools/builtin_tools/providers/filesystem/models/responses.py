#!/usr/bin/env python
"""文件系统工具包 —— 结构化响应与异常。

所有工具统一返回 JSON 字符串：

成功：
    {"success": true, "operation": "read", "path": "src/main.py", ...}

失败：
    {"success": false, "operation": "read", "path": "src/main.py",
     "error": {"code": "PATH_NOT_FOUND", "message": "..."}}

异常体系：安全层/服务层抛 FsToolkitError 子类，Toolkit.run 统一捕获并转成失败响应，
工具函数内部不直接拼错误字符串。
"""
import json
from enum import Enum
from typing import Any


class FsErrorCode(str, Enum):
    """工具返回的错误码（Agent 可据此做分支处理）"""

    INVALID_PATH = "INVALID_PATH"  # 非法路径（空 / NUL / 绝对路径 / 盘符 / UNC）
    PATH_TRAVERSAL = "PATH_TRAVERSAL"  # 路径越出工作区
    SYMLINK_ESCAPE = "SYMLINK_ESCAPE"  # 符号链接指向工作区外
    PERMISSION_DENIED = "PERMISSION_DENIED"  # 权限不足（策略拒绝）
    PATH_NOT_FOUND = "PATH_NOT_FOUND"  # 路径不存在
    IS_DIRECTORY = "IS_DIRECTORY"  # 期望文件却得到目录
    NOT_DIRECTORY = "NOT_DIRECTORY"  # 期望目录却得到文件
    ALREADY_EXISTS = "ALREADY_EXISTS"  # 目标已存在（且不允许覆盖）
    NOT_EMPTY = "NOT_EMPTY"  # 目录非空且未开启 recursive
    SIZE_LIMIT_EXCEEDED = "SIZE_LIMIT_EXCEEDED"  # 超出大小/配额限制
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"  # fs_edit 的 old_text 未找到
    INVALID_ARGUMENT = "INVALID_ARGUMENT"  # 参数不合法（如行号范围、编码）
    ENCODING_ERROR = "ENCODING_ERROR"  # 不支持的编码
    RISK_BLOCKED = "RISK_BLOCKED"  # 高风险操作被拦截（如删除根目录/回收站）
    OPERATION_FAILED = "OPERATION_FAILED"  # 底层 IO 失败


def ok(operation: str, **data: Any) -> dict:
    """构造成功响应"""
    return {"success": True, "operation": operation, **data}


def fail(
    operation: str,
    code: FsErrorCode | str,
    message: str,
    path: str | None = None,
    **extra: Any,
) -> dict:
    """构造失败响应"""
    code_str = code.value if isinstance(code, FsErrorCode) else str(code)
    result: dict[str, Any] = {
        "success": False,
        "operation": operation,
        "error": {"code": code_str, "message": message},
    }
    if path is not None:
        result["path"] = path
    if extra:
        result.update(extra)
    return result


def to_json(result: dict) -> str:
    """响应 dict → JSON 字符串（工具返回值）"""
    return json.dumps(result, ensure_ascii=False, default=str)


# ── 异常体系 ────────────────────────────────────────────────────────────────


class FsToolkitError(Exception):
    """文件系统工具包异常基类，携带错误码与面向 Agent 的消息"""

    code: FsErrorCode = FsErrorCode.OPERATION_FAILED

    def __init__(self, message: str, path: str | None = None):
        super().__init__(message)
        self.message = message
        self.path = path

    def to_result(self, operation: str) -> dict:
        return fail(operation, self.code, self.message, path=self.path)


class PathGuardError(FsToolkitError):
    """路径安全层拒绝（越界 / 非法 / 符号链接逃逸）"""

    def __init__(self, code: FsErrorCode, message: str, path: str | None = None):
        super().__init__(message, path=path)
        self.code = code


class PermissionDeniedError(FsToolkitError):
    """权限层拒绝"""

    code = FsErrorCode.PERMISSION_DENIED

    def __init__(self, message: str, path: str | None = None):
        super().__init__(message, path=path)


class RiskBlockedError(FsToolkitError):
    """风险控制层拒绝（高风险操作）"""

    code = FsErrorCode.RISK_BLOCKED

    def __init__(self, message: str, path: str | None = None):
        super().__init__(message, path=path)


class FileOperationError(FsToolkitError):
    """业务操作失败（不存在 / 类型不符 / 非空 / 大小超限 / IO 失败）"""

    def __init__(self, code: FsErrorCode, message: str, path: str | None = None):
        super().__init__(message, path=path)
        self.code = code
