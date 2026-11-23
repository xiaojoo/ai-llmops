#!/usr/bin/env python
"""文件系统工具包 —— 安全层：策略（工作区 / 权限 / 大小限制）。

FileSystemPolicy 是全部安全判断的唯一事实来源：

- workspace：工作区根目录（虚拟根），所有工具路径都解析在其内部
- allowed_roots：额外允许的根（默认仅 workspace）
- denied_paths：禁止访问的路径（命中即拒绝，优先级最高）
- permissions：按 FileSystemPermission 开关读写删等能力
- max_*：大小 / 条数限制，防止撑爆 LLM 上下文或磁盘配额

默认权限（遵循设计约定）：
    READ / LIST / SEARCH / WRITE / EDIT / MOVE / COPY  ✅（写类操作经风险层把关）
    DELETE：默认允许（删除统一进回收站 .agent-trash/，可恢复）；
            生产环境可通过环境变量 FILESYSTEM_ALLOW_DELETE=0 关闭
    EXECUTE：文件系统工具包不提供任何执行能力（Shell 应单独成工具包）
"""
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FileSystemPermission(str, Enum):
    """文件系统权限枚举"""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class FileSystemPolicy:
    """文件系统安全策略"""

    workspace: Path  # 工作区根目录（resolve 后的绝对路径）
    allowed_roots: list[Path] = field(default_factory=list)  # 额外允许根
    denied_paths: list[Path] = field(default_factory=list)  # 禁止路径（命中即拒）
    permissions: dict[FileSystemPermission, bool] = field(default_factory=dict)
    max_file_size: int = 2 * 1024 * 1024  # 单文件写入/编辑上限（字节），默认 2MB
    max_read_bytes: int = 2 * 1024 * 1024  # 单次读取文件大小上限（字节），默认 2MB
    max_read_chars: int = 50_000  # 单次读取返回字符上限，防止撑爆上下文
    max_list_entries: int = 500  # fs_list 单目录最大返回条数
    max_search_results: int = 200  # fs_search 最大返回条数
    trash_dir_name: str = ".agent-trash"  # 回收站目录名（工作区内）
    audit_dir_name: str = ".agent-audit"  # 审计日志目录名（工作区内）

    def __post_init__(self):
        self.workspace = Path(self.workspace).resolve()
        self.allowed_roots = [Path(p).resolve() for p in self.allowed_roots]
        self.denied_paths = [Path(p).resolve() for p in self.denied_paths]
        # 默认权限：读/列/搜/写/编辑/移动/复制开放；删除按环境变量；不提供执行
        self.permissions.setdefault(FileSystemPermission.READ, True)
        self.permissions.setdefault(FileSystemPermission.WRITE, True)
        self.permissions.setdefault(FileSystemPermission.DELETE, _env_bool("FILESYSTEM_ALLOW_DELETE", True))
        self.permissions.setdefault(FileSystemPermission.EXECUTE, False)

    def allow(self, perm: FileSystemPermission) -> bool:
        return bool(self.permissions.get(perm, False))

    @property
    def trash_root(self) -> Path:
        return self.workspace / self.trash_dir_name

    @property
    def audit_root(self) -> Path:
        return self.workspace / self.audit_dir_name

    def is_internal_dir(self, abs_path: Path) -> bool:
        """是否为工具包内部目录（回收站 / 审计日志），对 Agent 不可见、不可删"""
        abs_path = Path(abs_path).resolve()
        return abs_path.is_relative_to(self.trash_root) or abs_path.is_relative_to(self.audit_root)


def default_workspace() -> Path:
    """计算工作区根目录：FILESYSTEM_WORKSPACE 优先，否则项目内兜底目录"""
    env_workspace = os.environ.get("FILESYSTEM_WORKSPACE")
    if env_workspace:
        return Path(env_workspace).resolve()
    # 本地开发兜底：<项目根>/storage/agent-workspace
    project_root = Path(__file__).resolve().parents[7]
    return (project_root / "storage" / "agent-workspace").resolve()


def default_policy() -> FileSystemPolicy:
    """从环境变量构造默认策略（进程级单例由 toolkit.get_toolkit 持有）"""
    workspace = default_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    return FileSystemPolicy(workspace=workspace)
