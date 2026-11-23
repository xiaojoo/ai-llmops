#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/2 20:08
@author : sunxiaojie
@File   : document_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from typing import Annotated
from fastapi import Query
from internal.lib.helper import datetime_to_timestamp
from internal.server.deps import CurrentUser
from internal.schema.document_schema import (
    CreateDocumentsReq,
    CreateDocumentsResp,
    GetDocumentResp,
    GetDocumentsWithPageReq,
    GetDocumentsWithPageResp,
    UpdateDocumentEnableReq,
    UpdateDocumentNameReq,
)
from internal.service import DocumentService
from package.paginator import PageModel
from package.response import success_json, success_message_json


@dataclass
class DocumentHandler:
    """文档处理器"""
    document_service: DocumentService

    async def create_document(self, user: CurrentUser, dataset_id: UUID, req: CreateDocumentsReq) -> None:
        """知识库新增/上传文档列表"""
        documents, batch = await self.document_service.create_document(dataset_id, account=user, **req.model_dump())
        resp = CreateDocumentsResp.model_validate((documents, batch))
        return success_json(resp.model_dump(mode="json"))

    async def get_document(self, user: CurrentUser, dataset_id: UUID, document_id: UUID) -> None:
        """根据传递的知识库ID+文档ID获取文档详情信息"""
        document = await self.document_service.get_document(dataset_id, document_id, user)
        # 统计字段已上移为服务方法，由 handler 组装 dict。
        resp = GetDocumentResp.model_validate({
            "id": str(document.id),
            "dataset_id": str(document.dataset_id),
            "name": document.name,
            "title": document.title or "",
            "page_count": document.page_count or 0,
            "footer": document.footer or "",
            "segment_count": await self.document_service.get_segment_count(document, self.document_service.db),
            "character_count": document.character_count,
            "hit_count": await self.document_service.get_document_hit_count(document, self.document_service.db),
            "position": document.position,
            "enabled": document.enabled,
            "disabled_at": datetime_to_timestamp(document.updated_at),
            "status": document.status,
            "error": document.error,
            "updated_at": datetime_to_timestamp(document.updated_at),
            "created_at": datetime_to_timestamp(document.created_at),
        })
        return success_json(resp.model_dump(mode="json"))

    async def update_document_name(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, req: UpdateDocumentNameReq) -> None:
        """根据传递的知识库ID+文档ID更新对应文档的名称信息"""
        await self.document_service.update_document(dataset_id, document_id, user, name=req.name)
        return success_message_json("更新文档名称成功")

    async def update_document_enabled(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, req: UpdateDocumentEnableReq) -> None:
        """根据传递的知识库id+文档id更新指定文档的启用状态"""
        await self.document_service.update_document_enabled(dataset_id, document_id, user, enabled=req.enabled)
        return success_message_json("更改文档启用状态成功")

    async def delete_document(self, user: CurrentUser, dataset_id: UUID, document_id: UUID) -> None:
        """根据传递的知识库id+文档id删除指定的文档信息"""
        await self.document_service.delete_document(dataset_id, document_id, user)
        return success_message_json("删除文档成功")

    async def retry_document(self, user: CurrentUser, dataset_id: UUID, document_id: UUID) -> None:
        """根据传递的知识库id+文档id重试构建文档索引"""
        await self.document_service.retry_document(dataset_id, document_id, user)
        return success_message_json("已重新提交构建任务，请稍后在任务查看中确认进度")

    async def pause_document(self, user: CurrentUser, dataset_id: UUID, document_id: UUID) -> None:
        """根据传递的知识库id+文档id暂停文档构建"""
        await self.document_service.pause_document(dataset_id, document_id, user)
        return success_message_json("已暂停构建任务，可在任务查看中继续")

    async def resume_document(self, user: CurrentUser, dataset_id: UUID, document_id: UUID) -> None:
        """根据传递的知识库id+文档id继续构建文档"""
        await self.document_service.resume_document(dataset_id, document_id, user)
        return success_message_json("已继续构建任务，请稍后在任务查看中确认进度")

    async def preview_chunks(self, user: CurrentUser, dataset_id: UUID, req: CreateDocumentsReq) -> None:
        """切片预览：按当前分段方式/规则切分第一个文件，返回前几块用于对比调整"""
        chunks = await self.document_service.preview_chunks(dataset_id, account=user, **req.model_dump())
        return success_json(chunks)

    async def get_document_with_page(self, user: CurrentUser, dataset_id: UUID, req: Annotated[GetDocumentsWithPageReq, Query()]) -> None:
        """根据传递的知识库id获取文档分页列表数据"""
        documents, paginator = await self.document_service.get_documents_with_page(dataset_id, req, user)
        # 统计字段已上移为服务方法，由 handler 组装 dict。
        resp = []
        for d in documents:
            resp.append(GetDocumentsWithPageResp.model_validate({
                "id": str(d.id),
                "name": d.name,
                "title": d.title or "",
                "page_count": d.page_count or 0,
                "footer": d.footer or "",
                "character_count": d.character_count,
                "hit_count": await self.document_service.get_document_hit_count(d, self.document_service.db),
                "position": d.position,
                "enabled": d.enabled,
                "disabled_at": datetime_to_timestamp(d.updated_at),
                "status": d.status,
                "error": d.error,
                "segment_count": await self.document_service.get_segment_count(d, self.document_service.db),
                "completed_segment_count": getattr(d, "completed_segment_count", 0),
                "updated_at": datetime_to_timestamp(d.updated_at),
                "created_at": datetime_to_timestamp(d.created_at),
            }).model_dump(mode="json"))
        return success_json(PageModel(list=resp, paginator=paginator))

    async def get_documents_status(self, user: CurrentUser, dataset_id: UUID, batch: str) -> None:
        """根据传递的知识库id+批处理标识获取文档的状态"""
        documents_status = await self.document_service.get_documents_status(dataset_id, batch, user)
        return success_json(documents_status)
