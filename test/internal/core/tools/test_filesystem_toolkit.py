#!/usr/bin/env python
"""文件系统工具包（受控版）测试：10 个工具 + 安全层（路径沙箱/符号链接/权限/大小/回收站/审计）。

纯本地测试（无需 DB）：用 repo/tmp/fs-toolkit-tests 下独立目录作为工作区。
注意：测试目录用 os.makedirs 创建（DSH 沙箱下 tempfile.mkdtemp/pytest tmp_path 不可写）。
"""
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from internal.core.tools.builtin_tools.providers.filesystem.security.policy import (
    FileSystemPermission,
    FileSystemPolicy,
)
from internal.core.tools.builtin_tools.providers.filesystem.toolkit import (
    FileSystemToolkit,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _make_toolkit(workspace: Path, **policy_kwargs) -> FileSystemToolkit:
    policy = FileSystemPolicy(workspace=workspace, **policy_kwargs)
    policy.workspace.mkdir(parents=True, exist_ok=True)
    return FileSystemToolkit(policy=policy)


def _load(result_str: str) -> dict:
    return json.loads(result_str)


@pytest.fixture()
def ws_dir():
    base = _REPO_ROOT / "tmp" / "fs-toolkit-tests"
    base.mkdir(parents=True, exist_ok=True)
    d = base / f"ws-{uuid4().hex[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def toolkit(ws_dir):
    return _make_toolkit(ws_dir / "workspace")


class TestBasicOps:
    def test_fs_write_creates_and_overwrites(self, toolkit, ws_dir):
        r1 = _load(toolkit.fs_write("src/main.py", "timeout = 30\n"))
        assert r1["success"] and r1["created"] is True
        assert r1["bytes_written"] == len("timeout = 30\n")

        r2 = _load(toolkit.fs_write("src/main.py", "timeout = 60\n"))
        assert r2["success"] and r2["created"] is False
        assert (ws_dir / "workspace" / "src" / "main.py").read_text() == "timeout = 60\n"

    def test_fs_read_full_and_range(self, toolkit):
        toolkit.fs_write("a.txt", "l1\nl2\nl3\nl4\n")
        full = _load(toolkit.fs_read("a.txt"))
        assert full["total_lines"] == 4 and full["content"] == "l1\nl2\nl3\nl4\n"

        part = _load(toolkit.fs_read("a.txt", start_line=2, end_line=3))
        assert part["start_line"] == 2 and part["end_line"] == 3
        assert part["content"] == "l2\nl3\n"

    def test_fs_edit_replaces_first_occurrence(self, toolkit, ws_dir):
        toolkit.fs_write("a.txt", "x=1\ny=2\nx=1\n")
        r = _load(toolkit.fs_edit("a.txt", "x=1", "x=9"))
        assert r["success"]
        assert r["occurrences"] == 2 and r["replaced_count"] == 1
        assert (ws_dir / "workspace" / "a.txt").read_text() == "x=9\ny=2\nx=1\n"

    def test_fs_edit_target_not_found(self, toolkit):
        toolkit.fs_write("a.txt", "hello")
        r = _load(toolkit.fs_edit("a.txt", "nope", "x"))
        assert not r["success"] and r["error"]["code"] == "TARGET_NOT_FOUND"

    def test_fs_mkdir_copy_move_delete_list_stat_search(self, toolkit, ws_dir):
        assert _load(toolkit.fs_mkdir("proj/src"))["success"]

        toolkit.fs_write("proj/src/app.py", "print(1)\n")
        toolkit.fs_write("proj/README.md", "# readme\n")

        copied = _load(toolkit.fs_copy("proj/src/app.py", "proj/src/app_copy.py"))
        assert copied["success"] and copied["kind"] == "file"

        moved = _load(toolkit.fs_move("proj/src/app_copy.py", "proj/src/moved.py"))
        assert moved["success"]
        assert not (ws_dir / "workspace" / "proj" / "src" / "app_copy.py").exists()

        listing = _load(toolkit.fs_list("proj"))
        names = {e["name"] for e in listing["entries"]}
        assert {"src", "README.md"} <= names

        stat = _load(toolkit.fs_stat("proj/README.md"))
        assert stat["success"] and stat["type"] == "file" and stat["size"] > 0

        found = _load(toolkit.fs_search("*.py", root="proj"))
        paths = {m["path"] for m in found["matches"]}
        assert {"proj/src/app.py", "proj/src/moved.py"} <= paths

        deleted = _load(toolkit.fs_delete("proj/README.md"))
        assert deleted["success"] and deleted["trashed"] is True
        assert not (ws_dir / "workspace" / "proj" / "README.md").exists()

    def test_fs_delete_non_empty_dir_requires_recursive(self, toolkit):
        toolkit.fs_write("d/keep.txt", "x")
        r = _load(toolkit.fs_delete("d"))
        assert not r["success"] and r["error"]["code"] == "NOT_EMPTY"
        r2 = _load(toolkit.fs_delete("d", recursive=True))
        assert r2["success"] and r2["trashed"] is True

    def test_fs_delete_goes_to_trash_and_recovers(self, toolkit, ws_dir):
        toolkit.fs_write("important.txt", "secret")
        r = _load(toolkit.fs_delete("important.txt"))
        assert r["success"]
        trash_path = ws_dir / "workspace" / r["trash_path"]
        assert trash_path.exists() and trash_path.read_text() == "secret"
        # 手工恢复
        trash_path.replace(ws_dir / "workspace" / "important.txt")
        assert (ws_dir / "workspace" / "important.txt").read_text() == "secret"

    def test_fs_list_hidden_visibility(self, toolkit):
        toolkit.fs_write(".hidden.txt", "x")
        listing = _load(toolkit.fs_list("."))
        assert all(e["name"] != ".hidden.txt" for e in listing["entries"])
        listing2 = _load(toolkit.fs_list(".", show_hidden=True))
        assert any(e["name"] == ".hidden.txt" for e in listing2["entries"])


class TestSecurity:
    def test_path_traversal_rejected(self, toolkit, ws_dir):
        outside = ws_dir / "outside.txt"
        outside.write_text("secret")
        r = _load(toolkit.fs_read("../outside.txt"))
        assert not r["success"] and r["error"]["code"] == "PATH_TRAVERSAL"

    def test_absolute_and_drive_paths_rejected(self, toolkit):
        # 盘符 / UNC：直接拒绝 INVALID_PATH
        for p in ["C:/Windows/System32/config/SAM", "//server/share"]:
            r = _load(toolkit.fs_read(p))
            assert not r["success"] and r["error"]["code"] == "INVALID_PATH", p
        # 类 POSIX 绝对路径 "/x"：按虚拟根映射到工作区（绝无宿主访问），不存在 → PATH_NOT_FOUND
        r = _load(toolkit.fs_read("/etc/passwd"))
        assert not r["success"] and r["error"]["code"] == "PATH_NOT_FOUND"

    def test_project_evil_prefix_not_mistaken_for_workspace(self, toolkit, ws_dir):
        """startswith 陷阱回归：H:/project-evil 不应算作 H:/project 之内"""
        (ws_dir / "workspace-evil").mkdir()
        (ws_dir / "workspace-evil" / "x.txt").write_text("evil")
        r = _load(toolkit.fs_read("../workspace-evil/x.txt"))
        assert not r["success"] and r["error"]["code"] == "PATH_TRAVERSAL"

    def test_symlink_escape_rejected(self, toolkit, ws_dir):
        target = ws_dir / "outside-dir"
        target.mkdir()
        (target / "secret.txt").write_text("secret")
        try:
            (toolkit.policy.workspace / "link").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("当前环境无符号链接权限（Windows 需管理员/开发者模式）")
        r = _load(toolkit.fs_read("link/secret.txt"))
        assert not r["success"] and r["error"]["code"] == "SYMLINK_ESCAPE"

    def test_delete_workspace_root_rejected(self, toolkit):
        r = _load(toolkit.fs_delete("."))
        assert not r["success"] and r["error"]["code"] == "RISK_BLOCKED"

    def test_permission_delete_disabled(self, ws_dir):
        toolkit = _make_toolkit(ws_dir / "workspace", permissions={FileSystemPermission.DELETE: False})
        toolkit.fs_write("a.txt", "x")
        r = _load(toolkit.fs_delete("a.txt"))
        assert not r["success"] and r["error"]["code"] == "PERMISSION_DENIED"

    def test_write_size_limit(self, ws_dir):
        toolkit = _make_toolkit(ws_dir / "workspace", max_file_size=10)
        r = _load(toolkit.fs_write("big.txt", "x" * 100))
        assert not r["success"] and r["error"]["code"] == "SIZE_LIMIT_EXCEEDED"

    def test_internal_dirs_not_deletable_and_hidden_from_search(self, toolkit):
        toolkit.fs_write("a.txt", "x")
        toolkit.fs_delete("a.txt")  # 产生回收站
        r = _load(toolkit.fs_delete(".agent-trash"))
        assert not r["success"]
        # 回收站不进入默认搜索
        found = _load(toolkit.fs_search("*", include_hidden=False))
        assert all(".agent-trash" not in m["path"] for m in found["matches"])


class TestAudit:
    def test_audit_log_written(self, toolkit):
        toolkit.fs_write("a.txt", "hello")
        toolkit.fs_edit("a.txt", "hello", "world")
        log_dir = toolkit.policy.audit_root
        files = list(log_dir.glob("fs-audit-*.jsonl"))
        assert files, "审计日志文件应存在"
        lines = [json.loads(line) for line in files[0].read_text().splitlines()]
        assert len(lines) == 2
        assert {entry["tool"] for entry in lines} == {"fs_write", "fs_edit"}
        assert all(entry["success"] is True for entry in lines)
        assert all(entry["path"] == "a.txt" for entry in lines)

    def test_audit_records_failures(self, toolkit):
        toolkit.fs_read("missing.txt")
        files = sorted(toolkit.policy.audit_root.glob("fs-audit-*.jsonl"))
        lines = [json.loads(line) for line in files[-1].read_text().splitlines()]
        assert lines[-1]["success"] is False
        assert lines[-1]["error_code"] == "PATH_NOT_FOUND"
