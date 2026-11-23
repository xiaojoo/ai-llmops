#!/usr/bin/env python
"""fs_search —— 在工作区内搜索文件（glob 通配符，结构化 JSON 返回）。"""
from langchain_core.tools import tool

from ..models.requests import FsSearchInput
from ..toolkit import get_toolkit


@tool(args_schema=FsSearchInput)
def fs_search(
    pattern: str,
    root: str = ".",
    include_hidden: bool = False,
    limit: int = 100,
) -> str:
    """在工作区内按 glob 模式搜索文件（结构化 JSON 返回）：
    返回 matches（path / type）、total_found、truncated。pattern 不含 / 时按文件名
    匹配任意深度（如 *.py、test_*.md），含 / 时按相对路径匹配（如 src/*.py）。
    默认跳过隐藏目录与回收站/审计目录；结果受 limit 与策略上限限制。
    路径相对于工作区根目录。"""
    return get_toolkit().fs_search(pattern=pattern, root=root, include_hidden=include_hidden, limit=limit)
