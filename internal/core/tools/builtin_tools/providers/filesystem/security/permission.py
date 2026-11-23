#!/usr/bin/env python
"""文件系统工具包 —— 安全层：权限检查（PermissionChecker）。"""
from ..models.responses import PermissionDeniedError
from .policy import FileSystemPermission, FileSystemPolicy


class PermissionChecker:
    """按 FileSystemPolicy.permissions 校验工具能力开关"""

    def __init__(self, policy: FileSystemPolicy):
        self.policy = policy

    def check(self, perm: FileSystemPermission, path: str) -> None:
        """不允许时抛 PermissionDeniedError"""
        if not self.policy.allow(perm):
            raise PermissionDeniedError(
                f"当前策略禁止 {perm.value} 操作（FileSystemPolicy.permissions 未开启）",
                path=path,
            )
