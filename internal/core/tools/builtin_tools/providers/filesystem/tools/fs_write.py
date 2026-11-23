#!/usr/bin/env python
"""fs_write —— 创建/覆盖工作区内文件（结构化 JSON 返回）。

职责边界：只做“创建新文件 / 整体覆盖”，不做局部修改与追加；
局部修改请用 fs_edit，避免 Agent 误操作。
"""
from langchain_core.tools import tool

from ..models.requests import FsWriteInput
from ..toolkit import get_toolkit


@tool(args_schema=FsWriteInput)
def fs_write(path: str, content: str, encoding: str = "utf-8") -> str:
    """在工作区内创建文件或整体覆盖已有文件（结构化 JSON 返回）：
    返回 path / bytes_written / chars_written / created / size / size_human。
    父目录不存在时自动创建；单文件大小受策略上限保护。路径相对于工作区根目录。
    注意：本工具是覆盖式写入，局部修改请使用 fs_edit。"""
    return get_toolkit().fs_write(path=path, content=content, encoding=encoding)
