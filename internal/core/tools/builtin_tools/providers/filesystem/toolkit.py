#!/usr/bin/env python
"""文件系统工具包 —— 门面（FileSystemToolkit）。

架构（对应设计约定）：

    Agent → ToolCall Dispatcher → FileSystemToolkit → 安全层 → Service → OS → Audit

- 所有工具方法返回 JSON 字符串（结构化响应，Agent 可直接解析）
- 统一捕获 FsToolkitError → 失败响应；未知异常 → OPERATION_FAILED
- 每次调用写审计日志（trace_id / agent_id / tool / path / 耗时 / 成败）

进程级默认实例：get_toolkit()（惰性创建，FILESYSTEM_WORKSPACE 优先，
本地兜底 <项目根>/storage/agent-workspace）。
"""
import time
from collections.abc import Callable
from typing import Any

from .models.responses import FsErrorCode, FsToolkitError, fail, to_json
from .security.path_guard import PathGuard
from .security.permission import PermissionChecker
from .security.policy import FileSystemPolicy, default_policy
from .security.risk import RiskControl
from .service.audit_service import AuditLogger
from .service.file_service import FileService
from .service.search_service import SearchService
from .service.trash_service import TrashService


class FileSystemToolkit:
    """受控文件系统工具包：Agent 只能通过这些方法访问工作区文件"""

    def __init__(
        self,
        policy: FileSystemPolicy | None = None,
        audit: AuditLogger | None = None,
    ):
        self.policy = policy or default_policy()
        self.path_guard = PathGuard(self.policy)
        self.permission = PermissionChecker(self.policy)
        self.trash = TrashService(self.policy, self.path_guard)
        self.risk = RiskControl(self.policy)
        self.file_service = FileService(
            policy=self.policy,
            path_guard=self.path_guard,
            permission=self.permission,
            risk=self.risk,
            trash=self.trash,
        )
        self.search_service = SearchService(self.policy, self.path_guard, self.permission)
        self.audit = audit or AuditLogger(self.policy.audit_root)

    # ── 10 个工具 ──────────────────────────────────────────────────────────

    def fs_list(self, path: str = ".", show_hidden: bool = False) -> str:
        return self._run("fs_list", "list", self.file_service.list_dir, path=path, show_hidden=show_hidden)

    def fs_stat(self, path: str) -> str:
        return self._run("fs_stat", "stat", self.file_service.stat, path=path)

    def fs_read(self, path: str, start_line: int | None = None, end_line: int | None = None, encoding: str = "utf-8") -> str:
        return self._run(
            "fs_read", "read", self.file_service.read_file,
            path=path, start_line=start_line, end_line=end_line, encoding=encoding,
        )

    def fs_write(self, path: str, content: str, encoding: str = "utf-8") -> str:
        return self._run("fs_write", "write", self.file_service.write_file, path=path, content=content, encoding=encoding)

    def fs_edit(self, path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> str:
        return self._run(
            "fs_edit", "edit", self.file_service.edit_file,
            path=path, old_text=old_text, new_text=new_text, encoding=encoding,
        )

    def fs_mkdir(self, path: str) -> str:
        return self._run("fs_mkdir", "mkdir", self.file_service.mkdir, path=path)

    def fs_copy(self, src: str, dst: str, overwrite: bool = False) -> str:
        return self._run("fs_copy", "copy", self.file_service.copy, src=src, dst=dst, overwrite=overwrite)

    def fs_move(self, src: str, dst: str) -> str:
        return self._run("fs_move", "move", self.file_service.move, src=src, dst=dst)

    def fs_delete(self, path: str, recursive: bool = False) -> str:
        return self._run("fs_delete", "delete", self.file_service.delete, path=path, recursive=recursive)

    def fs_search(self, pattern: str, root: str = ".", include_hidden: bool = False, limit: int = 100) -> str:
        return self._run(
            "fs_search", "search", self.search_service.search,
            pattern=pattern, root=root, include_hidden=include_hidden, limit=limit,
        )

    # ── 统一执行管线：异常 → 失败响应 + 审计 ──────────────────────────────────

    def _run(self, tool: str, operation: str, fn: Callable, **kwargs: Any) -> str:
        start = time.perf_counter()
        display_path = kwargs.get("path") or kwargs.get("src")
        try:
            result = fn(**kwargs)
            success = bool(result.get("success"))
            error_code = None
        except FsToolkitError as e:
            result = e.to_result(operation)
            success = False
            error_code = e.code.value if isinstance(e.code, FsErrorCode) else str(e.code)
        except Exception as e:  # noqa: BLE001 - 兜底：绝不把异常泄漏给 Agent
            result = fail(operation, FsErrorCode.OPERATION_FAILED, f"操作失败：{e}", path=display_path)
            success = False
            error_code = str(FsErrorCode.OPERATION_FAILED)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.audit.log(
                tool=tool,
                operation=operation,
                path=display_path,
                success=success,
                duration_ms=duration_ms,
                error_code=error_code,
            )
        return to_json(result)


_toolkit: FileSystemToolkit | None = None


def get_toolkit() -> FileSystemToolkit:
    """进程级默认工具包实例（惰性创建）"""
    global _toolkit
    if _toolkit is None:
        _toolkit = FileSystemToolkit()
    return _toolkit
