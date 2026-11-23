#!/usr/bin/env python
"""
@Time    : 2026/3/22 20:41
@author  : sunxiaojie
@File    : chroma_vector_handler.py
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Query

from internal.schema.chroma_vector_schema import (
    AddVectorReq,
    ListVectorsReq,
    RecallTestReq,
    UpdateVectorReq,
)
from internal.service.chroma_vector_service import ChromaVectorService
from package.response import success_json, success_message_json


@dataclass
class ChromaVectorHandler:
    """Chroma 向量数据 CRUD 与召回测试处理器"""
    chroma_vector_service: ChromaVectorService

    async def list_vectors(self, req: Annotated[ListVectorsReq, Query()]) -> None:
        result = self.chroma_vector_service.list_vectors(req.page, req.page_size)
        return success_json(result)

    async def get_vector(self, doc_id: str) -> None:
        item = self.chroma_vector_service.get_vector(doc_id)
        return success_json(item)

    async def add_vector(self, req: AddVectorReq) -> None:
        item = self.chroma_vector_service.add_vector(req.id, req.content, req.metadata)
        return success_json(item)

    async def update_vector(self, doc_id: str, req: UpdateVectorReq) -> None:
        item = self.chroma_vector_service.update_vector(doc_id, req.content, req.metadata)
        return success_json(item)

    async def delete_vector(self, doc_id: str) -> None:
        self.chroma_vector_service.delete_vector(doc_id)
        return success_message_json("删除成功")

    async def clear_vectors(self) -> None:
        result = self.chroma_vector_service.clear_vectors()
        return success_json({"deleted": result})

    async def recall_test(self, req: RecallTestReq) -> None:
        results = self.chroma_vector_service.recall_test(
            query=req.query,
            top_k=req.top_k,
        )
        return success_json({"query": req.query, "total": len(results), "results": results})

    async def sync_documents(self) -> None:
        result = self.chroma_vector_service.sync_documents()
        return success_json(result)
