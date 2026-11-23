#!/usr/bin/env python
"""文件系统工具包（受控版）。

替换原 filesystem 提供商：不再提供"任意执行"，而是 10 个受控文件工具：

    fs_list / fs_stat / fs_read / fs_write / fs_edit / fs_mkdir /
    fs_copy / fs_move / fs_delete / fs_search

安全设计：PathGuard（路径沙箱+符号链接防护）→ PermissionChecker（权限开关）
→ RiskControl（高风险拦截）→ Service（业务）→ OS，全部操作写审计日志，
删除统一进回收站（.agent-trash/，可恢复）。

对外暴露的 10 个工具函数由 providers 框架按 positions.yaml 动态导入。
"""
from .toolkit import FileSystemToolkit, get_toolkit
from .tools.fs_copy import fs_copy
from .tools.fs_delete import fs_delete
from .tools.fs_edit import fs_edit
from .tools.fs_list import fs_list
from .tools.fs_mkdir import fs_mkdir
from .tools.fs_move import fs_move
from .tools.fs_read import fs_read
from .tools.fs_search import fs_search
from .tools.fs_stat import fs_stat
from .tools.fs_write import fs_write

__all__ = [
    "FileSystemToolkit",
    "fs_copy",
    "fs_delete",
    "fs_edit",
    "fs_list",
    "fs_mkdir",
    "fs_move",
    "fs_read",
    "fs_search",
    "fs_stat",
    "fs_write",
    "get_toolkit",
]
