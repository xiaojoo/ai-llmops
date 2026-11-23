#!/usr/bin/env python
"""fs_edit —— 精确修改工作区内文件文本片段（结构化 JSON 返回）。

old_text 必须精确匹配现有内容；未找到时报 TARGET_NOT_FOUND。
多处命中时仅替换第一处，并在结果中提示 occurrences 与 changed_line。
"""
from langchain_core.tools import tool

from ..models.requests import FsEditInput
from ..toolkit import get_toolkit


@tool(args_schema=FsEditInput)
def fs_edit(path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> str:
    """精确替换工作区内文件的一段文本（结构化 JSON 返回）：
    返回 path / replaced_count / occurrences / changed_line / size / size_human。
    old_text 必须与文件现有内容精确匹配（找不到报错），推荐先 fs_read 确认再编辑；
    多处命中仅替换第一处。路径相对于工作区根目录。"""
    return get_toolkit().fs_edit(path=path, old_text=old_text, new_text=new_text, encoding=encoding)
