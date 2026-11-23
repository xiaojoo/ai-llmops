#!/usr/bin/env python
"""fs_move —— 移动/重命名工作区内文件/目录（结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsMoveInput
from ..toolkit import get_toolkit


@tool(args_schema=FsMoveInput)
def fs_move(src: str, dst: str) -> str:
    """移动或重命名工作区内的文件/目录（等价 mv，结构化 JSON 返回）：
    目标父目录不存在时自动创建；目标已存在时报错。路径相对于工作区根目录。"""
    return get_toolkit().fs_move(src=src, dst=dst)
