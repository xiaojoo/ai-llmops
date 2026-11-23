#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/2 20:13
@Author : sunxiaojie
@File   : document_service.py
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from numpy import random
from redis import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.cache_entity import LOCK_DOCUMENT_UPDATE_ENABLE, LOCK_EXPIRE_TIME
from internal.entity.dataset_entity import DocumentStatus, ProcessType, SegmentStatus
from internal.entity.upload_file_entity import ALLOWED_DOCUMENT_EXTENSION
from internal.exception import FailedException, ForbiddenException, NotFoundException
from internal.lib.helper import datetime_to_timestamp
from internal.model import Account, Dataset, Document, ProcessRule, Segment, UploadFile
from internal.schema.document_schema import GetDocumentsWithPageReq
from internal.task.document_task import (
    build_documents,
    delete_document,
    update_document_enabled,
)
from package.paginator import Paginator

from .base_service import BaseService

logger = logging.getLogger(__name__)



@dataclass
class DocumentService(BaseService):
    """文档服务"""
    db: AsyncSession
    redis_client: Redis

    async def get_upload_file(self, document: Document, db: AsyncSession) -> UploadFile | None:
        """获取文档对应的上传文件记录"""
        return await db.get(UploadFile, document.upload_file_id)

    async def get_process_rule(self, document: Document, db: AsyncSession) -> ProcessRule | None:
        """获取文档对应的处理规则记录"""
        return await db.get(ProcessRule, document.process_rule_id)

    async def get_segment_count(self, document: Document, db: AsyncSession) -> int:
        """获取文档下的片段总数"""
        stmt = select(func.count(Segment.id)).where(Segment.document_id == document.id)
        return (await db.scalar(stmt)) or 0

    async def get_document_hit_count(self, document: Document, db: AsyncSession) -> int:
        """获取文档下全部片段的命中总数"""
        stmt = select(func.coalesce(func.sum(Segment.hit_count), 0)).where(Segment.document_id == document.id)
        return (await db.scalar(stmt)) or 0

    async def preview_chunks(
            self,
            dataset_id: UUID,
            upload_file_ids: list[UUID],
            process_type: str,
            rule: dict,
            account: Account,
            limit: int = 5,
    ) -> list[dict]:
        """切片预览：按指定分段方式/规则对第一个上传文件做真实切分，返回前 limit 块

        不落库、不建索引，仅用于分段设置页对比调整参数。
        """
        # 1、校验知识库权限
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise ForbiddenException("当前用户无该知识库权限或知识库不存在")

        # 2、取第一个合法上传文件
        stmt = select(UploadFile).where(
            UploadFile.account_id == account.id,
            UploadFile.id.in_(upload_file_ids)
        )
        upload_file = (await self.db.execute(stmt)).scalars().first()
        if upload_file is None:
            raise FailedException("未找到可预览的文件，请重新上传")

        # 3、构建临时 ProcessRule（复用创建文档的规则构造，不落库）
        process_rule = ProcessRule(
            account_id=account.id,
            dataset_id=dataset_id,
            mode=process_type,
            rule=rule,
        )

        # 4、加载文件内容（返回文本）
        from internal.entity.upload_file_entity import ALLOWED_DOCUMENT_EXTENSION
        if upload_file.extension.lower() not in ALLOWED_DOCUMENT_EXTENSION:
            raise FailedException("该文件类型不支持分段预览")

        # 4.1、按识别设置构建 OCR 提供者（图片/扫描PDF 预览需要）
        from starlette.concurrency import run_in_threadpool

        from internal.core.file_extractor.file_extractor import FileExtractor

        from .process_rule_service import ProcessRuleService

        file_extractor = FileExtractor()
        process_rule_service = ProcessRuleService()
        ocr_provider = self._build_ocr_provider_for_rule(process_rule)
        # 预览只处理前几页（前 limit 块一般来自前几页），避免整个扫描件全量 OCR 拖慢预览
        lc_documents = await run_in_threadpool(
            file_extractor.load, upload_file, False, False, ocr_provider=ocr_provider, max_pages=limit + 3
        )
        # 清洗文本（与正式构建一致）
        for lc_doc in lc_documents:
            lc_doc.page_content = process_rule_service.clean_text_by_process_rule(
                lc_doc.page_content,
                process_rule,
            )

        # 5、按规则切分
        text_splitter = process_rule_service.get_text_splitter_by_process_rule(process_rule)
        lc_segments = text_splitter.split_documents(lc_documents)

        # 6、返回前 limit 块（带标题路径）
        return [
            {
                "index": i + 1,
                "content": seg.page_content,
                "character_count": len(seg.page_content),
                "headings": seg.metadata.get("headings", []),
            }
            for i, seg in enumerate(lc_segments[:limit])
        ]

    @staticmethod
    def _build_ocr_provider_for_rule(process_rule) -> object | None:
        """按处理规则的识别设置构建 OCR 提供者（图片/扫描PDF 识别时）"""
        recognition = (process_rule.rule or {}).get("recognition", {}) if process_rule else {}
        if not recognition:
            return None
        if not recognition.get("image", False) and not recognition.get("pdf_ocr", False):
            return None
        import os as _os

        from internal.core.ocr.ocr_provider import create_ocr_provider

        ocr_provider = recognition.get("ocr_provider", "")
        if ocr_provider:
            _os.environ["OCR_PROVIDER"] = ocr_provider
        # custom 模式：把用户自定义 API 配置传给提供者
        custom = recognition.get("custom") or {}
        try:
            return create_ocr_provider(
                provider_name=ocr_provider,
                api_key=custom.get("api_key", ""),
                api_base=custom.get("api_base", ""),
                model=custom.get("model", ""),
            )
        except Exception as e:
            logger.warning("OCR 提供者创建失败（预览跳过 OCR）: %s", e)
            return None

    async def create_document(
            self,
            dataset_id: UUID,
            upload_file_ids: list[UUID],
            process_type: str = ProcessType.AUTOMATIC,
            rule: dict | None = None,
            account: Account = None,
    ) -> tuple[list[Document], str]:
        """根据传递的信息创建文档列表并调用异步任务"""
        # 1、检测知识库权限
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise ForbiddenException("当前用户无该知识库权限或知识库不存在")

        # 2、提取文件并校验权限与文件扩展
        stmt = select(UploadFile).where(
            UploadFile.account_id == account.id,
            UploadFile.id.in_(upload_file_ids)
        )
        upload_files = (await self.db.execute(stmt)).scalars().all()
        upload_files = [
            upload_file for upload_file in upload_files if
            upload_file.extension.lower() in ALLOWED_DOCUMENT_EXTENSION
        ]
        if len(upload_files) == 0:
            logger.warning(
                f"上传文件列表未解析到合法文件，account_id：{account.id}, dataset_id:{dataset_id}, upload_file_ids:{upload_file_ids}"
            )
            raise FailedException("暂未解析到合法文件，请重新上传")

        # 3、创建批次与处理规则并记录到数据库中
        batch = time.strftime("%Y%m%d%H%M%S") + str(random.randint(100000, 999999))
        process_rule = await self.create(
            ProcessRule,
            account_id=account.id,
            dataset_id=dataset_id,
            mode=process_type,
            rule=rule,
        )
        # 4、获取当前知识库的最新文档位置
        position = await self.get_latest_document_position(dataset_id)
        # 5、循环遍历所有合法的上传文件列表并记录
        documents_list = []
        for upload_file in upload_files:
            position += 1
            document_instance = await self.create(
                Document,
                account_id=account.id,
                dataset_id=dataset_id,
                upload_file_id=upload_file.id,
                process_rule_id=process_rule.id,
                batch=batch,
                name=upload_file.name,
                position=position,
            )
            documents_list.append(document_instance)

        # 6、调用异步任务，完成后续操作
        build_documents.delay([document.id for document in documents_list])

        # 7、返回文档列表与处理批次
        return documents_list, batch

    async def get_document(self, dataset_id: UUID, document_id: UUID, account: Account) -> Document:
        """根据传递的知识库id+文档id获取文档记录信息"""
        # 1、检测知识库权限
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")
        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限获取该文档，请联系管理员添加权限")

        return document

    async def update_document(self, dataset_id: UUID, document_id: UUID, account: Account, **kwargs) -> Document:
        """根据传递的知识库id+文档id，更新文档信息"""
        # 1、检测知识库权限
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")
        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限修改文档，请联系管理员添加权限")

        return await self.update(document, **kwargs)

    async def update_document_enabled(self, dataset_id: UUID, document_id: UUID, account: Account, enabled: bool) -> Document:
        """根据传递的知识库id+文档id，更新文档的启用状态，同时会异步更新weaviate向量数据库中的数据"""
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")

        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限修改该知识库下的文档，请联系管理员")

        if document.status != DocumentStatus.COMPLETED:
            raise ForbiddenException("当前文档处于不可修改状态，请稍后重试")

        if document.enabled == enabled:
            raise FailedException(f"文档状态修改错误，当前已是{'启用' if enabled else '禁用'}状态")

        # 获取更新文档启用状态的缓存键并检测是否上锁
        cache_key = LOCK_DOCUMENT_UPDATE_ENABLE.format(document_id=document_id)
        cache_result = self.redis_client.get(cache_key)
        if cache_result is not None:
            raise FailedException("当前文档正在被修改启用状态，请稍后再尝试")

        # 修改文档的启用状态并设置缓存键，缓存时间600s
        await self.update(
            document,
            enabled=enabled,
            disabled_at=None if enabled else datetime.now(),
        )

        self.redis_client.set(cache_key, 1, ex=LOCK_EXPIRE_TIME)

        # 启用异步任务
        update_document_enabled.delay(document.id)

        return document

    async def delete_document(self, dataset_id: UUID, document_id: UUID, account: Account) -> Document:
        """根据传递的知识库id+文档id删除文档信息，涵盖：文档片段删除、关键词表更新、weaviate向量数据库记录删除"""
        # 1、获取文档并校验权限
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")
        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限删除该知识库下的文档，请核实后重试")

        # 2、判断文档是否处于可删除状态：
        #    构建完成/出错/已暂停 可删除；等待/处理中需等待（避免删除后 worker 还在处理）
        if document.status not in [
            DocumentStatus.COMPLETED,
            DocumentStatus.ERROR,
            DocumentStatus.STOPPED,
        ]:
            raise FailedException("当前文件处于不可删除状态，需要等待构建完成")

        # 3、删除postgres中的文档基础信息
        await self.delete(document)

        # 4、调用异步任务
        delete_document.delay(dataset_id, document.id)

        return document

    async def retry_document(self, dataset_id: UUID, document_id: UUID, account: Account) -> Document:
        """重试构建文档索引：清理旧的片段/向量/关键词，重置状态并重新派发异步任务

        适用场景：Celery 未启动时上传导致索引失败（文档为 error 状态），
        修复环境后可一键重新上传构建。
        """
        # 1、获取文档并校验权限
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")
        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限操作该知识库下的文档，请核实后重试")

        # 2、只有出错状态的文档允许重试（处理中/完成的不需要重试）
        if document.status not in [DocumentStatus.ERROR, DocumentStatus.WAITING]:
            raise FailedException("当前文档状态不允许重试，仅错误/等待状态的文档可重新构建")

        # 3、先清理旧的索引数据（片段、关键词、weaviate 向量），避免幂等跳过导致不重建
        from internal.container import create_indexing_service

        indexing_service = create_indexing_service(self.db, self.redis_client)
        await indexing_service.delete_document(dataset_id, document_id)

        # 4、重置文档状态为等待并清除错误信息，重新派发异步构建任务
        #    同时禁用文档（构建中不可被检索/使用），完成后 _completed 会重新启用
        await self.update(
            document,
            status=DocumentStatus.WAITING,
            error="",
            enabled=False,
            disabled_at=datetime.now(),
            processing_started_at=None,
            processing_completed_at=None,
            splitting_completed_at=None,
            indexing_completed_at=None,
            completed_at=None,
            stopped_at=None,
        )
        build_documents.delay([document_id])

        return document

    async def pause_document(self, dataset_id: UUID, document_id: UUID, account: Account) -> Document:
        """暂停文档构建：将等待中的文档标记为 stopped（worker 派发前会跳过），可稍后继续"""
        # 1、获取文档并校验权限
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")
        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限操作该知识库下的文档，请核实后重试")

        # 2、等待/错误/处理中（解析/分段/索引）状态均可暂停：
        #    处理中的文档会在当前阶段完成后停止（软暂停），已完成的片段保留，继续时断点续传
        if document.status not in [
            DocumentStatus.WAITING,
            DocumentStatus.ERROR,
            DocumentStatus.PARSING,
            DocumentStatus.SPLITTING,
            DocumentStatus.INDEXING,
        ]:
            raise FailedException("当前文档状态不允许暂停，仅等待/失败/处理中的文档可暂停")

        # 3、标记为停止状态（同时禁用，处理中的文档不可被使用）
        await self.update(
            document,
            status=DocumentStatus.STOPPED,
            stopped_at=datetime.now(),
            enabled=False,
            disabled_at=datetime.now(),
        )

        return document

    async def resume_document(self, dataset_id: UUID, document_id: UUID, account: Account) -> Document:
        """继续构建：将暂停（stopped）的文档重新置为等待并派发异步构建任务"""
        # 1、获取文档并校验权限
        document = await self.get(Document, document_id)
        if document is None:
            raise NotFoundException("该文档不存在，请核实后重试")
        if document.dataset_id != dataset_id or document.account_id != account.id:
            raise ForbiddenException("当前用户无权限操作该知识库下的文档，请核实后重试")

        # 2、仅停止状态可继续
        if document.status != DocumentStatus.STOPPED:
            raise FailedException("当前文档状态不允许继续，仅暂停状态的文档可继续")

        # 3、重置为等待状态并清除停止时间，重新派发构建任务（保持禁用，完成后自动启用）
        await self.update(
            document,
            status=DocumentStatus.WAITING,
            error="",
            stopped_at=None,
        )
        build_documents.delay([document_id])

        return document

    async def get_documents_with_page(
            self,
            dataset_id: UUID,
            req: GetDocumentsWithPageReq,
            account: Account
    ) -> tuple[list[Document], Paginator]:
        # 根据传递的知识库id+请求数据获取文档分页列表数据
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise NotFoundException("该知识库不存在或无权限")

        paginator = Paginator(db=self.db, req=req)

        filters = [
            Document.account_id == account.id,
            Document.dataset_id == dataset_id,
        ]
        if req.search_word:
            filters.append(Document.name.ilike(f"%{req.search_word}%"))

        select_stmt = select(Document).where(*filters).order_by(desc(Document.created_at))

        documents = await paginator.paginate(select_stmt)

        # 批量填充每个文档的已完成片段数（segment_count 由 Document.segment_count 属性提供）
        if documents:
            doc_ids = [document.id for document in documents]
            done_stmt = select(Segment.document_id, func.count(Segment.id)).where(
                Segment.document_id.in_(doc_ids),
                Segment.status == SegmentStatus.COMPLETED,
            ).group_by(Segment.document_id)
            done_counts = dict((await self.db.execute(done_stmt)).fetchall())

            for document in documents:
                document.completed_segment_count = done_counts.get(document.id, 0)

        return documents, paginator

    async def get_latest_document_position(self, dataset_id: UUID) -> int:
        """根据传递的知识库id获取最新文档位置"""
        stmt = select(Document).where(
            Document.dataset_id == dataset_id
        ).order_by(desc(Document.position)).limit(1)
        document = (await self.db.execute(stmt)).scalars().first()
        return document.position if document else 0

    async def get_documents_status(self, dataset_id: UUID, batch: str, account: Account) -> list[dict]:
        """根据传递的知识库id+处理批次获取文档列表的状态"""
        # 1、检测知识库权限
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise ForbiddenException("当前用户无该知识库权限或知识库不存在")
        # 2、查询当前知识库下该批次的文档列表
        stmt = select(Document).where(
            Document.dataset_id == dataset_id,
            Document.batch == batch
        ).order_by(Document.position)
        documents = (await self.db.execute(stmt)).scalars().all()
        if documents is None or len(documents) == 0:
            raise NotFoundException("该处理批次未发现文档，请核实后重试")

        # 3、循环遍历文档列表提取文档的状态信息
        documents_status = []
        for document in documents:
            # 4、查询每个文档的总片段数和已构建完成的片段数
            stmt = select(func.count(Segment.id)).where(
                Segment.document_id == document.id
            )
            segment_count = await self.db.scalar(stmt)
            stmt = select(func.count(Segment.id)).where(
                Segment.document_id == document.id,
                Segment.status == SegmentStatus.COMPLETED
            )
            completed_segment_count = await self.db.scalar(stmt)

            upload_file = await self.db.get(UploadFile, document.upload_file_id)
            documents_status.append({
                "id": document.id,
                "name": document.name,
                "size": upload_file.size if upload_file else 0,
                "extension": upload_file.extension if upload_file else "",
                "mime_type": upload_file.mime_type if upload_file else "",
                "position": document.position,
                "segment_count": segment_count,
                "completed_segment_count": completed_segment_count,
                "error": document.error,
                "status": document.status,
                "processing_started_at": datetime_to_timestamp(document.processing_started_at),
                "processing_completed_at": datetime_to_timestamp(document.processing_completed_at),
                "splitting_completed_at": datetime_to_timestamp(document.splitting_completed_at),
                "indexing_completed_at": datetime_to_timestamp(document.indexing_completed_at),
                "completed_at": datetime_to_timestamp(document.completed_at),
                "stopped_at": datetime_to_timestamp(document.stopped_at),
                "created_at": datetime_to_timestamp(document.created_at),
            })

        return documents_status
