#!/usr/bin/env python
"""
@Time    : 2025/12/8 19:09
@Author  : sunxiaojie
@File    : segment_service.py
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from redis import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from anyio import to_thread
from starlette.concurrency import run_in_threadpool

from internal.entity.cache_entity import LOCK_EXPIRE_TIME, LOCK_SEGMENT_UPDATE_ENABLED
from internal.entity.dataset_entity import DocumentStatus, SegmentStatus
from internal.exception import FailedException, NotFoundException, ValidateException
from internal.lib.helper import generate_text_hash
from internal.model import Account, Document, Segment
from internal.schema.segment_schema import (
    CreateSegmentReq,
    GetSegmentsWithPageReq,
)
from package.paginator import Paginator

from .base_service import BaseService
from .embeddings_service import EmbeddingsService
from .keyword_table_service import KeywordTableService
from .ltp_service import LtpService
from .vector_database_service import VectorDatabaseService

logger = logging.getLogger(__name__)



@dataclass
class SegmentService(BaseService):
    """片段服务"""
    db: AsyncSession
    redis_client: Redis
    keyword_table_service: KeywordTableService
    vector_database_service: VectorDatabaseService
    embeddings_service: EmbeddingsService
    ltp_service: LtpService

    async def get_document(self, segment: Segment, db: AsyncSession) -> Document | None:
        """查询片段所属文档"""
        return await db.get(Document, segment.document_id)

    async def create_segment(self, dataset_id: UUID, document_id: UUID, req: CreateSegmentReq, account: Account) -> Segment:
        """根据传递的信息新增文档片段信息"""
        # 1、校验上传内容的token长度总数，不能超过1000
        token_count = self.embeddings_service.calculate_token_count(req.content)
        if token_count > 1000:
            raise ValidateException("片段内容的长度不能超过1000 token")
        # 2、获取文档信息并校验
        document = await self.get(Document, document_id)
        if (
                document is None
                or document.account_id != account.id
                or document.dataset_id != dataset_id
        ):
            raise NotFoundException("该知识库文档片段不存在，或无权限新增，请核实后重试")
        # 3、判断文档的状态是否可以新增片段数据，只有completed才可以新增
        if document.status != DocumentStatus.COMPLETED:
            raise FailedException("当前文档不可新增片段，请稍后重试")
        # 4、提取文档片段的最大位置
        stmt = select(func.coalesce(func.max(Segment.position), 0)).where(
            Segment.document_id == document_id
        )
        position = await self.db.scalar(stmt)
        # 5、校验是否传递了keywords，如果没有传递的话，调用ltp服务生产关键字
        # asyncio.to_thread 线程池桥接
        if req.keywords is None or len(req.keywords) == 0:
            import asyncio
            req.keywords = await asyncio.to_thread(
                self.ltp_service.extract_keywords, req.content, 10
            )
        # 6、向postgres数据库中新增记录
        segment = None
        try:
            # 7、位置+1并且新增segment记录
            position += 1
            segment = await self.create(
                Segment,
                account_id=account.id,
                dataset_id=dataset_id,
                document_id=document_id,
                node_id=uuid.uuid4(),
                position=position,
                content=req.content,
                character_count=len(req.content),
                token_count=token_count,
                keywords=req.keywords,
                hash=generate_text_hash(req.content),
                enabled=True,
                processing_started_at=datetime.now(),
                indexing_completed_at=datetime.now(),
                completed_at=datetime.now(),
                status=SegmentStatus.COMPLETED,
            )
            # 8、向向量数据库中新增数据（weaviate 同步客户端桥接）
            await run_in_threadpool(
                self.vector_database_service.vector_store.add_documents,
                [LCDocument(
                    page_content=req.content,
                    metadata={
                        "account_id": str(document.account_id),
                        "dataset_id": str(document.dataset_id),
                        "document_id": str(document.id),
                        "segment_id": str(segment.id),
                        "node_id": str(segment.node_id),
                        "document_enabled": document.enabled,
                        "segment_enabled": True,
                    }
                )],
                ids=[str(segment.node_id)]
            )
            # 9、重新计算片段的字符总数一级token总数
            stmt = select(
                func.coalesce(func.sum(Segment.character_count), 0),
                func.coalesce(func.sum(Segment.token_count), 0)
            ).where(Segment.dataset_id == dataset_id)
            document_character_count, document_token_count = (await self.db.execute(stmt)).first()
            # 10、更新文档的对应信息
            await self.update(
                document,
                character_count=document_character_count,
                token_count=document_token_count,
            )
            # 11、更新关键词表信息
            if document.enabled is True:
                await self.keyword_table_service.add_keyword_table_from_ids(dataset_id, [segment.id])

        except Exception as e:
            logger.exception("新增文档片段内容发生异常")
            if segment:
                await self.update(
                    segment,
                    error=str(e),
                    status=SegmentStatus.ERROR,
                    enabled=False,
                    disabled_at=datetime.now(),
                    stopped_at=datetime.now(),
                )
            raise FailedException("新增文档片段失败，请稍后重试")

        return segment

    async def get_segments_with_page(
            self,
            dataset_id: UUID, document_id: UUID,
            req: GetSegmentsWithPageReq,
            account: Account,
    ) -> tuple[list[Segment], Paginator]:
        """根据传递的信息获取片段列表分页数据"""
        # 1、获取文档并校验权限
        document = await self.get(Document, document_id)
        if document is None or document.dataset_id != dataset_id or document.account_id != account.id:
            raise NotFoundException("该知识库文档片段不存在，或无权限查看，请核实后重试")

        # 2、构建分页查询器
        paginator = Paginator(db=self.db, req=req)

        filters = [
            Segment.document_id == document_id,
        ]
        if req.search_word:
            filters.append(Segment.content.ilike(f"%{req.search_word}%"))

        select_stmt = select(Segment).where(*filters).order_by(desc("position"))
        segments = await paginator.paginate(select_stmt)

        return segments, paginator

    async def get_segment(self, dataset_id: UUID, document_id: UUID, segment_id: UUID, account: Account) -> Segment:
        """根据传递的信息获取片段详情信息"""
        # 获取片段信息并校验权限
        segment = await self.get(Segment, segment_id)
        if (
                segment is None
                or segment.account_id != account.id
                or segment.dataset_id != dataset_id
                or segment.document_id != document_id
        ):
            raise NotFoundException("该知识库文档不存在，或无权限查看，请核实后重试")

        return segment

    async def update_segment_enabled(self, dataset_id: UUID, document_id: UUID, segment_id: UUID, enabled: bool,
                               account: Account) -> None:
        """根据传递的信息更新文档片段的启用状态信息"""
        # 1、获取片段信息并校验权限
        segment = await self.get(Segment, segment_id)
        if (
                segment is None
                or segment.account_id != account.id
                or segment.dataset_id != dataset_id
                or segment.document_id != document_id
        ):
            raise NotFoundException("该知识库文档不存在，或无权限查看，请核实后重试")

        # 2、判断文档片段是否处于可启用/禁用的环境
        if segment.status != SegmentStatus.COMPLETED:
            raise FailedException("当前片段不可修改状态，请稍后重试")

        # 3、判断更新的片段启用状态和数据库的数据是否一致，如果是则抛出错误
        if enabled == segment.enabled:
            raise FailedException(f"片段状态修改错误，当前已是{'启用' if enabled else '禁用'}")

        # 4、获取更新片段启用状态锁并上锁检测
        cache_key = LOCK_SEGMENT_UPDATE_ENABLED.format(segment_id=segment_id)
        cache_result = self.redis_client.get(cache_key)
        if cache_result is not None:
            raise FailedException("当前文档片段正在修改状态，请稍后重试")

        # 5、上锁并更新对应的数据，涵盖postgres记录、weaviate、关键词表
        with self.redis_client.lock(cache_key, LOCK_EXPIRE_TIME):
            try:
                # 6、修改postgres数据库里的文档片段状态
                await self.update(
                    segment,
                    enabled=enabled,
                    disabled_at=None if enabled else datetime.now()
                )
                # 7、更新关键词表对应的信息，有可能新增，也有可能删除
                document = await self.db.get(Document, segment.document_id)
                if enabled and document.enabled is True:
                    await self.keyword_table_service.add_keyword_table_from_ids(dataset_id, [segment_id])
                else:
                    await self.keyword_table_service.delete_keyword_table_from_ids(dataset_id, [segment_id])
                # 8、同步处理weaviate向量数据库里的数据（weaviate 同步客户端桥接）
                await run_in_threadpool(
                    self.vector_database_service.collection.data.update,
                    uuid=segment.node_id,
                    properties={"segment_enabled": enabled},
                )
            except Exception as e:
                logger.exception(f"更改文档片段启用状态出现异常，segment_id：{segment_id}")
                await self.update(
                    segment,
                    error=str(e),
                    status=SegmentStatus.ERROR,
                    enabled=False,
                    disabled_at=datetime.now(),
                    stopped_at=datetime.now(),
                )
                raise FailedException("更新文档片段启用状态失败，请稍后重试")

    async def delete_segment(self, dataset_id: UUID, document_id: UUID, segment_id: UUID, account: Account) -> Segment:
        """删除文档片段信息"""
        # 1、获取片段信息并校验权限
        segment = await self.get(Segment, segment_id)
        if (
                segment is None
                or segment.account_id != account.id
                or segment.dataset_id != dataset_id
                or segment.document_id != document_id
        ):
            raise NotFoundException("该知识库文档不存在，或无权限查看，请核实后重试")

        # 2、判断文档是否处于可以删除状态，只有COMPLETED/ERROR才可以删除
        if segment.status not in [SegmentStatus.COMPLETED, SegmentStatus.ERROR]:
            raise FailedException("当前文档片段处于不可删除状态，请稍后重试")
        # 3、删除文档片段并获取该片段的文档信息
        document = await self.db.get(Document, segment.document_id)
        await self.delete(segment)

        # 4、同步删除关键词表中属于该片段的关键词
        await self.keyword_table_service.delete_keyword_table_from_ids(dataset_id, [segment_id])

        # 5、同步删除向量数据库存储的记录（weaviate 同步客户端桥接）
        try:
            await run_in_threadpool(
                self.vector_database_service.collection.data.delete_by_id,
                str(segment.node_id)
            )
        except Exception:
            logger.exception(f"删除文档片段记录失败，segment_id：{segment_id}")

        # 6、重新计算片段的字符总数一级token总数
        stmt = select(
            func.coalesce(func.sum(Segment.character_count), 0),
            func.coalesce(func.sum(Segment.token_count), 0)
        ).where(Segment.dataset_id == dataset_id)
        document_character_count, document_token_count = (await self.db.execute(stmt)).first()
        await self.update(
            document,
            character_count=document_character_count,
            token_count=document_token_count,
        )

        return segment

    async def update_segment(self, dataset_id: UUID, document_id: UUID, segment_id: UUID, req: CreateSegmentReq,
                       account: Account) -> Segment:
        """根据传递的信息更新指定的文档片段信息"""
        # 获取片段信息并校验权限
        segment = await self.get(Segment, segment_id)
        if (
                segment is None
                or segment.account_id != account.id
                or segment.dataset_id != dataset_id
                or segment.document_id != document_id
        ):
            raise NotFoundException("该知识库文档不存在，或无权限查看，请核实后重试")

        # 2、判断文档是否处于可以删除状态，只有COMPLETED/ERROR才可以删除
        if segment.status not in [SegmentStatus.COMPLETED, SegmentStatus.ERROR]:
            raise FailedException("当前文档片段处于不可删除状态，请稍后重试")

        # 3、检测是否传递了keywords，如果没有传递，调用ltp服务生产关键词
        # asyncio.to_thread 线程池桥接
        if req.keywords is None or len(req.keywords) == 0:
            import asyncio
            req.keywords = await asyncio.to_thread(
                self.ltp_service.extract_keywords, req.content, 10
            )

        # 4、计算新内容的hash值
        new_hash = generate_text_hash(req.content)
        required_update = segment.hash != new_hash

        try:
            # 5、更新segment记录
            await self.update(
                segment,
                keywords=req.keywords,
                content=req.content,
                hash=new_hash,
                character_count=len(req.content),
                token_count=self.embeddings_service.calculate_token_count(req.content),
            )
            # 6、更新片段归属关键词信息
            await self.keyword_table_service.delete_keyword_table_from_ids(dataset_id, [segment_id])
            await self.keyword_table_service.add_keyword_table_from_ids(dataset_id, [segment_id])

            # 7、检测是否需要更新文档信息以及向量数据库
            if required_update:
                # 8、更新文档信息
                document = await self.db.get(Document, segment.document_id)
                stmt = select(
                    func.coalesce(func.sum(Segment.character_count), 0),
                    func.coalesce(func.sum(Segment.token_count), 0)
                ).where(
                    Segment.document_id == document_id
                )
                document_character_count, document_token_count = (await self.db.execute(stmt)).first()
                await self.update(
                    document,
                    character_count=document_character_count,
                    token_count=document_token_count,
                )
            # 9、更新向量数据库（asyncio.to_thread 线程池桥接）
            import asyncio
            query_vector = await asyncio.to_thread(
                self.embeddings_service.embeddings.embed_query, req.content
            )
            await run_in_threadpool(
                self.vector_database_service.collection.data.update,
                uuid=str(segment.node_id),
                properties={
                    "text": req.content,
                },
                vector=query_vector
            )
        except Exception:
            logger.exception(f"更新文档片段记录失败，segment_id：{segment}")
            raise FailedException("更新文档片段记录失败，请稍后重试")

        return segment
