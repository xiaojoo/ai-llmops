#!/usr/bin/env python
"""文件系统工具包 —— 服务层：搜索服务（SearchService）。

在工作区内按 glob 模式搜索文件/目录：
- pattern 不含 "/" 时按“文件名”匹配（任意深度）；含 "/" 时按相对路径匹配
- 默认跳过隐藏目录与工具包内部目录（.agent-trash / .agent-audit）
- 结果数受 max_search_results 限制
"""
import fnmatch
import os
from pathlib import Path

from ..models.responses import FileOperationError, FsErrorCode, ok
from ..security.path_guard import PathGuard
from ..security.permission import PermissionChecker
from ..security.policy import FileSystemPermission, FileSystemPolicy


class SearchService:
    """工作区文件搜索"""

    def __init__(
        self,
        policy: FileSystemPolicy,
        path_guard: PathGuard,
        permission: PermissionChecker,
    ):
        self.policy = policy
        self.path_guard = path_guard
        self.permission = permission

    def search(
        self,
        pattern: str,
        root: str = ".",
        include_hidden: bool = False,
        limit: int = 100,
    ) -> dict:
        self.permission.check(FileSystemPermission.READ, root)
        if not pattern or not pattern.strip():
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "pattern 不能为空", path=root)
        if limit < 1:
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "limit 必须 >= 1", path=root)

        limit = min(limit, self.policy.max_search_results)
        abs_root = self.path_guard.resolve(root, must_exist=True)
        if not abs_root.is_dir():
            raise FileOperationError(FsErrorCode.NOT_DIRECTORY, f"'{root}' 不是一个目录", path=root)

        pattern = pattern.replace("\\", "/").strip()
        # "**/*.py" → "*.py"（任意深度按文件名匹配）
        pattern = pattern.removeprefix("**/")
        match_by_path = "/" in pattern

        matches: list[dict] = []
        total = 0
        truncated = False
        skip_prefixes = (self.policy.trash_dir_name, self.policy.audit_dir_name)

        try:
            for dirpath, dirnames, filenames in os.walk(str(abs_root), topdown=True, onerror=None, followlinks=False):
                rel_dir = self.path_guard.to_rel(Path(dirpath))

                # 剪枝：隐藏目录 / 内部目录（除非 include_hidden）
                kept_dirs = []
                for d in sorted(dirnames):
                    if d in skip_prefixes:
                        continue
                    if not include_hidden and d.startswith("."):
                        continue
                    kept_dirs.append(d)
                dirnames[:] = kept_dirs

                entries = sorted(dirnames, key=lambda n: (True, n)) + sorted(
                    filenames, key=lambda n: (False, n)
                )
                for name in entries:
                    is_dir = name in dirnames
                    rel_dir_norm = rel_dir.replace(os.sep, "/")
                    rel = f"{rel_dir_norm}/{name}" if rel_dir_norm != "." else name
                    if match_by_path:
                        matched = fnmatch.fnmatch(rel, pattern)
                    else:
                        matched = fnmatch.fnmatch(name, pattern)
                    if not matched:
                        continue
                    total += 1
                    if len(matches) >= limit:
                        truncated = True
                        break
                    matches.append(
                        {
                            "path": rel,
                            "type": "directory" if is_dir else "file",
                        }
                    )
                if truncated:
                    break
        except PermissionError:
            raise FileOperationError(
                FsErrorCode.PERMISSION_DENIED, f"没有权限搜索目录：'{root}'", path=root
            ) from None
        except OSError as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"搜索失败：{e}", path=root) from e

        return ok(
            "search",
            pattern=pattern,
            root=root or ".",
            total_found=total,
            shown=len(matches),
            truncated=truncated,
            matches=matches,
        )
