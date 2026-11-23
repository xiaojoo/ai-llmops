#!/usr/bin/env python
"""文件系统工具包 —— 安全层：路径守卫（PathGuard）。

统一入口 resolve()：所有工具路径都必须先经过这里，返回工作区内的绝对路径。

防护点（对应设计约定）：
1. 拒绝非法输入：空路径、NUL 字节、绝对路径、盘符、UNC（//server/share）
2. 虚拟根：以 "/" 开头的路径视为相对工作区根目录
3. 路径穿越：Path.resolve() 规范化后必须 is_relative_to(workspace)
   —— 不用字符串 startswith（"H:/project-evil".startswith("H:/project") 会误判）
4. 符号链接：resolve() 已跟随链接，resolve 后再做 realpath 复核，
   任何一层链接指向工作区外 → SYMLINK_ESCAPE
5. 额外根 allowed_roots / 禁止路径 denied_paths
6. follow_final=False（删除/移动）：只解析父目录，不跟随最后一段，
   保证“删除的是链接本身”而不是链接指向的目标
"""
import os
import re
from pathlib import Path

from ..models.responses import FsErrorCode, PathGuardError
from .policy import FileSystemPolicy

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PathGuard:
    """工作区路径守卫：所有路径解析与边界校验"""

    def __init__(self, policy: FileSystemPolicy):
        self.policy = policy

    def resolve(self, relative_path: str, *, must_exist: bool = False, follow_final: bool = True) -> Path:
        """相对路径 → 工作区内绝对路径（安全性校验通过后）

        follow_final=False：不解析最后一段（用于删除/移动符号链接本身）。
        """
        raw = relative_path
        if raw is None or not str(raw).strip():
            raise PathGuardError(FsErrorCode.INVALID_PATH, "路径不能为空", path=raw)

        path_str = str(raw).replace("\\", "/").strip()
        if "\x00" in path_str:
            raise PathGuardError(FsErrorCode.INVALID_PATH, "路径包含非法字符（NUL）", path=raw)

        # 虚拟根："/a/b" 视为工作区下 a/b；绝对路径 / 盘符 / UNC 一律拒绝
        if path_str.startswith("/") and not path_str.startswith("//"):
            path_str = path_str.lstrip("/")
        if os.path.isabs(path_str) or _DRIVE_RE.match(path_str) or path_str.startswith("//"):
            raise PathGuardError(
                FsErrorCode.INVALID_PATH,
                "禁止使用绝对路径/盘符/UNC，请使用相对工作区根目录的路径",
                path=raw,
            )

        workspace = self.policy.workspace
        try:
            if follow_final:
                lexical = (workspace / path_str).absolute()
                abs_path = lexical.resolve(strict=False)
            else:
                # 只解析父目录，最后一段保持原样（不跟随符号链接）
                candidate = (workspace / path_str).absolute()
                if candidate.name == "..":
                    raise PathGuardError(
                        FsErrorCode.INVALID_PATH,
                        f"路径不能以 '..' 结尾：'{raw}'",
                        path=raw,
                    )
                lexical = candidate
                parent = candidate.parent.resolve(strict=False)
                abs_path = parent / candidate.name
        except OSError as e:
            raise PathGuardError(FsErrorCode.INVALID_PATH, f"路径解析失败：{e}", path=raw) from e

        self._assert_within_roots(abs_path, lexical, raw, follow_final=follow_final)

        if must_exist and not abs_path.exists() and not abs_path.is_symlink():
            raise PathGuardError(FsErrorCode.PATH_NOT_FOUND, "路径不存在", path=raw)

        return abs_path

    def to_rel(self, abs_path: Path) -> str:
        """绝对路径 → 工作区相对路径（用于展示/审计）"""
        try:
            return str(abs_path.relative_to(self.policy.workspace))
        except ValueError:
            return str(abs_path)

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _assert_within_roots(self, abs_path: Path, lexical: Path, raw: str, *, follow_final: bool) -> None:
        """边界校验：allowed roots 之内、denied paths 之外、符号链接不逃逸"""
        workspace = self.policy.workspace
        roots = [workspace, *self.policy.allowed_roots]

        # 1) 解析后的路径必须位于工作区或额外根内
        if not any(abs_path.is_relative_to(r) for r in roots):
            # 区分：符号链接指向外部（SYMLINK_ESCAPE）还是纯 .. 越界（PATH_TRAVERSAL）
            if self._any_symlink_on_path(lexical, workspace):
                raise PathGuardError(
                    FsErrorCode.SYMLINK_ESCAPE,
                    f"符号链接指向工作区之外：'{raw}'",
                    path=raw,
                )
            raise PathGuardError(
                FsErrorCode.PATH_TRAVERSAL,
                f"路径越界：'{raw}' 超出工作区范围 '{workspace}'",
                path=raw,
            )

        # 2) 符号链接复核：realpath 同样必须在允许根内
        #    （follow_final=False 时只校验父目录链——删除/移动链接本身是安全的；
        #     目标就是根本身时跳过，根删除由 RiskControl 拦截）
        if follow_final:
            check_target = abs_path
        elif abs_path != workspace and abs_path not in roots:
            check_target = abs_path.parent
        else:
            check_target = abs_path
        real = Path(os.path.realpath(check_target))
        if not any(real.is_relative_to(r) for r in roots):
            raise PathGuardError(
                FsErrorCode.SYMLINK_ESCAPE,
                f"符号链接指向工作区之外：'{raw}'",
                path=raw,
            )

        # 3) 禁止路径（命中自身或任意祖先即拒绝）
        for denied in self.policy.denied_paths:
            if abs_path.is_relative_to(denied) or denied.is_relative_to(abs_path):
                raise PathGuardError(
                    FsErrorCode.PERMISSION_DENIED,
                    f"路径 '{raw}' 命中禁止访问清单",
                    path=raw,
                )

    def _any_symlink_on_path(self, lexical: Path, workspace: Path) -> bool:
        """从工作区根沿未解析路径逐级检查是否存在符号链接（用于区分逃逸原因）"""
        try:
            rel = lexical.relative_to(workspace)
        except ValueError:
            return False
        cur = workspace
        for part in rel.parts:
            if part in (".", ".."):
                cur = (cur / part).resolve() if part == ".." else cur
                continue
            cur = cur / part
            try:
                if cur.is_symlink():
                    return True
            except OSError:
                pass
        return False
