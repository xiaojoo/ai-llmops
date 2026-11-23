#!/usr/bin/env python
"""fs_copy —— 复制工作区内文件/目录（结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsCopyInput
from ..toolkit import get_toolkit


@tool(args_schema=FsCopyInput)
def fs_copy(src: str, dst: str, overwrite: bool = False) -> str:
    """复制工作区内的文件或目录（结构化 JSON 返回）：
    文件返回 bytes_copied，目录返回 item_count。目标父目录不存在时自动创建；
    目标已存在默认报错（可设 overwrite=true 覆盖）。路径相对于工作区根目录。"""
    return get_toolkit().fs_copy(src=src, dst=dst, overwrite=overwrite)
