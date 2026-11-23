#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 16:03
@Author : sunxiaojie
@File   : upload_file_service.py
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.exception import ValidateException
from internal.model import Document, UploadFile

from .base_service import BaseService

# 已上传待分段文件的时间窗口（小时）：文件夹日期在当前窗口内（含今天）的孤儿文件才显示
PENDING_FILE_WINDOW_HOURS = 2
# 知识库文档固定目录：只扫描该前缀下的孤儿文件（排除 image/audio 等其他类型）
DATASET_DOCS_PREFIX = "/document/dataset_documents/"
# URL key 中的日期文件夹格式：document/dataset_documents/YYYY-MM-DD/xxx
FOLDER_DATE_PATTERN = re.compile(r"/document/dataset_documents/(\d{4}-\d{2}-\d{2})/")


def _extract_folder_date(key: str) -> datetime | None:
    """从存储 key（COS 路径或 MiniIO URL）中提取日期文件夹，如 2026-08-22"""
    path = urlparse(key).path if "://" in key else key
    match = FOLDER_DATE_PATTERN.search(path)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d")
    except ValueError:
        return None


@dataclass
class UploadFileService(BaseService):
    """上传文件记录服务"""
    db: AsyncSession


    async def create_upload_file(self, **kwargs) -> UploadFile:
        """创建文件上传记录"""
        return await self.create(UploadFile, **kwargs)

    async def get_pending_upload_files(self, account_id) -> list[UploadFile]:
        """查询当前账号下已上传但尚未创建文档（孤儿）的文件记录。

        展示规则（只针对知识库文档目录 document/dataset_documents/）：
        - 上传固定落在 document/dataset_documents/ 目录，再按日期分文件夹
        - 文件夹日期 = 当前日期，或在最近 PENDING_FILE_WINDOW_HOURS 小时窗口内 → 显示
        - 其他类型目录（image/audio/video 等）和历史窗口外文件不显示
        """
        now = datetime.now()
        window_start = now - timedelta(hours=PENDING_FILE_WINDOW_HOURS)

        # 查询该账号全部孤儿文件，且 key 位于知识库文档目录
        stmt = (
            select(UploadFile)
            .outerjoin(Document, Document.upload_file_id == UploadFile.id)
            .where(
                UploadFile.account_id == account_id,
                UploadFile.key.like(f"%{DATASET_DOCS_PREFIX}%"),
                Document.id.is_(None),
            )
            .order_by(UploadFile.created_at.desc())
        )
        all_orphans = (await self.db.execute(stmt)).scalars().all()

        # 按文件夹日期过滤：日期在今天，或在 2 小时窗口内（跨天场景）
        def _in_window(upload_file: UploadFile) -> bool:
            folder_date = _extract_folder_date(upload_file.key)
            if folder_date is None:
                # key 无日期文件夹时回退到 DB 时间戳判断
                return upload_file.created_at >= window_start
            # 同一天（今天）恒显示；跨天时文件夹日期落在窗口内也显示
            same_day = folder_date.date() == now.date()
            in_window = window_start.date() <= folder_date.date() <= now.date()
            return same_day or in_window

        return [f for f in all_orphans if _in_window(f)]

    async def get_owned_upload_file(self, upload_file_id, account_id) -> UploadFile:
        """按 ID 获取归属当前账号的上传文件记录（不存在或无权时抛错）"""
        upload_file = await self.get(UploadFile, upload_file_id)
        if upload_file is None or upload_file.account_id != account_id:
            raise ValidateException("上传文件不存在或无权访问")
        return upload_file

    async def delete_upload_file(self, upload_file_id, account_id) -> UploadFile:
        """删除上传文件记录（调用方负责删除 OSS 对象）"""
        upload_file = await self.get_owned_upload_file(upload_file_id, account_id)
        await self.delete(upload_file)
        return upload_file
