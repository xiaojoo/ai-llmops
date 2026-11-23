#!/usr/bin/env python
"""文件系统工具包 —— 输入模型（Agent 调用参数）。

所有路径参数均为“工作区相对路径”：相对工作区根目录（FILESYSTEM_WORKSPACE），
支持以 "/" 开头表示工作区根目录（虚拟根）。禁止绝对路径 / 盘符 / UNC 路径。
"""
from pydantic import BaseModel, Field


class FsListInput(BaseModel):
    """fs_list —— 列出目录内容"""

    path: str = Field(
        default=".",
        description="要列出的目录路径，相对于工作区根目录，默认为根目录",
    )
    show_hidden: bool = Field(
        default=False,
        description="是否显示隐藏文件（以 . 开头），默认 false",
    )


class FsStatInput(BaseModel):
    """fs_stat —— 获取文件/目录信息"""

    path: str = Field(
        description="要查看的文件或目录路径，相对于工作区根目录",
    )


class FsReadInput(BaseModel):
    """fs_read —— 读取文件内容（支持行范围）"""

    path: str = Field(
        description="要读取的文件路径，相对于工作区根目录",
    )
    start_line: int | None = Field(
        default=None,
        description="起始行号（从 1 开始），不填则从头读取",
    )
    end_line: int | None = Field(
        default=None,
        description="结束行号（包含），不填则读到末尾",
    )
    encoding: str = Field(
        default="utf-8",
        description="文件编码，默认 utf-8，可选 gbk、latin-1 等",
    )


class FsWriteInput(BaseModel):
    """fs_write —— 创建/覆盖文件（不承担局部修改与追加职责）"""

    path: str = Field(
        description="要写入的文件路径，相对于工作区根目录，父目录不存在时自动创建",
    )
    content: str = Field(
        description="要写入的完整文本内容（覆盖式写入；局部修改请使用 fs_edit）",
    )
    encoding: str = Field(
        default="utf-8",
        description="文件编码，默认 utf-8",
    )


class FsEditInput(BaseModel):
    """fs_edit —— 精确替换文件中的文本片段"""

    path: str = Field(
        description="要修改的文件路径，相对于工作区根目录",
    )
    old_text: str = Field(
        description="要被替换的原文片段（必须精确匹配；找不到时报错）",
    )
    new_text: str = Field(
        description="替换后的新文本片段",
    )
    encoding: str = Field(
        default="utf-8",
        description="文件编码，默认 utf-8",
    )


class FsMkdirInput(BaseModel):
    """fs_mkdir —— 创建目录（mkdir -p 语义）"""

    path: str = Field(
        description="要创建的目录路径，相对于工作区根目录，支持多级路径（如 a/b/c）",
    )


class FsCopyInput(BaseModel):
    """fs_copy —— 复制文件或目录"""

    src: str = Field(
        description="源文件或目录路径，相对于工作区根目录",
    )
    dst: str = Field(
        description="目标路径，相对于工作区根目录，父目录不存在时自动创建",
    )
    overwrite: bool = Field(
        default=False,
        description="目标已存在时是否覆盖，默认 false（已存在则报错）",
    )


class FsMoveInput(BaseModel):
    """fs_move —— 移动/重命名文件或目录"""

    src: str = Field(
        description="源文件或目录路径，相对于工作区根目录",
    )
    dst: str = Field(
        description="目标路径，相对于工作区根目录，父目录不存在时自动创建",
    )


class FsDeleteInput(BaseModel):
    """fs_delete —— 删除文件/目录（进入回收站，可恢复）"""

    path: str = Field(
        description="要删除的文件或目录路径，相对于工作区根目录",
    )
    recursive: bool = Field(
        default=False,
        description="是否递归删除非空目录，默认 false；非空目录必须设 true",
    )


class FsSearchInput(BaseModel):
    """fs_search —— 在工作区内搜索文件"""

    pattern: str = Field(
        description=(
            "文件名匹配模式（glob 通配符），如 *.py、test_*.md；"
            "含 / 时按相对路径匹配，如 src/*.py"
        ),
    )
    root: str = Field(
        default=".",
        description="搜索起始目录，相对于工作区根目录，默认为根目录",
    )
    include_hidden: bool = Field(
        default=False,
        description="是否搜索隐藏目录/文件，默认 false",
    )
    limit: int = Field(
        default=100,
        description="最多返回的匹配数量，默认 100",
    )
