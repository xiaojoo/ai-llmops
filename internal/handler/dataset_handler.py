#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 23:39
@author : sunxiaojie
@File   : dataset_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from internal.core.file_extractor import FileExtractor
from internal.lib.helper import datetime_to_timestamp
from internal.model.upload_file import UploadFile
from typing import Annotated
from fastapi import Query
from internal.server.deps import CurrentUser
from internal.schema.dataset_schema import (
    CreateOrUpdateDatasetReq,
    GetDatasetQueriesResp,
    GetDatasetResp,
    GetDatasetsWithPageReq,
    GetDatasetsWithPageResp,
    HitReq,
)
from internal.service import DatasetService
from package.paginator import PageModel
from package.response import success_json, success_message_json


@dataclass
class DatasetHandler:
    """知识库处理器"""
    dataset_service: DatasetService
    file_extractor: FileExtractor

    async def embeddings_query(self, user: CurrentUser) -> None:
        """Embeddings查询（调试接口）——加载指定文件并返回提取内容"""
        from sqlalchemy import select
        stmt = select(UploadFile).where(UploadFile.id == "3df2bde2-5c18-4dd3-9ac7-353f7663b268")
        upload_file = (await self.dataset_service.db.execute(stmt)).scalar_one_or_none()
        if upload_file is None:
            return success_json({"content": ""})
        content = self.file_extractor.load(upload_file, True)
        return success_json({"content": content})

    async def hit(self, user: CurrentUser, dataset_id: UUID, req: HitReq) -> None:
        """根据传递的知识库id+检索参数执行召回测试"""
        hit_result = await self.dataset_service.hit(dataset_id, req, user)
        return success_json(hit_result)

    async def get_dataset_queries(self, user: CurrentUser, dataset_id: UUID) -> None:
        """根据传递的知识库id获取最近10条查询记录"""
        dataset_queries = await self.dataset_service.get_dataset_queries(dataset_id, user)
        resp = [
            GetDatasetQueriesResp.model_validate(q).model_dump(mode="json")
            for q in dataset_queries
        ]
        return success_json(resp)

    async def create_dataset(self, user: CurrentUser, req: CreateOrUpdateDatasetReq) -> None:
        """创建知识库"""
        await self.dataset_service.create_dataset(req, user)
        return success_message_json("创建知识库成功")

    async def get_dataset(self, user: CurrentUser, dataset_id: UUID) -> None:
        """根据传递的知识库id获取详情"""
        dataset = await self.dataset_service.get_dataset(dataset_id, user)
        # 统计字段已上移为服务方法，由 handler 组装 dict（与 get_datasets_with_page 一致）。
        resp = GetDatasetResp.model_validate({
            "id": str(dataset.id),
            "name": dataset.name,
            "icon": dataset.icon,
            "description": dataset.description,
            "document_count": await self.dataset_service.get_document_count(dataset, self.dataset_service.db),
            "hit_count": await self.dataset_service.get_hit_count(dataset, self.dataset_service.db),
            "related_app_count": await self.dataset_service.get_related_app_count(dataset, self.dataset_service.db),
            "character_count": await self.dataset_service.get_character_count(dataset, self.dataset_service.db),
            "updated_at": datetime_to_timestamp(dataset.updated_at),
            "created_at": datetime_to_timestamp(dataset.created_at),
        })
        return success_json(resp.model_dump(mode="json"))

    async def update_dataset(self, user: CurrentUser, dataset_id: UUID, req: CreateOrUpdateDatasetReq) -> None:
        """根据传递的知识库id+信息更新知识库"""
        await self.dataset_service.update_dataset(dataset_id, req, user)
        return success_message_json("更新知识库成功")

    async def delete_dataset(self, user: CurrentUser, dataset_id: UUID) -> None:
        """根据传递的知识库id删除知识库"""
        await self.dataset_service.delete_dataset(dataset_id, user)
        return success_message_json("删除知识库成功")

    async def get_datasets_with_page(self, user: CurrentUser, req: Annotated[GetDatasetsWithPageReq, Query()]) -> None:
        """获取知识库分页+搜索列表数据"""
        datasets, paginator = await self.dataset_service.get_dataset_with_page(req, user)
        # 统计字段已上移为服务方法，由 handler 组装 dict。
        resp = []
        for dataset in datasets:
            resp.append(GetDatasetsWithPageResp.model_validate({
                "id": str(dataset.id),
                "name": dataset.name,
                "icon": dataset.icon,
                "description": dataset.description,
                "document_count": await self.dataset_service.get_document_count(dataset, self.dataset_service.db),
                "hit_count": await self.dataset_service.get_hit_count(dataset, self.dataset_service.db),
                "related_app_count": await self.dataset_service.get_related_app_count(dataset, self.dataset_service.db),
                "character_count": await self.dataset_service.get_character_count(dataset, self.dataset_service.db),
                "updated_at": datetime_to_timestamp(dataset.updated_at),
                "created_at": datetime_to_timestamp(dataset.created_at),
            }).model_dump(mode="json"))
        return success_json(PageModel(list=resp, paginator=paginator))
