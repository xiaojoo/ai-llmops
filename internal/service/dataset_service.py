#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/1 18:11
@Author : sunxiaojie
@File   : dataset_service.py
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.dataset_entity import DEFAULT_DATASET_DESCRIPTION_FORMATTER
from internal.exception import FailedException, NotFoundException, ValidateException
from internal.lib.helper import datetime_to_timestamp
from internal.model import (
    Account,
    AppDatasetJoin,
    Dataset,
    DatasetQuery,
    Document,
    Segment,
    UploadFile,
)
from internal.schema.dataset_schema import (
    CreateOrUpdateDatasetReq,
    GetDatasetsWithPageReq,
    HitReq,
)
from internal.task.dataset_task import delete_dataset
from package.paginator import Paginator

from .base_service import BaseService
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)



@dataclass
class DatasetService(BaseService):
    """知识库服务"""
    db: AsyncSession
    retriever_service: RetrievalService

    async def get_document_count(self, dataset: Dataset, db: AsyncSession) -> int:
        """获取知识库下的文档总数"""
        stmt = select(func.count(Document.id)).where(Document.dataset_id == dataset.id)
        return (await db.scalar(stmt)) or 0

    async def get_hit_count(self, dataset: Dataset, db: AsyncSession) -> int:
        """获取知识库下全部片段的命中总数"""
        stmt = select(func.coalesce(func.sum(Segment.hit_count), 0)).where(Segment.dataset_id == dataset.id)
        return (await db.scalar(stmt)) or 0

    async def get_character_count(self, dataset: Dataset, db: AsyncSession) -> int:
        """获取知识库下全部片段的字符总数"""
        stmt = select(func.coalesce(func.sum(Segment.character_count), 0)).where(Segment.dataset_id == dataset.id)
        return (await db.scalar(stmt)) or 0

    async def get_related_app_count(self, dataset: Dataset, db: AsyncSession) -> int:
        """获取知识库关联的应用数量"""
        stmt = select(func.count(AppDatasetJoin.id)).where(AppDatasetJoin.dataset_id == dataset.id)
        return (await db.scalar(stmt)) or 0

    async def create_dataset(self, req: CreateOrUpdateDatasetReq, account: Account):
        """根据传递的请求信息创建知识库"""
        # 检测该账号下是否存在同名知识库
        stmt = select(Dataset).where(
            Dataset.account_id == account.id,
            Dataset.name == req.name
        )
        dataset = (await self.db.execute(stmt)).scalars().one_or_none()
        if dataset:
            raise ValidateException(f"该知识库{req.name}已经存在")

        # 检测是否传递了描述信息，如果没有传递需要补充上
        if req.description is None or req.description.strip() == "":
            req.description = DEFAULT_DATASET_DESCRIPTION_FORMATTER.format(name=req.name)

        # 创建知识库记录并返回
        return await self.create(
            Dataset,
            account_id=account.id,
            name=req.name,
            icon=req.icon,
            description=req.description,
        )

    async def get_dataset_queries(self, dataset_id: UUID, account: Account) -> list[DatasetQuery]:
        """根据传递的知识库id获取最近10条查询记录"""
        # 1、获取知识库并校验权限
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise NotFoundException("该知识库不存在")
        # 2、调用知识库查询模型查找最近的10条记录
        stmt = (
            select(DatasetQuery).where(DatasetQuery.dataset_id == dataset_id)
            .order_by(desc(DatasetQuery.created_at))
            .limit(10)
        )
        dataset_queries = (await self.db.execute(stmt)).scalars().all()

        return dataset_queries

    async def get_dataset(self, dataset_id: UUID, account: Account) -> Dataset:
        """根据传递的知识库id获取知识库记录"""
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise NotFoundException("该知识库不存在")

        return dataset

    async def update_dataset(self, dataset_id: UUID, req: CreateOrUpdateDatasetReq, account: Account) -> Dataset:
        """根据传递的知识库id+数据更新知识库"""
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise NotFoundException("该知识库不存在")

        # 检测修改后的知识库名称是否出现重名
        stmt = select(Dataset).where(
            Dataset.account_id == account.id,
            Dataset.name == req.name,
            Dataset.id != dataset_id,
        )
        check_dataset = (await self.db.execute(stmt)).scalars().one_or_none()
        if check_dataset:
            raise ValidateException(f"该知识库名称{req.name}已存在，请修改")

        # 校验描述信息是否为空，如果为空则人为设置
        if req.description is None or req.description.strip() == "":
            req.description = DEFAULT_DATASET_DESCRIPTION_FORMATTER.format(name=req.name)

        await self.update(
            dataset,
            name=req.name,
            icon=req.icon,
            description=req.description,
        )
        return dataset

    async def get_dataset_with_page(self, req: GetDatasetsWithPageReq, account: Account) -> tuple[list[Dataset], Paginator]:
        """根据传递的信息获取知识库列表分页数据"""
        # 构建分页查询器
        paginator = Paginator(db=self.db, req=req)
        # 构建筛选器
        filters = [Dataset.account_id == account.id]
        if req.search_word:
            filters.append(Dataset.name.ilike(f"%{req.search_word}%"))
        stmt = select(Dataset).where(*filters).order_by(Dataset.created_at)
        datasets = await paginator.paginate(stmt)
        return datasets, paginator

    async def hit(self, dataset_id: UUID, req: HitReq, account: Account) -> list[dict]:
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise NotFoundException("该知识库不存在")

        # 2、调用检索服务执行检索（agentic 模式：结果校验 + 多轮重检）
        hit_data = dict(req.model_dump())
        agentic_enable = bool(hit_data.pop("agentic_enable", False))
        max_rounds = int(hit_data.pop("max_rounds", 2) or 2)
        trace = []
        if agentic_enable:
            lc_documents = await self.retriever_service.search_agentic(
                dataset_ids=[dataset_id],
                query=hit_data.get("query", ""),
                retrieval_strategy=hit_data.get("retrieval_strategy", "semantic"),
                k=int(hit_data.get("k", 4)),
                score=float(hit_data.get("score", 0) or 0),
                account_id=account.id,
                max_rounds=max_rounds,
                trace=trace,
            )
        else:
            lc_documents = await self.retriever_service.search_in_datasets(
                dataset_ids=[dataset_id],
                account_id=account.id,
                **hit_data,
            )
        lc_document_dict = {str(lc_document.metadata["segment_id"]): lc_document for lc_document in lc_documents}
        # 3、根据检索到的数据查询对应的片段信息
        filters = [str(lc_document.metadata["segment_id"]) for lc_document in lc_documents]
        stmt = (
            select(Segment).where(
                Segment.id.in_(filters)
            )
        )
        segments = (await self.db.execute(stmt)).scalars().all()
        segment_dict = {str(segment.id): segment for segment in segments}
        # 4、排序片段数据
        sorted_segments = [
            segment_dict[str(lc_document.metadata["segment_id"])]
            for lc_document in lc_documents
            if str(lc_document.metadata["segment_id"]) in segment_dict
        ]
        # 5、组装响应数据（async 模型无 relationship，Document/UploadFile 显式批量查询）
        document_ids = list({segment.document_id for segment in sorted_segments})
        documents = {}
        if document_ids:
            stmt = select(Document).where(Document.id.in_(document_ids))
            documents = {str(doc.id): doc for doc in (await self.db.execute(stmt)).scalars().all()}
        upload_file_ids = list({doc.upload_file_id for doc in documents.values()})
        upload_files = {}
        if upload_file_ids:
            stmt = select(UploadFile).where(UploadFile.id.in_(upload_file_ids))
            upload_files = {str(uf.id): uf for uf in (await self.db.execute(stmt)).scalars().all()}

        hit_result = []
        for segment in sorted_segments:
            document = documents.get(str(segment.document_id))
            if document is None:
                continue

            upload_file = upload_files.get(str(document.upload_file_id))
            hit_result.append({
                "id": segment.id,
                "document": {
                    "id": document.id,
                    "name": document.name,
                    "extension": upload_file.extension if upload_file else "",
                    "mime_type": upload_file.mime_type if upload_file else "",
                },
                "dataset_id": segment.dataset_id,
                "score": lc_document_dict[str(segment.id)].metadata['score'],
                "position": segment.position,
                "content": segment.content,
                "content_type": segment.content_type or "text",
                "image_url": segment.image_url or "",
                "page_number": segment.page_number or 0,
                "section_title": segment.section_title or "",
                "footer": segment.footer or "",
                "keywords": segment.keywords,
                "character_count": segment.character_count,
                "token_count": segment.token_count,
                "hit_count": segment.hit_count,
                "enabled": segment.enabled,
                "disabled_at": datetime_to_timestamp(segment.disabled_at),
                "status": segment.status,
                "error": segment.error,
                "updated_at": datetime_to_timestamp(segment.updated_at),
                "created_at": datetime_to_timestamp(segment.created_at),
            })

        # 6、组装响应：list 为召回片段，trace 为 agentic 命中轨迹（非 agentic 为空列表）
        return {
            "list": hit_result,
            "trace": trace,
            "agentic_enable": agentic_enable,
        }

    async def delete_dataset(self, dataset_id: UUID, account: Account) -> Dataset:
        """根据传递的知识库id删除知识库信息，涵盖知识库底下的所有文档、片段、关键词，以及向量数据库里存储的数据"""
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.account_id != account.id:
            raise NotFoundException("该知识库不存在")

        try:
            # 1、删除知识库基础记录一级知识库和应用关联的记录
            await self.delete(dataset)
            stmt = delete(AppDatasetJoin).where(AppDatasetJoin.dataset_id == dataset_id)
            await self.db.execute(stmt)
            await self.db.commit()  # 独立事务边界
            # 2、调用异步任务执行后续操作
            delete_dataset.delay(dataset_id)
        except Exception:
            logger.exception(f"删除知识库失败，dataset_id: {dataset_id}")
            raise FailedException("删除知识库失败，请稍后重试")

        return dataset
