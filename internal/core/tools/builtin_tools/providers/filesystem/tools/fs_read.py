#!/usr/bin/env python
"""fs_read —— 读取工作区内文件内容（支持行范围，结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsReadInput
from ..toolkit import get_toolkit


@tool(args_schema=FsReadInput)
def fs_read(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    encoding: str = "utf-8",
) -> str:
    """读取工作区内指定文件的文本内容（结构化 JSON）：
    返回 path / encoding / size / content / start_line / end_line / total_lines /
    truncated。支持 start_line/end_line 行范围读取（从 1 开始），避免大文件整读
    撑爆上下文；超大文件自动截断并有大小上限保护。路径相对于工作区根目录。"""
    return get_toolkit().fs_read(path=path, start_line=start_line, end_line=end_line, encoding=encoding)
