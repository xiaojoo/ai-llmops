#!/usr/bin/env python
"""文件系统工具包 —— 服务层：回收站（TrashService）。

fs_delete 不直接 os.remove，而是把文件/目录“移入”回收站：

    <workspace>/.agent-trash/<UTC时间戳>-<随机后缀>/<原相对路径>

删除后仍可恢复（V2 提供 fs_restore / 手工移回），实现"Agent 删错还能救"。
"""
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..models.responses import FileOperationError, FsErrorCode
from ..security.path_guard import PathGuard
from ..security.policy import FileSystemPolicy


class TrashService:
    """回收站服务：删除 = 移入回收站"""

    def __init__(self, policy: FileSystemPolicy, path_guard: PathGuard):
        self.policy = policy
        self.path_guard = path_guard

    def trash(self, abs_path: Path, raw_path: str) -> Path:
        """把目标移动到回收站，返回回收站内的绝对路径"""
        abs_path = Path(abs_path)
        session_dir = self._new_session_dir()
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            rel = self.path_guard.to_rel(abs_path)
            # 原路径可能是 a/b/c.txt，保持目录结构便于恢复
            dest = session_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(abs_path), str(dest))
            return dest
        except OSError as e:
            raise FileOperationError(
                FsErrorCode.OPERATION_FAILED,
                f"移入回收站失败：{e}",
                path=raw_path,
            ) from e

    def _new_session_dir(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        return self.policy.trash_root / f"{stamp}-{suffix}"
