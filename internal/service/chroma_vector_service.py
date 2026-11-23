#!/usr/bin/env python
"""
@Time    : 2026/03/22 21:49
@Author  : sunxiaojie
@File    : chroma_vector_service.py
"""

from dataclasses import dataclass

from langchain_core.documents import Document

from internal.exception import NotFoundException, ValidateException
from internal.service.chroma_service import ChromaService


@dataclass
class ChromaVectorService:
    """Chroma 向量数据 CRUD 与召回测试"""
    chroma_service: ChromaService

    def list_vectors(self, page: int = 1, page_size: int = 20) -> dict:
        """分页查询向量库中所有记录（含向量维度摘要）"""
        result = self.chroma_service.chroma.get(
            include=["documents", "metadatas", "embeddings"]
        )
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        embeddings = result.get("embeddings")
        has_embeddings = embeddings is not None and len(embeddings) > 0

        total = len(ids)
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = max(1, min(page, total_pages))
        start = (current_page - 1) * page_size
        end = start + page_size

        items = [
            {
                "id": ids[i],
                "content": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "embedding_dims": len(embeddings[i]) if has_embeddings and i < len(embeddings) else 0,
                "embedding_preview": [round(float(v), 6) for v in embeddings[i][:8]] if has_embeddings and i < len(
                    embeddings) else [],
            }
            for i in range(start, min(end, total))
        ]

        return {
            "list": items,
            "paginator": {
                "total_count": total,
                "total_pages": total_pages,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_vector(self, doc_id: str) -> dict:
        """查询单条向量记录（含完整向量数组）"""
        result = self.chroma_service.chroma.get(
            ids=[doc_id],
            include=["documents", "metadatas", "embeddings"]
        )
        ids = result.get("ids", [])
        if not ids:
            raise NotFoundException(f"记录 {doc_id} 不存在")

        embeddings = result.get("embeddings")
        embedding = [round(float(v), 6) for v in embeddings[0]] if embeddings is not None and len(
            embeddings) > 0 else []

        return {
            "id": ids[0],
            "content": result["documents"][0] if result.get("documents") else "",
            "metadata": result["metadatas"][0] if result.get("metadatas") else {},
            "embedding_dims": len(embedding),
            "embedding": embedding,
        }

    def add_vector(self, doc_id: str, content: str, metadata: dict | None = None) -> dict:
        """新增一条向量记录"""
        # 检查是否已存在
        existing = self.chroma_service.chroma.get(ids=[doc_id])
        if existing.get("ids"):
            raise ValidateException(f"ID {doc_id} 已存在，请使用更新接口")

        doc = Document(page_content=content, metadata=metadata or {})
        self.chroma_service.chroma.add_documents(documents=[doc], ids=[doc_id])
        return {"id": doc_id, "content": content, "metadata": metadata or {}}

    def update_vector(self, doc_id: str, content: str, metadata: dict | None = None) -> dict:
        """更新一条向量记录（先删后加）"""
        existing = self.chroma_service.chroma.get(ids=[doc_id])
        if not existing.get("ids"):
            raise NotFoundException(f"记录 {doc_id} 不存在")

        self.chroma_service.chroma.delete(ids=[doc_id])
        doc = Document(page_content=content, metadata=metadata or {})
        self.chroma_service.chroma.add_documents(documents=[doc], ids=[doc_id])
        return {"id": doc_id, "content": content, "metadata": metadata or {}}

    def delete_vector(self, doc_id: str) -> None:
        """删除一条向量记录"""
        existing = self.chroma_service.chroma.get(ids=[doc_id])
        if not existing.get("ids"):
            raise NotFoundException(f"记录 {doc_id} 不存在")
        self.chroma_service.chroma.delete(ids=[doc_id])

    def clear_vectors(self) -> int:
        """清空所有向量记录，返回删除数量"""
        result = self.chroma_service.chroma.get()
        ids = result.get("ids", [])
        if ids:
            self.chroma_service.chroma.delete(ids=ids)
        return len(ids)

    def recall_test(
            self,
            query: str,
            top_k: int = 5,
    ) -> list[dict]:
        """
        召回测试：相似度检索，返回距离与相关性判定
        :param query: 查询语句
        :param top_k: 返回条数
        """
        chroma = self.chroma_service.chroma
        raw = chroma.similarity_search_with_score(query, k=top_k)

        return [
            {
                "id": doc.metadata.get("source", ""),
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": round(float(score), 6),
                "relevant": score <= 1.2,  # 距离 < 1.2 视为相关
            }
            for doc, score in raw
        ]

    def sync_documents(self) -> dict:
        """触发同步本地 storage/vector_store 目录到向量库"""
        before = len(self.chroma_service.chroma.get().get("ids", []))
        self.chroma_service.sync_local_documents()
        after = len(self.chroma_service.chroma.get().get("ids", []))
        return {"before": before, "after": after, "added": after - before}
