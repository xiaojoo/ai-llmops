#!/usr/bin/env python
"""
@Time    : 2025/12/8 18:39
@author  : sunxiaojie
@File    : segment_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.segment_schema import (
    CreateSegmentReq,
    GetSegmentResp,
    GetSegmentsWithPageReq,
    GetSegmentsWithPageResp,
    UpdateSegmentEnabledReq,
)
from internal.service import SegmentService
from package.paginator import PageModel
from package.response import success_json, success_message_json


@dataclass
class SegmentHandler:
    """片段处理器"""
    segment_service: SegmentService

    async def create_segment(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, req: CreateSegmentReq) -> None:
        """根据传递的信息创建知识库文档片段"""
        await self.segment_service.create_segment(dataset_id, document_id, req, user)
        return success_message_json("新增文档片段成功")

    async def get_segments_with_page(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, req: Annotated[GetSegmentsWithPageReq, Query()]) -> None:
        """获取指定知识库文档的片段列表信息"""
        segments, paginator = await self.segment_service.get_segments_with_page(dataset_id, document_id, req, user)
        resp = [
            GetSegmentsWithPageResp.model_validate(s).model_dump(mode="json")
            for s in segments
        ]
        return success_json(PageModel(list=resp, paginator=paginator))

    async def get_segment(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, segment_id: UUID) -> None:
        """获取指定的文档片段信息详情"""
        segment = await self.segment_service.get_segment(dataset_id, document_id, segment_id, user)
        resp = GetSegmentResp.model_validate(segment)
        return success_json(resp.model_dump(mode="json"))

    async def update_segment_enabled(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, segment_id: UUID, req: UpdateSegmentEnabledReq) -> None:
        """根据传递的信息更新指定的文档片段启用状态"""
        await self.segment_service.update_segment_enabled(dataset_id, document_id, segment_id, user, req.enabled)
        return success_message_json("修改片段状态成功")

    async def delete_segment(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, segment_id: UUID) -> None:
        """根据传递的信息删除指定文档片段信息"""
        await self.segment_service.delete_segment(dataset_id, document_id, segment_id, user)
        return success_message_json("删除文档片段成功")

    async def update_segment(self, user: CurrentUser, dataset_id: UUID, document_id: UUID, segment_id: UUID, req: CreateSegmentReq) -> None:
        """根据传递的信息更新文档片段信息"""
        await self.segment_service.update_segment(dataset_id, document_id, segment_id, req, user)
        return success_message_json("更新文档片段成功")
