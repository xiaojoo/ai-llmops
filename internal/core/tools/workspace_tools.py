#!/usr/bin/env python
"""Agent 模式(智能体)工作区工具构造器。

VS Code 插件在对话模式为 agent 时传入当前工作区路径(project_root),
后端按请求构建一套绑定该工作区的工具注入 Agent:

- filesystem:复用受控文件系统工具包(PathGuard 沙箱 + 回收站 + 审计),
  但 workspace 动态指向请求传入的 project_root(而非进程级 FILESYSTEM_WORKSPACE);
- shell:新增受控命令执行工具(命令白名单 + cwd 限定 + 超时 + 输出截断)。

安全边界:
- 所有文件操作严格限制在 project_root 内(PathGuard 拒绝穿越/符号链接逃逸);
- shell 只能执行白名单命令,工作目录固定为 project_root,列表参数调用
  (无 shell=True,天然防注入),带超时与输出截断,stdout/stderr 合并返回。
"""
import logging
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from internal.core.tools.builtin_tools.providers.filesystem.models.requests import (
    FsCopyInput,
    FsDeleteInput,
    FsEditInput,
    FsListInput,
    FsMkdirInput,
    FsMoveInput,
    FsReadInput,
    FsSearchInput,
    FsStatInput,
    FsWriteInput,
)
from internal.core.tools.builtin_tools.providers.filesystem.security.policy import FileSystemPolicy
from internal.core.tools.builtin_tools.providers.filesystem.toolkit import FileSystemToolkit

logger = logging.getLogger(__name__)

# ===== shell 命令白名单(常用开发命令) =====
SHELL_ALLOWLIST: frozenset[str] = frozenset({
    "python", "python3", "py", "pytest", "pip", "pip3",
    "node", "npm", "npx", "tsc",
    "java", "javac", "mvn", "gradle",
    "go", "cargo", "rustc",
    "git",
})

# venv 目录名(大小写不敏感):位于工作区内、名为这些目录下的白名单可执行文件才允许带路径调用
_VENV_DIR_NAMES = ("venv", ".venv", "env")

# ===== 本地工具运行时（Remote Agent + Local Tool Runtime） ====
# 这些工具在 local_tool_runtime=True 时，服务器不执行，改由插件在本地对真实工作区执行。
# Phase 2：全部文件类工具都由插件本地执行（读 + 写/改/建/复制/移动/删除）。
#   插件端路径守卫 + 回收站与服务器 FileService 语义一致（见 vscode-plugin/src/api/localTools.ts）。
#   服务器端只注册"工具桩"（同名同 schema，让 LLM 正确生成参数），并在运行时拦截走
#   LOCAL_TOOL_CALL 事件 + 等待插件回传结果。任何非白名单工具不会进入本集合。
#   注意：shell_run（终端）仍由服务器执行（未本地化），因此不在此集合内。
LOCAL_TOOL_NAMES: frozenset[str] = frozenset({
    "fs_list", "fs_stat", "fs_read",
    "fs_write", "fs_edit", "fs_mkdir",
    "fs_copy", "fs_move", "fs_delete",
    "fs_search",
})

# 已被本地运行时接管的工具：注入前从应用配置/服务器工具集里剔除，避免服务器误执行。
_LOCAL_FS_TOOL_PREFIXES = ("fs_",)
_LOCAL_SHELL_TOOL_NAMES = ("shell_run",)


# 文件系统工具包内、按「读写」划分的两类工具名（用于按绑定授权区分权限，不写死）。
FS_READ_TOOL_NAMES: frozenset[str] = frozenset({"fs_list", "fs_stat", "fs_read", "fs_search"})
FS_WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "fs_write", "fs_edit", "fs_mkdir", "fs_copy", "fs_move", "fs_delete",
})


def bound_filesystem_tool_names(app_config: dict) -> set[str]:
    """返回应用在 /space/apps/{id} 『扩展插件』中实际**绑定**的 filesystem 工具名集合。

    应用按「工具」粒度绑定（app_config.tools 中每条 builtin_tool 的 provider.id=filesystem、
    tool.name 为 fs_*）。这些名字决定 Agent 能使用哪些文件操作——绑定了写工具才能写，
    没绑定就不能用（写入权限随绑定授权，不写死）。
    """
    names: set[str] = set()
    for tool in app_config.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "builtin_tool":
            continue
        provider = tool.get("provider") or {}
        if provider.get("id") != "filesystem":
            continue
        t = tool.get("tool") or {}
        name = t.get("name") if isinstance(t.get("name"), str) else t.get("id")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def build_local_tool_stubs(names: frozenset[str] | set[str] | None = None) -> list[BaseTool]:
    """构建本地工具桩（Phase 2：全部文件类工具：读 + 写/改/建/复制/移动/删除）。

    桩工具复用真实 Fs*Input schema（LLM 参数生成一致），但 func 不会被服务器执行——
    FunctionCallAgent._tools_node 对 LOCAL_TOOL_NAMES 内的工具走本地运行时分支。

    `names`：要注入的本地文件工具名集合（可选）。None=全部文件工具；
    传入应用实际绑定的工具名集合时，只生成这些桩（读/写权限随绑定授权，不写死）。
    """
    full_specs: list[tuple[str, type[BaseModel], str]] = [
        ("fs_list", FsListInput, "列出工作区目录内容"),
        ("fs_stat", FsStatInput, "获取文件/目录信息"),
        ("fs_read", FsReadInput, "读取工作区内文件内容（支持行范围）"),
        ("fs_write", FsWriteInput, "创建/覆盖工作区内文件"),
        ("fs_edit", FsEditInput, "精确替换文件中的文本片段"),
        ("fs_mkdir", FsMkdirInput, "创建目录（mkdir -p）"),
        ("fs_copy", FsCopyInput, "复制文件或目录"),
        ("fs_move", FsMoveInput, "移动/重命名文件或目录"),
        ("fs_delete", FsDeleteInput, "删除文件/目录（进回收站可恢复）"),
        ("fs_search", FsSearchInput, "在工作区内搜索文件"),
    ]
    specs = full_specs if names is None else [s for s in full_specs if s[0] in names]
    stubs: list[BaseTool] = []
    for tool_name, input_schema, desc in specs:
        stubs.append(
            StructuredTool.from_function(
                name=tool_name,
                func=_local_tool_stub,
                args_schema=input_schema,
                description=f"{desc}(路径相对于工作区根目录；由本地工具运行时在插件内执行)",
            )
        )
    return stubs


def is_local_runtime_tool(name: str) -> bool:
    """判断工具名是否由本地工具运行时接管执行。"""
    return name in LOCAL_TOOL_NAMES


def should_strip_server_tool(name: str) -> bool:
    """本地运行时下应剔除的服务器端文件系统/命令工具名（避免服务器误执行）。"""
    if name in _LOCAL_SHELL_TOOL_NAMES:
        return True
    return any(name.startswith(p) for p in _LOCAL_FS_TOOL_PREFIXES)


def _local_tool_stub(**kwargs) -> str:
    """本地工具桩占位函数：正常应被运行时拦截，绝不应被服务器执行。

    若被直接调用（说明拦截分支未命中），记录日志并抛错，而不是安静地返回
    一条会被 LLM 当成"正常结果"读取的提示——该提示会掩盖本地工具分发失效的 bug。
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("[local-tool-runtime] 本地工具桩被服务器直接调用，说明分发拦截未生效 (kwargs=%s)", kwargs)
    raise RuntimeError(
        "本地工具分发未生效：工具桩在服务器被直接执行了。请检查 AgentConfig.local_tool_runtime "
        "是否透传（主 Agent/编排器子 Agent），以及是否走的是本地工具运行时分支。"
    )


def _resolve_command(command: str, workspace: Path) -> str | None:
    """解析并校验命令白名单。

    - 裸命令名(不含路径分隔符):必须在 SHELL_ALLOWLIST 内,原样返回;
    - 带路径的命令(如 venv/Scripts/python.exe):解析为工作区内绝对路径,
      要求路径中某一级目录名为 venv/.venv/env,且可执行名(去 .exe 后缀)
      在 SHELL_ALLOWLIST 内;不合法返回 None。
    """
    cmd = command.strip()
    if not cmd:
        return None
    # 裸命令名
    if "/" not in cmd and "\\" not in cmd:
        return cmd if cmd in SHELL_ALLOWLIST else None
    # 带路径:相对于工作区解析
    try:
        abs_cmd = (workspace / cmd).resolve()
    except OSError:
        return None
    try:
        rel = abs_cmd.relative_to(workspace)
    except ValueError:
        return None
    if not any(p in _VENV_DIR_NAMES for p in rel.parts):
        return None
    name = abs_cmd.name
    if name.lower().endswith(".exe"):
        name = name[:-4]
    if name not in SHELL_ALLOWLIST:
        return None
    return str(abs_cmd)

# 单条命令输出上限(字节),防止撑爆 LLM 上下文
SHELL_MAX_OUTPUT_BYTES = 100 * 1024
# 单条命令超时(秒)
SHELL_DEFAULT_TIMEOUT = 60


class ShellRunInput(BaseModel):
    """shell_run —— 在工作区内执行白名单命令"""

    command: str = Field(
        description="要执行的命令名(必须在白名单内)："
                    "python/python3/py/pytest/pip/pip3/node/npm/npx/tsc/java/javac/"
                    "mvn/gradle/go/cargo/rustc/git；"
                    "也支持工作区 venv 目录下的可执行文件路径，"
                    "如 venv/Scripts/python.exe 或 venv/Scripts/pip.exe",
    )
    args: list[str] = Field(
        default_factory=list,
        description="命令参数列表(如 ['-m', 'pytest', 'test_demo.py'])；"
                    "禁止 shell 元字符(管道/重定向/分号)——参数按列表直传,不会经 shell 解释",
    )
    timeout: int = Field(
        default=SHELL_DEFAULT_TIMEOUT,
        description=f"超时秒数(默认 {SHELL_DEFAULT_TIMEOUT}，上限 300)",
        ge=1,
        le=300,
    )


class ShellToolkit:
    """受控命令执行工具：白名单 + cwd 限定 + 超时 + 输出截断"""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    def run(self, command: str, args: list[str] | None = None, timeout: int = SHELL_DEFAULT_TIMEOUT) -> str:
        args = args or []
        resolved_cmd = _resolve_command(command, self.workspace)
        if resolved_cmd is None:
            return _shell_fail(
                f"命令 '{command}' 不在白名单内。仅允许: "
                f"{', '.join(sorted(SHELL_ALLOWLIST))}，"
                f"或工作区 venv 目录下的可执行文件(如 venv/Scripts/python.exe)"
            )
        if len(args) > 200:
            return _shell_fail("命令参数过多(超过 200 个)")
        # 白名单命令不校验参数内容——列表参数直传,不经 shell 解释,无注入面
        try:
            proc = subprocess.run(
                [resolved_cmd, *args],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _shell_fail(f"命令执行超时(>{timeout}s)")
        except FileNotFoundError:
            return _shell_fail(f"命令 '{command}' 不存在(未安装或不在 PATH)")
        except OSError as e:
            return _shell_fail(f"命令执行失败: {e}")

        output = _merge_output(proc.stdout, proc.stderr)
        if len(output) > SHELL_MAX_OUTPUT_BYTES:
            output = output[:SHELL_MAX_OUTPUT_BYTES] + "\n...[输出已截断]..."
        status = "success" if proc.returncode == 0 else "failed"
        return (
            f'{{"status": "{status}", "exit_code": {proc.returncode}, '
            f'"output": {_json_escape(output)}}}'
        )


def _shell_fail(message: str) -> str:
    return f'{{"status": "failed", "exit_code": -1, "output": {_json_escape(message)}}}'


def _merge_output(stdout: str, stderr: str) -> str:
    parts = []
    if stdout and stdout.strip():
        parts.append(stdout.rstrip())
    if stderr and stderr.strip():
        parts.append(stderr.rstrip())
    return "\n".join(parts)


def _json_escape(text: str) -> str:
    import json
    return json.dumps(text, ensure_ascii=False)


# ===== 工具构造 =====

_FS_SPECS: list[tuple[str, type[BaseModel], Any, str]] = [
    ("fs_list", FsListInput, "fs_list", "列出工作区目录内容"),
    ("fs_stat", FsStatInput, "fs_stat", "获取文件/目录信息"),
    ("fs_read", FsReadInput, "fs_read", "读取工作区内文件内容"),
    ("fs_write", FsWriteInput, "fs_write", "创建/覆盖工作区内文件"),
    ("fs_edit", FsEditInput, "fs_edit", "精确替换文件中的文本片段"),
    ("fs_mkdir", FsMkdirInput, "fs_mkdir", "创建目录(mkdir -p 语义)"),
    ("fs_copy", FsCopyInput, "fs_copy", "复制文件或目录"),
    ("fs_move", FsMoveInput, "fs_move", "移动/重命名文件或目录"),
    ("fs_delete", FsDeleteInput, "fs_delete", "删除文件/目录(进回收站可恢复)"),
    ("fs_search", FsSearchInput, "fs_search", "在工作区内搜索文件"),
]


def build_workspace_tools(project_root: str) -> list[BaseTool]:
    """按请求工作区构建 Agent 模式工具集(空目录/非法路径 → 空列表)。

    返回:10 个 filesystem 工具(动态 workspace) + 1 个 shell_run 工具。
    """
    if not project_root or not project_root.strip():
        return []
    try:
        workspace = Path(project_root).resolve()
    except (OSError, ValueError):
        return []
    if not workspace.is_dir():
        logger.warning("[workspace_tools] 工作区不存在: %s", project_root)
        return []

    toolkit = FileSystemToolkit(policy=FileSystemPolicy(workspace=workspace))

    tools: list[BaseTool] = []
    for tool_name, input_schema, method_name, desc in _FS_SPECS:
        method = getattr(toolkit, method_name)
        tools.append(
            StructuredTool.from_function(
                name=tool_name,
                func=method,
                args_schema=input_schema,
                description=f"{desc}(路径相对于工作区根目录)",
            )
        )

    shell = ShellToolkit(workspace=workspace)
    tools.append(
        StructuredTool.from_function(
            name="shell_run",
            func=shell.run,
            args_schema=ShellRunInput,
            description=(
                "在工作区根目录执行白名单命令并返回输出(JSON: status/exit_code/output)。"
                "参数以列表直传(无 shell 解释),禁止管道/重定向/分号。"
                "可用命令: python/python3/py/pytest/pip/pip3/node/npm/npx/tsc/java/javac/"
                "mvn/gradle/go/cargo/rustc/git；"
                "也可用工作区 venv 目录下的解释器路径，如 venv/Scripts/python.exe、"
                "venv/Scripts/pip.exe（优先用 venv 环境跑项目脚本）"
            ),
        )
    )
    return tools
