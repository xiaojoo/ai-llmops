#!/usr/bin/env python
"""fs_mkdir —— 在工作区内创建目录（mkdir -p 语义，结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsMkdirInput
from ..toolkit import get_toolkit


@tool(args_schema=FsMkdirInput)
def fs_mkdir(path: str) -> str:
    """在工作区内创建目录（支持多级，等价 mkdir -p，结构化 JSON 返回）：
    返回 path / created / existed。已存在时不报错；路径已存在同名文件时报错。
    路径相对于工作区根目录。"""
    return get_toolkit().fs_mkdir(path=path)
