#!/usr/bin/env python
"""
@Time    : 2026/3/23 1:01
@author  : sunxiaojie
@File    : weaviate_vector_handler.py
"""
from dataclasses import dataclass

from internal.server.deps import CurrentUser
from internal.schema.weaviate_vector_schema import (
    WeaviateDeleteDocumentReq,
    WeaviateDeleteMemoryReq,
    WeaviateRecallReq,
)
from internal.service import WeaviateVectorService
from package.response import success_json


@dataclass
class WeaviateVectorHandler:
    """Weaviate 向量数据库处理器"""
    weaviate_vector_service: WeaviateVectorService

    async def recall_test(self, user: CurrentUser, req: WeaviateRecallReq) -> None:
        """向量召回测试"""
        results = await self.weaviate_vector_service.recall(
            dataset_id=req.dataset_id,
            query=req.query,
            top_k=req.top_k,
            score_threshold=req.score_threshold,
            document_id=req.document_id or None,
        )
        return success_json(results)

    async def delete_document(self, user: CurrentUser, req: WeaviateDeleteDocumentReq) -> None:
        """从Weaviate删除指定文档的所有向量数据"""
        await self.weaviate_vector_service.delete_document(
            dataset_id=req.dataset_id,
            account=user,
        )
        return success_json({"message": "文档向量数据已删除"})

    async def delete_memory(self, user: CurrentUser, req: WeaviateDeleteMemoryReq) -> None:
        """按 app_id 清空记忆集合（EpisodicMemory 等）中的向量数据"""
        await self.weaviate_vector_service.delete_memory(
            collection_name=req.collection_name,
            app_id=req.app_id,
            account=user,
        )
        return success_json({"message": "记忆数据已删除"})

    async def get_all_collections(self, user: CurrentUser) -> None:
        """查询所有 Collection 名称列表"""
        collections = await self.weaviate_vector_service.get_all_collections()
        return success_json({"collections": collections})

    async def get_all(
        self, user: CurrentUser,
        collection_name: str | None = None,
        app_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> None:
        """查询 Collection 下全量分块（不过滤）"""
        result = await self.weaviate_vector_service.get_all(
            collection_name=collection_name,
            dataset_id=None,
            app_id=app_id,
            limit=limit,
            offset=offset,
        )
        return success_json(result)

    async def get_all_by_dataset(
        self, user: CurrentUser,
        dataset_id: str | None = None,
        document_id: str | None = None,
        collection_name: str | None = None,
        app_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> None:
        """查询 Collection 下指定 dataset_id 的分块"""
        result = await self.weaviate_vector_service.get_all(
            collection_name=collection_name,
            dataset_id=dataset_id,
            document_id=document_id,
            app_id=app_id,
            limit=limit,
            offset=offset,
        )
        return success_json(result)

    async def get_documents_by_collection(
        self, user: CurrentUser,
        collection_name: str | None = None,
        page: int = 1,
        page_size: int = 8,
    ) -> None:
        """查询 Collection 下文档及分块数（支持分页）"""
        result = await self.weaviate_vector_service.get_documents_by_collection(
            collection_name=collection_name,
            page=max(page, 1),
            page_size=max(page_size, 1),
        )
        return success_json(result)

    async def get_segments_by_document(
        self, user: CurrentUser,
        document_id: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> None:
        """查询指定文档下所有分块（含原文，按 position 排序）"""
        result = await self.weaviate_vector_service.get_segments_by_document(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
        return success_json(result)

    async def get_metadata(
        self, user: CurrentUser,
        dataset_id: str = "",
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> None:
        """查询元数据（不含向量原文）"""
        result = await self.weaviate_vector_service.get_metadata(
            dataset_id=dataset_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
        return success_json(result)
