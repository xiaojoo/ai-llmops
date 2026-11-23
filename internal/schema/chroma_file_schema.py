#!/usr/bin/env python
"""
@Time    : 2026/3/22 18:25
@Author  : sunxiaojie
@File    : chroma_file_schema.py
"""

from pydantic import BaseModel


class FileItemSchema(BaseModel):
    """单个文件信息"""
    name: str
    size: int
    modified: str
    path: str


class FileListResp(BaseModel):
    """文件列表响应"""
    files: list[FileItemSchema]
