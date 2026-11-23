#!/usr/bin/env python
"""文件系统工具包 —— 服务层：文件服务（FileService）。

Tool → Service → Security → OS 分层中的业务实现层：
只做“工作区内”的纯业务操作，路径解析统一走 PathGuard，
能力开关统一走 PermissionChecker，高危操作统一走 RiskControl。
"""
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path

from ..models.responses import (
    FileOperationError,
    FsErrorCode,
    ok,
)
from ..security.path_guard import PathGuard
from ..security.permission import PermissionChecker
from ..security.policy import FileSystemPermission, FileSystemPolicy
from ..security.risk import RiskControl
from .trash_service import TrashService


def _fmt_size(size_bytes: int) -> str:
    """字节数 → 可读大小"""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006 - 仅本地时间展示


def _entry_info(path: Path, rel: str) -> dict:
    """文件/目录 → 结构化信息（不跟随符号链接）"""
    st = os.stat(path, follow_symlinks=False)
    is_link = path.is_symlink()
    is_dir = path.is_dir() and not is_link
    etype = "symlink" if is_link else ("directory" if is_dir else "file")
    info = {
        "name": path.name,
        "path": rel,
        "type": etype,
        "size": st.st_size,
        "size_human": "-" if is_dir else _fmt_size(st.st_size),
        "modified": _fmt_time(st.st_mtime),
        "created": _fmt_time(st.st_ctime),
        "permissions": stat.filemode(st.st_mode),
    }
    if is_link:
        try:
            info["target"] = str(path.readlink())
        except OSError:
            info["target"] = None
    return info


class FileService:
    """文件系统业务操作（全部经由安全层）"""

    def __init__(
        self,
        policy: FileSystemPolicy,
        path_guard: PathGuard,
        permission: PermissionChecker,
        risk: RiskControl,
        trash: TrashService,
    ):
        self.policy = policy
        self.path_guard = path_guard
        self.permission = permission
        self.risk = risk
        self.trash = trash

    # ── 读类 ──────────────────────────────────────────────────────────────

    def list_dir(self, path: str, show_hidden: bool = False) -> dict:
        self.permission.check(FileSystemPermission.READ, path)
        abs_path = self.path_guard.resolve(path, must_exist=True)
        if not abs_path.is_dir():
            raise FileOperationError(FsErrorCode.NOT_DIRECTORY, f"'{path}' 不是一个目录", path=path)

        try:
            entries = list(abs_path.iterdir())
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限读取目录：'{path}'", path=path) from None

        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        # 目录在前，文件在后，同类按名称字母序
        entries.sort(key=lambda e: (not (e.is_dir() and not e.is_symlink()), e.name.lower()))

        limit = self.policy.max_list_entries
        truncated = len(entries) > limit
        shown = entries[:limit]

        items = []
        for entry in shown:
            try:
                rel = self.path_guard.to_rel(entry)
                items.append(_entry_info(entry, rel))
            except OSError:
                items.append({"name": entry.name, "path": self.path_guard.to_rel(entry), "type": "unknown"})

        return ok(
            "list",
            path=path or ".",
            total=len(entries),
            shown=len(items),
            truncated=truncated,
            entries=items,
        )

    def stat(self, path: str) -> dict:
        self.permission.check(FileSystemPermission.READ, path)
        abs_path = self.path_guard.resolve(path, must_exist=True)
        rel = self.path_guard.to_rel(abs_path)
        return ok("stat", path=rel, **{k: v for k, v in _entry_info(abs_path, rel).items() if k != "path"})

    def read_file(
        self,
        path: str,
        encoding: str = "utf-8",
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict:
        self.permission.check(FileSystemPermission.READ, path)
        abs_path = self.path_guard.resolve(path, must_exist=True)
        if not abs_path.is_file():
            raise FileOperationError(FsErrorCode.IS_DIRECTORY, f"'{path}' 不是一个文件", path=path)

        # 大小上限保护
        try:
            size = abs_path.stat().st_size
        except OSError as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"读取文件信息失败：{e}", path=path) from e
        if size > self.policy.max_read_bytes:
            raise FileOperationError(
                FsErrorCode.SIZE_LIMIT_EXCEEDED,
                f"文件大小 {_fmt_size(size)} 超过单次读取上限 {_fmt_size(self.policy.max_read_bytes)}，"
                "请使用 fs_stat 确认大小或调整策略",
                path=path,
            )

        try:
            with open(abs_path, encoding=encoding, errors="replace") as f:
                all_lines = f.readlines()
        except LookupError:
            raise FileOperationError(FsErrorCode.ENCODING_ERROR, f"不支持的编码格式：'{encoding}'", path=path) from None
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限读取文件：'{path}'", path=path) from None
        except OSError as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"读取文件失败：{e}", path=path) from e

        total = len(all_lines)
        if start_line is not None and start_line < 1:
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "start_line 必须 >= 1", path=path)
        if end_line is not None and end_line < 1:
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "end_line 必须 >= 1", path=path)
        if start_line is not None and end_line is not None and start_line > end_line:
            raise FileOperationError(
                FsErrorCode.INVALID_ARGUMENT, "start_line 不能大于 end_line", path=path
            )

        s = (start_line - 1) if start_line else 0
        e = end_line if (end_line and end_line <= total) else total
        selected = all_lines[s:e]
        content = "".join(selected)

        truncated = len(content) > self.policy.max_read_chars
        if truncated:
            content = content[: self.policy.max_read_chars]

        return ok(
            "read",
            path=self.path_guard.to_rel(abs_path),
            encoding=encoding,
            size=size,
            size_human=_fmt_size(size),
            content=content,
            start_line=s + 1,
            end_line=s + len(selected),
            total_lines=total,
            char_count=len(content),
            truncated=truncated,
        )

    # ── 写类 ──────────────────────────────────────────────────────────────

    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> dict:
        self.permission.check(FileSystemPermission.WRITE, path)
        abs_path = self.path_guard.resolve(path)
        if abs_path.is_dir():
            raise FileOperationError(FsErrorCode.ALREADY_EXISTS, f"'{path}' 已存在且是目录", path=path)

        try:
            data = content.encode(encoding)
        except LookupError:
            raise FileOperationError(FsErrorCode.ENCODING_ERROR, f"不支持的编码格式：'{encoding}'", path=path) from None
        except UnicodeEncodeError as e:
            raise FileOperationError(
                FsErrorCode.ENCODING_ERROR, f"内容无法用 '{encoding}' 编码：{e}", path=path
            ) from e

        if len(data) > self.policy.max_file_size:
            raise FileOperationError(
                FsErrorCode.SIZE_LIMIT_EXCEEDED,
                f"写入内容 {_fmt_size(len(data))} 超过单文件上限 {_fmt_size(self.policy.max_file_size)}",
                path=path,
            )

        created = not abs_path.exists()
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(data)
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限写入：'{path}'", path=path) from None
        except OSError as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"写入失败：{e}", path=path) from e

        return ok(
            "write",
            path=self.path_guard.to_rel(abs_path),
            bytes_written=len(data),
            chars_written=len(content),
            created=created,
            size=abs_path.stat().st_size,
            size_human=_fmt_size(abs_path.stat().st_size),
        )

    def edit_file(self, path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> dict:
        """精确替换：old_text 必须存在；多处命中时仅替换第一处并在结果中提示"""
        self.permission.check(FileSystemPermission.WRITE, path)
        abs_path = self.path_guard.resolve(path, must_exist=True)
        if not abs_path.is_file():
            raise FileOperationError(FsErrorCode.IS_DIRECTORY, f"'{path}' 不是一个文件", path=path)

        try:
            content = abs_path.read_text(encoding=encoding, errors="replace")
        except LookupError:
            raise FileOperationError(FsErrorCode.ENCODING_ERROR, f"不支持的编码格式：'{encoding}'", path=path) from None
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限读取文件：'{path}'", path=path) from None
        except OSError as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"读取文件失败：{e}", path=path) from e

        if not old_text:
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "old_text 不能为空", path=path)

        occurrences = content.count(old_text)
        if occurrences == 0:
            raise FileOperationError(
                FsErrorCode.TARGET_NOT_FOUND,
                "未找到目标文本（old_text），请先 fs_read 确认当前内容后再编辑",
                path=path,
            )

        idx = content.find(old_text)
        changed_line = content[:idx].count("\n") + 1
        new_content = content.replace(old_text, new_text, 1)

        try:
            data = new_content.encode(encoding)
        except UnicodeEncodeError as e:
            raise FileOperationError(
                FsErrorCode.ENCODING_ERROR, f"新内容无法用 '{encoding}' 编码：{e}", path=path
            ) from e
        if len(data) > self.policy.max_file_size:
            raise FileOperationError(
                FsErrorCode.SIZE_LIMIT_EXCEEDED,
                f"修改后文件 {_fmt_size(len(data))} 超过单文件上限 {_fmt_size(self.policy.max_file_size)}",
                path=path,
            )

        try:
            abs_path.write_bytes(data)
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限写入：'{path}'", path=path) from None
        except OSError as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"写入失败：{e}", path=path) from e

        return ok(
            "edit",
            path=self.path_guard.to_rel(abs_path),
            old_text_chars=len(old_text),
            new_text_chars=len(new_text),
            replaced_count=1,
            occurrences=occurrences,
            changed_line=changed_line,
            bytes_written=len(data),
            size=abs_path.stat().st_size,
            size_human=_fmt_size(abs_path.stat().st_size),
            warning=(
                f"目标文本出现 {occurrences} 次，本次仅替换第 1 处（第 {changed_line} 行）"
                if occurrences > 1
                else None
            ),
        )

    def mkdir(self, path: str) -> dict:
        self.permission.check(FileSystemPermission.WRITE, path)
        abs_path = self.path_guard.resolve(path)
        if abs_path.is_file():
            raise FileOperationError(FsErrorCode.ALREADY_EXISTS, f"'{path}' 已存在且是文件，无法创建同名目录", path=path)

        existed = abs_path.is_dir()
        if not existed:
            try:
                abs_path.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限创建目录：'{path}'", path=path) from None
            except OSError as e:
                raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"创建目录失败：{e}", path=path) from e

        return ok(
            "mkdir",
            path=self.path_guard.to_rel(abs_path),
            created=not existed,
            existed=existed,
        )

    # ── 复制 / 移动 ────────────────────────────────────────────────────────

    def copy(self, src: str, dst: str, overwrite: bool = False) -> dict:
        self.permission.check(FileSystemPermission.WRITE, src)
        abs_src = self.path_guard.resolve(src, must_exist=True)
        abs_dst = self.path_guard.resolve(dst)
        if abs_src == abs_dst:
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "源路径与目标路径相同", path=src)
        if abs_dst.exists() and not overwrite:
            raise FileOperationError(
                FsErrorCode.ALREADY_EXISTS,
                f"目标已存在：'{dst}'；如需覆盖请设置 overwrite=true",
                path=dst,
            )

        try:
            abs_dst.parent.mkdir(parents=True, exist_ok=True)
            if abs_src.is_dir() and not abs_src.is_symlink():
                if abs_dst.exists():
                    shutil.rmtree(abs_dst)
                shutil.copytree(abs_src, abs_dst)
                item_count = sum(1 for _ in abs_dst.rglob("*"))
                return ok(
                    "copy",
                    src=self.path_guard.to_rel(abs_src),
                    dst=self.path_guard.to_rel(abs_dst),
                    kind="directory",
                    item_count=item_count,
                )
            if abs_src.is_symlink() or abs_src.is_file():
                if abs_dst.exists():
                    os.remove(abs_dst)
                shutil.copy2(abs_src, abs_dst)
                return ok(
                    "copy",
                    src=self.path_guard.to_rel(abs_src),
                    dst=self.path_guard.to_rel(abs_dst),
                    kind="file",
                    bytes_copied=abs_dst.stat().st_size,
                    size_human=_fmt_size(abs_dst.stat().st_size),
                )
            raise FileOperationError(FsErrorCode.PATH_NOT_FOUND, f"源路径不存在：'{src}'", path=src)
        except FileOperationError:
            raise
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限复制：'{src}' → '{dst}'", path=src) from None
        except (shutil.Error, OSError) as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"复制失败：{e}", path=src) from e

    def move(self, src: str, dst: str) -> dict:
        self.permission.check(FileSystemPermission.WRITE, src)
        # follow_final=False：移动符号链接时移动的是链接本身（等价于 mv）
        abs_src = self.path_guard.resolve(src, must_exist=True, follow_final=False)
        abs_dst = self.path_guard.resolve(dst)
        if abs_src == abs_dst:
            raise FileOperationError(FsErrorCode.INVALID_ARGUMENT, "源路径与目标路径相同", path=src)
        if abs_dst.exists():
            raise FileOperationError(FsErrorCode.ALREADY_EXISTS, f"目标已存在：'{dst}'", path=dst)

        try:
            abs_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(abs_src), str(abs_dst))
        except PermissionError:
            raise FileOperationError(FsErrorCode.PERMISSION_DENIED, f"没有权限移动：'{src}' → '{dst}'", path=src) from None
        except (shutil.Error, OSError) as e:
            raise FileOperationError(FsErrorCode.OPERATION_FAILED, f"移动失败：{e}", path=src) from e

        return ok(
            "move",
            src=self.path_guard.to_rel(abs_src),
            dst=self.path_guard.to_rel(abs_dst),
        )

    # ── 删除（高危，先进回收站） ─────────────────────────────────────────────

    def delete(self, path: str, recursive: bool = False) -> dict:
        self.permission.check(FileSystemPermission.DELETE, path)
        # follow_final=False：删除符号链接时删除的是链接本身，绝不跟随
        abs_path = self.path_guard.resolve(path, follow_final=False)
        if not abs_path.exists() and not abs_path.is_symlink():
            raise FileOperationError(FsErrorCode.PATH_NOT_FOUND, "路径不存在", path=path)

        # 风险控制：禁止删根 / 内部目录；非空目录需 recursive
        self.risk.assert_deletable(abs_path, recursive, path)

        trash_dest = self.trash.trash(abs_path, path)
        return ok(
            "delete",
            path=self.path_guard.to_rel(abs_path),
            trashed=True,
            trash_path=self.path_guard.to_rel(trash_dest),
            recoverable=True,
            restore_hint="文件已进入回收站 .agent-trash/，可手工移回原路径恢复（V2 将提供 fs_restore）",
        )
