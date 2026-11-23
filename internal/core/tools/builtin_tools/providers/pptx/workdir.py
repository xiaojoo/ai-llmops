#!/usr/bin/env python
"""PPT 工具工作目录：在可写位置创建默认权限的临时目录。

背景：DSH 沙箱环境下，系统临时目录与 tempfile 创建的 0o700 目录内无法创建文件
（PermissionError），而项目 storage/ 目录可写（后端日志即写于此）。
故 PPT 生成改用项目内工作目录，并可用环境变量 PPTX_WORK_ROOT 覆盖根路径。
"""
import os
import shutil
import uuid
from pathlib import Path


def create_pptx_work_dir() -> Path:
    """创建并返回一个可写的工作目录（调用方负责 finally 清理）。"""
    # 惰性导入，保持工具包模块加载轻量
    from internal.config.settings import get_settings

    base = os.getenv("PPTX_WORK_ROOT") or ""
    if base:
        root = Path(base).expanduser()
    else:
        root = Path(get_settings().project_root) / "storage" / "tmp" / "pptx"
    root.mkdir(parents=True, exist_ok=True)
    work_dir = root / uuid.uuid4().hex
    os.mkdir(work_dir)  # 默认权限：沙箱拒绝在 0o700 目录内写文件
    return work_dir


def cleanup_pptx_work_dir(work_dir: Path) -> None:
    """删除工作目录（尽力而为，失败静默）。"""
    if work_dir is not None:
        shutil.rmtree(work_dir, ignore_errors=True)
