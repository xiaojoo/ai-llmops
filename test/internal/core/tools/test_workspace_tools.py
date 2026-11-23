#!/usr/bin/env python
"""Agent 模式工作区工具（workspace_tools）测试：
- build_workspace_tools：按请求 workspace 构建 11 个工具（10 filesystem + 1 shell）
- 动态 workspace 生效：读写限定在传入目录，越界/绝对路径被 PathGuard 拒绝
- shell 白名单：白名单外拒绝；列表参数直传（无 shell 注入）；超时；输出截断
- 空/非法/不存在目录 → 返回空列表

纯本地测试（无需 DB）：用 repo/tmp/workspace-tools-tests 下独立目录作为工作区。
注意：测试目录用 os.makedirs 创建（DSH 沙箱下 tempfile.mkdtemp/pytest tmp_path 不可写）。
"""
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from internal.core.tools.workspace_tools import (
    SHELL_ALLOWLIST,
    SHELL_MAX_OUTPUT_BYTES,
    LOCAL_TOOL_NAMES,
    ShellToolkit,
    _local_tool_stub,
    _resolve_command,
    bound_filesystem_tool_names,
    build_local_tool_stubs,
    build_workspace_tools,
    is_local_runtime_tool,
    should_strip_server_tool,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture()
def ws_base():
    base = _REPO_ROOT / "tmp" / "workspace-tools-tests"
    base.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def ws_dir(ws_base):
    d = ws_base / f"ws-{uuid4().hex[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture()
def outside_dir(ws_base):
    d = ws_base / f"out-{uuid4().hex[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tool_map(project_root: str) -> dict[str, object]:
    return {t.name: t for t in build_workspace_tools(project_root)}


class TestBuildWorkspaceTools:
    def test_returns_11_tools_with_dynamic_workspace(self, ws_dir):
        tools = _tool_map(str(ws_dir))
        names = set(tools)
        assert names == {
            "fs_list", "fs_stat", "fs_read", "fs_write", "fs_edit",
            "fs_mkdir", "fs_copy", "fs_move", "fs_delete", "fs_search",
            "shell_run",
        }

    def test_empty_and_invalid_roots_return_empty(self, ws_base):
        assert build_workspace_tools("") == []
        assert build_workspace_tools("   ") == []
        assert build_workspace_tools(str(ws_base / "not-exists-dir")) == []


class TestLocalToolRuntime:
    """本地工具运行时（Remote Agent + Local Tool Runtime）相关纯逻辑。"""

    def test_local_names_cover_all_fs_tools(self):
        # Phase 2：全部文件类工具（读+写/改/建/复制/移动/删除）进入本地运行时；
        # 终端(shell_run)仍由服务器执行，不在集合内
        assert LOCAL_TOOL_NAMES == frozenset({
            "fs_list", "fs_stat", "fs_read", "fs_write", "fs_edit",
            "fs_mkdir", "fs_copy", "fs_move", "fs_delete", "fs_search",
        })
        assert "shell_run" not in LOCAL_TOOL_NAMES

    def test_is_local_runtime_tool(self):
        assert is_local_runtime_tool("fs_read") is True
        assert is_local_runtime_tool("fs_write") is True
        assert is_local_runtime_tool("fs_delete") is True
        assert is_local_runtime_tool("shell_run") is False

    def test_bound_filesystem_tool_names(self):
        # 应用按工具粒度绑定：读 + 写工具都绑 → 返回全部 10 个
        def _tool(name):
            return {"type": "builtin_tool", "provider": {"id": "filesystem"}, "tool": {"name": name}}

        app_config = {
            "tools": [
                _tool("fs_list"), _tool("fs_stat"), _tool("fs_read"), _tool("fs_search"),
                _tool("fs_write"), _tool("fs_edit"), _tool("fs_mkdir"),
                _tool("fs_copy"), _tool("fs_move"), _tool("fs_delete"),
            ]
        }
        assert bound_filesystem_tool_names(app_config) == set(LOCAL_TOOL_NAMES)

        # 只绑读工具 → 只有读，不含写（写入权限随绑定，不写死）
        read_only_cfg = {
            "tools": [_tool("fs_list"), _tool("fs_read")],
        }
        names = bound_filesystem_tool_names(read_only_cfg)
        assert names == {"fs_list", "fs_read"}
        assert "fs_write" not in names
        assert "fs_delete" not in names

        # 未绑定 filesystem 工具 → 空
        assert bound_filesystem_tool_names({"tools": [
            {"type": "builtin_tool", "provider": {"id": "time"}, "tool": {"name": "time"}}
        ]}) == set()
        assert bound_filesystem_tool_names({"tools": []}) == set()

    def test_stub_schemas_match_real_tools(self, ws_dir):
        # 桩工具 schema 与真实工具一致（LLM 参数生成不受换执行方影响）
        stubs = {t.name: t for t in build_local_tool_stubs()}
        real = _tool_map(str(ws_dir))
        for name in LOCAL_TOOL_NAMES:
            assert name in stubs, f"缺少桩工具 {name}"
            assert name in real, f"缺少真实工具 {name}"
            stubs[name].args_schema.model_json_schema() == real[name].args_schema.model_json_schema()

    def test_stub_not_executed_server_side(self):
        # 桩的 func 被服务器直接调用应抛错（提示本地工具分发拦截失效），绝不返回可读结果
        import pytest
        with pytest.raises(RuntimeError):
            _local_tool_stub(path="x")

    def test_stubs_filtered_by_binding(self):
        # 只绑定读工具 → 不注入写工具（写权限随绑定授权，不写死）
        read_only = {t.name for t in build_local_tool_stubs(frozenset({"fs_list", "fs_stat", "fs_read", "fs_search"}))}
        assert read_only == {"fs_list", "fs_stat", "fs_read", "fs_search"}
        assert "fs_write" not in read_only
        assert "fs_delete" not in read_only

        # 绑定全部文件工具 → 读写都可注入
        all_fs = {t.name for t in build_local_tool_stubs(frozenset({
            "fs_list", "fs_stat", "fs_read", "fs_write", "fs_edit",
            "fs_mkdir", "fs_copy", "fs_move", "fs_delete", "fs_search",
        }))}
        assert "fs_write" in all_fs
        assert "fs_delete" in all_fs

        # 默认（None）= 全部文件工具
        assert len(build_local_tool_stubs()) == len(LOCAL_TOOL_NAMES)

    def test_should_strip_server_tool(self):
        assert should_strip_server_tool("fs_list") is True
        assert should_strip_server_tool("fs_read") is True
        assert should_strip_server_tool("fs_delete") is True
        assert should_strip_server_tool("shell_run") is True
        assert should_strip_server_tool("dataset_retrieval") is False
        assert should_strip_server_tool("web_search") is False


class TestDynamicWorkspace:
    def test_write_and_read_inside_workspace(self, ws_dir):
        tools = _tool_map(str(ws_dir))
        r = json.loads(tools["fs_write"].invoke({"path": "src/main.py", "content": "print(1)\n"}))
        assert r["success"] is True
        assert (ws_dir / "src" / "main.py").exists()

        r2 = json.loads(tools["fs_read"].invoke({"path": "src/main.py"}))
        assert r2["success"] is True and "print(1)" in r2["content"]

    def test_traversal_blocked(self, ws_dir, outside_dir):
        (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")
        tools = _tool_map(str(ws_dir))
        r = json.loads(tools["fs_read"].invoke({"path": "../secret.txt"}))
        assert r["success"] is False
        assert r["error"]["code"] == "PATH_TRAVERSAL"

    def test_absolute_path_blocked(self, ws_dir, outside_dir):
        (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")
        tools = _tool_map(str(ws_dir))
        r = json.loads(tools["fs_read"].invoke({"path": str(outside_dir / "secret.txt")}))
        assert r["success"] is False

    def test_delete_goes_to_trash(self, ws_dir):
        (ws_dir / "a.txt").write_text("x", encoding="utf-8")
        tools = _tool_map(str(ws_dir))
        r = json.loads(tools["fs_delete"].invoke({"path": "a.txt"}))
        assert r["success"] is True
        # 原文件移入工作区回收站，可恢复
        assert not (ws_dir / "a.txt").exists()
        assert (ws_dir / ".agent-trash").exists()


class TestShellToolkit:
    def test_allowlist_membership(self):
        for cmd in ("python", "pytest", "node", "npm", "git", "go"):
            assert cmd in SHELL_ALLOWLIST

    def test_block_non_allowlist(self, ws_dir):
        s = ShellToolkit(workspace=ws_dir)
        r = json.loads(s.run("rm", ["-rf", "/"]))
        assert r["status"] == "failed"
        assert "白名单" in r["output"]

    def test_run_python_success(self, ws_dir):
        s = ShellToolkit(workspace=ws_dir)
        r = json.loads(s.run("python", ["-c", "print(1+1)"]))
        assert r["status"] == "success"
        assert r["exit_code"] == 0
        assert r["output"].strip() == "2"

    def test_failed_command_exit_code(self, ws_dir):
        s = ShellToolkit(workspace=ws_dir)
        r = json.loads(s.run("python", ["-c", "raise SystemExit(3)"]))
        assert r["status"] == "failed"
        assert r["exit_code"] == 3

    def test_timeout(self, ws_dir):
        s = ShellToolkit(workspace=ws_dir)
        r = json.loads(s.run("python", ["-c", "import time; time.sleep(5)"], timeout=1))
        assert r["status"] == "failed"
        assert "超时" in r["output"]

    def test_args_not_shell_interpretted(self, ws_dir):
        """列表参数直传：分号/管道等作为普通参数，不经 shell 解释（无注入面）。"""
        s = ShellToolkit(workspace=ws_dir)
        # python -c "import os; print(os.getcwd())" —— 分号在参数内是 Python 语法，不是 shell 拼接
        r = json.loads(s.run("python", ["-c", "import os; print(os.getcwd())"]))
        assert r["status"] == "success"
        assert str(ws_dir.resolve()) in r["output"]

    def test_output_truncated(self, ws_dir):
        s = ShellToolkit(workspace=ws_dir)
        code = f"print('x' * {SHELL_MAX_OUTPUT_BYTES * 2})"
        r = json.loads(s.run("python", ["-c", code]))
        assert r["status"] == "success"
        assert "输出已截断" in r["output"]
        assert len(r["output"]) <= SHELL_MAX_OUTPUT_BYTES + 100


class TestShellVenvPath:
    """venv 目录下的解释器路径白名单（如 venv/Scripts/python.exe）。

    白名单判断用 _resolve_command 纯逻辑验证；真实执行用项目根下的真实 venv
    （H:\ai-code-llmops\venv）端到端验证。
    """

    def test_resolve_venv_python_path(self, ws_dir):
        """venv/Scripts/python.exe 可解析为工作区内绝对路径。"""
        venv_scripts = ws_dir / "venv" / "Scripts"
        venv_scripts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sys.executable, venv_scripts / "python.exe")
        resolved = _resolve_command("venv/Scripts/python.exe", ws_dir)
        assert resolved is not None
        assert Path(resolved) == (ws_dir / "venv" / "Scripts" / "python.exe").resolve()

    def test_resolve_venv_pip_path(self, ws_dir):
        """venv/Scripts/pip.exe 可解析（文件名判断）。"""
        venv_scripts = ws_dir / "venv" / "Scripts"
        venv_scripts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sys.executable, venv_scripts / "pip.exe")
        resolved = _resolve_command("venv/Scripts/pip.exe", ws_dir)
        assert resolved is not None

    def test_resolve_venv_blocked_for_non_allowlist_name(self, ws_dir):
        """venv 目录下非白名单可执行文件仍被拒绝（如 venv/Scripts/rm.exe）。"""
        venv_scripts = ws_dir / "venv" / "Scripts"
        venv_scripts.mkdir(parents=True, exist_ok=True)
        (venv_scripts / "rm.exe").write_text("x", encoding="utf-8")
        assert _resolve_command("venv/Scripts/rm.exe", ws_dir) is None

    def test_resolve_path_outside_workspace_blocked(self, ws_dir, outside_dir):
        """工作区外的路径（哪怕文件名合法）一律拒绝。"""
        (outside_dir / "python.exe").write_text("x", encoding="utf-8")
        assert _resolve_command(str(outside_dir / "python.exe"), ws_dir) is None

    def test_resolve_venv_dir_must_be_named_venv(self, ws_dir):
        """非 venv 目录（如 scripts/）下的合法文件名也拒绝。"""
        scripts = ws_dir / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "python.exe").write_text("x", encoding="utf-8")
        assert _resolve_command("scripts/python.exe", ws_dir) is None

    def test_resolve_bare_command_unchanged(self, ws_dir):
        """裸命令名仍按原白名单返回（不在白名单返回 None）。"""
        assert _resolve_command("python", ws_dir) == "python"
        assert _resolve_command("pip", ws_dir) == "pip"
        assert _resolve_command("rm", ws_dir) is None

    def test_real_venv_python_runs_end_to_end(self):
        """项目真实 venv 的 python.exe 可通过 shell_run 执行（端到端）。"""
        ws = _REPO_ROOT  # 项目根，内含真实 venv/
        s = ShellToolkit(workspace=ws)
        r = json.loads(s.run("venv/Scripts/python.exe", ["-c", "import sys; print(sys.executable)"]))
        assert r["status"] == "success", r
        assert "venv" in r["output"]
