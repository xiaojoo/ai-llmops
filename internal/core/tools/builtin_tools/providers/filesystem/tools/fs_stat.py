#!/usr/bin/env python
"""fs_stat —— 获取工作区内文件/目录信息（结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsStatInput
from ..toolkit import get_toolkit


@tool(args_schema=FsStatInput)
def fs_stat(path: str) -> str:
    """查看工作区内文件/目录的详细信息（结构化 JSON）：
    type / size / size_human / modified / created / permissions，
    符号链接额外返回 target。路径相对于工作区根目录（FILESYSTEM_WORKSPACE）。"""
    return get_toolkit().fs_stat(path=path)
