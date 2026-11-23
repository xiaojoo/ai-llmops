#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : bm25_retriever.py

BM25 全文检索器：直接调用 Weaviate 内置的 BM25 能力，
替代原先遍历 JSONB 关键词表的低效实现。
"""
from uuid import UUID

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document as LCDocument
from langchain_core.retrievers import BaseRetriever
from pydantic import Field
from weaviate.classes.query import Filter, MetadataQuery


class BM25Retriever(BaseRetriever):
    """Weaviate BM25 全文检索器"""

    dataset_ids: list[UUID]
    weaviate_client: object  # weaviate.Client
    search_kwargs: dict = Field(default_factory=dict)
    text_key: str = "text"

    def _get_relevant_documents(
            self,
            query: str,
            *,
            run_manager: CallbackManagerForRetrieverRun,
    ) -> list[LCDocument]:
        """执行 BM25 全文检索并返回带相关度得分的文档列表"""
        k = self.search_kwargs.get("k", 4)

        # 1、构建过滤条件：数据集 + 启用状态
        filters = Filter.all_of([
            Filter.by_property("dataset_id").contains_any(
                [str(dataset_id) for dataset_id in self.dataset_ids]
            ),
            Filter.by_property("document_enabled").equal(True),
            Filter.by_property("segment_enabled").equal(True),
        ])

        # 2、调用 Weaviate BM25 检索
        from internal.service.vector_database_service import COLLECTION_NAME

        collection = self.weaviate_client.collections.get(COLLECTION_NAME)
        response = collection.query.bm25(
            query=query,
            query_properties=[self.text_key],
            limit=k,
            filters=filters,
            return_metadata=MetadataQuery(score=True),
        )

        if response is None or len(response.objects) == 0:
            return []

        # 3、构建 LangChain 文档列表
        lc_documents = []
        for obj in response.objects:
            properties = obj.properties
            score = getattr(obj.metadata, "score", 0) or 0

            # 统一 id 字段为字符串（与 SemanticRetriever/FullTextRetriever 一致）
            def _str(v):
                return str(v) if v is not None else None

            lc_documents.append(LCDocument(
                page_content=properties.get(self.text_key, ""),
                metadata={
                    "account_id": _str(properties.get("account_id")),
                    "dataset_id": _str(properties.get("dataset_id")),
                    "document_id": _str(properties.get("document_id")),
                    "segment_id": _str(properties.get("segment_id")),
                    "node_id": _str(properties.get("node_id")),
                    "content_type": properties.get("content_type") or "text",
                    "summary": properties.get("summary") or "",
                    "parent_segment_id": _str(properties.get("parent_segment_id")),
                    "document_enabled": True,
                    "segment_enabled": True,
                    "score": float(score),
                    "source": "bm25",
                }
            ))

        return lc_documents
