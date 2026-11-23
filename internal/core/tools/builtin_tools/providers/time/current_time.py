#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/25 20:23
@Author : sunxiaojie
@File   : current_time.py
"""
from datetime import datetime

from langchain_core.tools import tool
from pydantic import BaseModel


class CurrentTimeArgs(BaseModel):
    pass


@tool(args_schema=CurrentTimeArgs)
def current_time() -> str:
    """返回获取当前时间的StructuredTool工具"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")
