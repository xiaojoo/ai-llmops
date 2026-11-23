#!/usr/bin/env python
"""
@Time    : 2025/12/8 22:16
@Author  : sunxiaojie
@File    : semantic_retriever.py
"""
from uuid import UUID

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document as LCDocument
from langchain_core.retrievers import BaseRetriever
from langchain_weaviate import WeaviateVectorStore
from pydantic import Field
from weaviate.classes.query import Filter


class SemanticRetriever(BaseRetriever):
    """相似性检索器/向量检索器"""
    dataset_ids: list[UUID]
    vector_store: WeaviateVectorStore
    search_kwargs: dict = Field(default_factory=dict)

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[LCDocument]:
        """根据传递的query执行相似性检索"""
        # 1、复制 search_kwargs，避免修改共享配置；提取 k 后其余参数透传
        search_kwargs = dict(self.search_kwargs)
        k = search_kwargs.pop("k", 4)
        score_threshold = search_kwargs.pop("score_threshold", None)

        filters = Filter.all_of([
            Filter.by_property("dataset_id").contains_any([str(dataset_id) for dataset_id in self.dataset_ids]),
            Filter.by_property("document_enabled").equal(True),
            Filter.by_property("segment_enabled").equal(True),
        ])

        search_results = self.vector_store.similarity_search_with_relevance_scores(
            query=query,
            k=k,
            filters=filters,
            score_threshold=score_threshold,
            **search_kwargs
        )

        if search_results is None or len(search_results) == 0:
            return []

        lc_documents = []
        for doc, score in search_results:
            doc.metadata["score"] = score
            doc.metadata["source"] = "semantic"
            # 统一 metadata 中 id 字段为字符串（与 FullTextRetriever/BM25Retriever 一致）
            for id_field in ("segment_id", "node_id", "document_id", "dataset_id", "account_id"):
                if doc.metadata.get(id_field) is not None:
                    doc.metadata[id_field] = str(doc.metadata[id_field])
            lc_documents.append(doc)

        return lc_documents
