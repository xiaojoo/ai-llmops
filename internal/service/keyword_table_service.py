#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/3 20:53
@Author : sunxiaojie
@File   : keyword_table_service.py
"""
from dataclasses import dataclass
from uuid import UUID

from redis import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.cache_entity import (
    LOCK_EXPIRE_TIME,
    LOCK_KEYWORD_TABLE_UPDATE_KEYWORD,
)
from internal.model import KeywordTable, Segment

from .base_service import BaseService


@dataclass
class KeywordTableService(BaseService):
    """知识库关键词表服务"""
    db: AsyncSession
    redis_client: Redis

    async def get_keyword_table_from_dataset_id(self, dataset_id: UUID) -> KeywordTable:
        """根据传递的知识库id获取关键词表"""
        stmt = select(KeywordTable).where(
            KeywordTable.dataset_id == dataset_id
        )
        keyword_table = (await self.db.execute(stmt)).scalars().one_or_none()
        if keyword_table is None:
            keyword_table = await self.create(KeywordTable, dataset_id=dataset_id, keyword_table={})

        return keyword_table

    async def delete_keyword_table_from_ids(self, dataset_id: UUID, segment_ids: list[UUID]) -> None:
        """根据传递的知识库id+片段id列表刷除对应关键词表中多余的数据"""
        cache_key = LOCK_KEYWORD_TABLE_UPDATE_KEYWORD.format(dataset_id=dataset_id)
        with self.redis_client.lock(cache_key, timeout=LOCK_EXPIRE_TIME):
            # 1、获取当前知识库关键词表
            keyword_table_record = await self.get_keyword_table_from_dataset_id(dataset_id)
            keyword_table = keyword_table_record.keyword_table.copy()

            segment_ids_to_delete = {str(segment_id) for segment_id in segment_ids}
            keywords_to_delete = set()

            # 2、循环遍历所有关键词执行判断与更新
            for keyword, ids in keyword_table.items():
                ids_set = set(ids)
                if segment_ids_to_delete.intersection(ids_set):
                    keyword_table[keyword] = list(ids_set.difference(segment_ids_to_delete))
                    if not keyword_table[keyword]:
                        keywords_to_delete.add(keyword)

            # 3、检测空关键词数据并删除
            for keyword in keywords_to_delete:
                del keyword_table[keyword]

            # 4、将数据更新到关键词中
            await self.update(keyword_table_record, keyword_table=keyword_table)

    async def add_keyword_table_from_ids(self, dataset_id: UUID, segment_ids: list[UUID]) -> None:
        """根据传递的知识库id+片段id列表，在关键词表中添加关键词"""
        cache_key = LOCK_KEYWORD_TABLE_UPDATE_KEYWORD.format(dataset_id=dataset_id)
        with self.redis_client.lock(cache_key, timeout=LOCK_EXPIRE_TIME):
            # 1、获取关键词表记录
            keyword_table_record = await self.get_keyword_table_from_dataset_id(dataset_id)
            # 2、关键：先对"已有关键词表"做一次深度 normalize（UUID → str）
            raw_keyword_table = keyword_table_record.keyword_table or {}

            keyword_table: dict[str, set[str]] = {}
            for keyword, ids in raw_keyword_table.items():
                # ids里不管是UUID/str/混合，全转为str
                keyword_table[keyword] = {str(i) for i in ids}

            # 3、根据segment_ids查询片段关键词
            segments = (await self.db.execute(
                select(Segment.id, Segment.keywords).where(Segment.id.in_(segment_ids))
            )).all()

            # 4、添加新关键词
            for segment_id, keywords in segments:
                segment_id_str = str(segment_id)
                for keyword in keywords:
                    keyword_table.setdefault(keyword, set()).add(segment_id_str)

            # 5、再次兜底：更新前确保没有任何非str
            safe_keyword_table = {
                keyword: [str(v) for v in ids]
                for keyword, ids in keyword_table.items()
            }

            # 6、更新数据库（JSONB 内只会是 string）
            await self.update(
                keyword_table_record,
                keyword_table=safe_keyword_table
            )
