#!/usr/bin/env python
"""
@Time    : 2025/12/8 22:42
@Author  : sunxiaojie
@File    : full_text_retriever.py
"""
from collections import Counter
from typing import Any
from uuid import UUID

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document as LCDocument
from langchain_core.retrievers import BaseRetriever
from pydantic import Field
from sqlalchemy import select

from internal.model import KeywordTable, Segment
from internal.service import LtpService


class FullTextRetriever(BaseRetriever):
    """全文检索器"""
    db: Any
    ltp_service: LtpService

    dataset_ids: list[UUID]
    search_kwargs: dict = Field(default_factory=dict)

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[LCDocument]:
        """根据传递的query执行关键词检索获取LangChain文档列表"""
        # 1、将查询query转换成关键词列表
        keywords = self.ltp_service.extract_keywords(query, 10)
        # 2、查找指定知识库的管检词表
        stmt = (
            select(KeywordTable.keyword_table)
            .where(KeywordTable.dataset_id.in_(self.dataset_ids))
        )
        result = self.db.execute(stmt).all()
        keyword_tables = [keyword_table for keyword_table, in result]
        # 3、遍历所有的知识库关键词表，找到匹配query关键词的id列表
        all_ids = []
        for keyword_table in keyword_tables:
            for keyword, segment_ids in keyword_table.items():
                # 4、如果数据存在则提取关键词对应的片段id列表
                if keyword in keywords:
                    all_ids.extend(segment_ids)
        # 5、统计segment_id出现的频率
        id_counter = Counter(all_ids)
        # 6、获取频率最高的前k条数据，格式为[(segment_id, freq), (segment_id, freq)]
        k = self.search_kwargs.get("k", 4)
        top_10_ids = id_counter.most_common(k)
        # 7、根据得到的id列表检索数据库得到的片段列表信息
        segment_ids = [id for id, _ in top_10_ids]
        stmt = (
            select(Segment).where(Segment.id.in_(segment_ids))
        )
        segments = self.db.execute(stmt).scalars().all()
        segment_dict = {
            str(segment.id): segment for segment in segments
        }
        # 8、根据频率进行排序
        sorted_segments = [segment_dict[str(id)] for id, freq in top_10_ids if id in segment_dict]
        # 9、构建LangChain文档列表
        lc_documents = [LCDocument(
            page_content=segment.content,
            metadata={
                "account_id": str(segment.account_id),
                "dataset_id": str(segment.dataset_id),
                "document_id": str(segment.document_id),
                "segment_id": str(segment.id),
                "node_id": str(segment.node_id),
                "content_type": segment.content_type or "text",
                "summary": segment.summary or "",
                "parent_segment_id": str(segment.parent_segment_id) if segment.parent_segment_id else None,
                "document_enabled": True,
                "segment_enabled": True,
                "score": 0,
                "source": "ltp",
            }
        ) for segment in sorted_segments]

        return lc_documents
