#!/usr/bin/env python
"""
@Time    : 2026/8/27
@File    : attachment_service.py

聊天附件解析服务：根据附件文件ID加载 UploadFile 记录，校验账号归属，
提取文本内容供 LLM 阅读。辅助Agent、应用调试、WebApp 三个聊天入口共用。
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from internal.core.file_extractor.file_extractor import FileExtractor
from internal.exception import FailedException
from internal.model import Account, UploadFile
from internal.service.cos_service import CosService

from .base_service import BaseService

logger = logging.getLogger(__name__)


@dataclass
class AttachmentService(BaseService):
    """附件解析服务"""
    db: AsyncSession
    file_extractor: FileExtractor
    cos_service: CosService

    # 单个附件注入LLM的最大字符数（超出截断）
    MAX_ATTACHMENT_CHARS = 4000

    async def load_attachments(self, file_ids: list[str], account: Account) -> tuple[list[dict], str]:
        """根据附件文件ID加载UploadFile记录，提取文本内容供LLM阅读

        返回：(附件元信息列表, 拼装后的附件文本)；元信息用于落库与历史展示。
        """
        if not file_ids:
            return [], ""

        # 1、过滤非法ID，按账号校验归属
        valid_ids: list[str] = []
        for file_id in file_ids:
            try:
                UUID(file_id)
                valid_ids.append(file_id)
            except (ValueError, TypeError, AttributeError):
                continue

        stmt = (
            select(UploadFile)
            .where(UploadFile.id.in_(valid_ids), UploadFile.account_id == account.id)
        )
        upload_files = (await self.db.execute(stmt)).scalars().all()

        # 2、附件必须全部存在且属于当前账号
        if len({str(f.id) for f in upload_files}) != len(set(file_ids)):
            raise FailedException("存在无效的附件文件，请重新上传后重试")

        # 3、构建元信息 + 提取文本（文件解析经 run_in_threadpool 桥接）
        file_infos: list[dict] = []
        text_parts: list[str] = []
        for idx, upload_file in enumerate(upload_files, start=1):
            file_infos.append({
                "id": str(upload_file.id),
                "name": upload_file.name,
                "size": upload_file.size,
                "extension": upload_file.extension,
                "url": CosService.get_fresh_file_url(upload_file.key),
            })
            try:
                content = await run_in_threadpool(
                    self.file_extractor.load, upload_file, True
                ) or ""
            except Exception as e:
                logger.warning("附件解析失败 %s: %s", upload_file.name, e)
                content = ""
            if content:
                text_parts.append(
                    f"[附件{idx}: {upload_file.name}]\n{content[:self.MAX_ATTACHMENT_CHARS]}"
                )

        return file_infos, "\n\n".join(text_parts)
