#!/usr/bin/env python
"""fs_delete —— 删除工作区内文件/目录（高危操作：统一进回收站，结构化 JSON 返回）。

删除不直接 os.remove：目标被移入 <workspace>/.agent-trash/，可恢复。
禁止删除工作区根目录与回收站/审计目录；非空目录必须显式 recursive=true。
"""
from langchain_core.tools import tool

from ..models.requests import FsDeleteInput
from ..toolkit import get_toolkit


@tool(args_schema=FsDeleteInput)
def fs_delete(path: str, recursive: bool = False) -> str:
    """删除工作区内的文件或目录（结构化 JSON 返回）：
    返回 path / trashed / trash_path / recoverable。删除会移入回收站
    .agent-trash/（可恢复），不会永久丢失；非空目录须设 recursive=true 才可删除；
    禁止删除工作区根目录。路径相对于工作区根目录。"""
    return get_toolkit().fs_delete(path=path, recursive=recursive)
