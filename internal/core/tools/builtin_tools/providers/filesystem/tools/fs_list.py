#!/usr/bin/env python
"""fs_list —— 列出工作区目录内容（结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsListInput
from ..toolkit import get_toolkit


@tool(args_schema=FsListInput)
def fs_list(path: str = ".", show_hidden: bool = False) -> str:
    """列出工作区内指定目录的文件和子目录，返回结构化 JSON：
    每个条目含 name / path / type(directory|file|symlink) / size / size_human /
    modified / created / permissions。路径相对于工作区根目录（FILESYSTEM_WORKSPACE），
    默认不显示隐藏文件（以 . 开头）。"""
    return get_toolkit().fs_list(path=path, show_hidden=show_hidden)
