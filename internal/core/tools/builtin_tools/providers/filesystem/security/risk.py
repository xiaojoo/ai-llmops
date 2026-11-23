#!/usr/bin/env python
"""文件系统工具包 —— 安全层：风险控制（RiskControl）。

高风险操作（删除类）统一在此把关：
- 禁止删除工作区根目录
- 禁止删除/触碰工具包内部目录（.agent-trash 回收站、.agent-audit 审计日志）
- 非空目录必须显式 recursive=true，否则 NOT_EMPTY
- 删除一律先进回收站（见 service.trash_service），不直接 os.remove
"""
from pathlib import Path

from ..models.responses import FileOperationError, FsErrorCode, RiskBlockedError
from .policy import FileSystemPolicy


class RiskControl:
    """删除等高危操作的二次确认与拦截"""

    def __init__(self, policy: FileSystemPolicy):
        self.policy = policy

    def assert_deletable(self, abs_path: Path, recursive: bool, raw_path: str) -> None:
        """删除前置风险校验，不通过则抛异常"""
        # 1) 禁止删除工作区根目录
        if abs_path == self.policy.workspace:
            raise RiskBlockedError("禁止删除工作区根目录本身", path=raw_path)

        # 2) 禁止删除工具包内部目录（回收站 / 审计日志）
        if self.policy.is_internal_dir(abs_path):
            raise RiskBlockedError("禁止删除回收站/审计日志等工具包内部目录", path=raw_path)

        # 3) 非空目录必须显式 recursive=true
        if abs_path.is_dir() and not abs_path.is_symlink():
            try:
                is_empty = not any(abs_path.iterdir())
            except OSError:
                is_empty = False
            if not is_empty and not recursive:
                raise FileOperationError(
                    FsErrorCode.NOT_EMPTY,
                    "目录非空，无法直接删除；如需递归删除整个目录树请将 recursive 设为 true（删除会进入回收站）",
                    path=raw_path,
                )
