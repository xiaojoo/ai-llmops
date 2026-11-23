#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : episodic_memory_service.py
"""
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from anyio import to_thread
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model import EpisodicMemory

from .base_service import BaseService
from .embeddings_service import EmbeddingsService
from .language_model_service import LanguageModelService
from .vector_database_service import VectorDatabaseService

logger = logging.getLogger(__name__)


# 情景记忆抽取提示词：记录有复用价值的对话经历（含一次性任务/问答中暴露的用户事实），宁缺毋滥
EPISODE_EXTRACTOR_TEMPLATE = """你是一个情景记忆抽取器。请判断用户与助手的对话中，是否有值得长期记住的"经历"。

值得记录的经历示例：
- 用户正在推进的一个长期任务及其进展（如"正在准备搬家到北京，已完成房源搜索"）
- 用户提出的一次性任务及其结果（如"用户要求撰写新能源行业研究报告，助手已完成并输出市场/技术/政策/竞争四部分"）
- 用户在问答/闲聊中暴露的稳定事实或偏好（如"用户是一名后端工程师，在深圳工作"、"用户偏好用表格对比方案"）
- 反复出现的行为模式（如"用户每次提问都要求先给结论"）

不值得记录的内容：
- 纯寒暄且无任何用户信息的问候（如"你好""在吗"）；
- 助手自己的行为总结（除非用户明确认可）；
- 指令性内容（"以后都要XX"这类要求不构成经历，属于程序记忆范畴）；
- 用户未参与的助手自言自语。

规则：
1. importance 表示该经历对后续对话的价值（0~1）：长期任务跟踪/行为模式给 0.8 以上，一次性任务/问答事实给 0.4~0.7；
2. 只要对话中出现了"用户相关信息"（任务、事实、偏好、进展、决策），都尽量抽取；确实没有任何用户信息时才输出空列表；
3. 严禁记录猜测的敏感信息与用户隐私细节。

已有情景记忆：
{existing_memories}

本轮对话：
Human: {query}
AI: {answer}

输出严格 JSON，不要输出其他内容：
{{"episodes": [{{"content": "...", "importance": 0.x, "evidence": "..."}}]}}"""


@dataclass
class EpisodicMemoryService(BaseService):
    """情景记忆服务：写侧管道（抽取+向量入库）与检索"""
    db: AsyncSession
    language_model_service: LanguageModelService
    embeddings_service: EmbeddingsService
    vector_database_service: VectorDatabaseService

    async def extract_episodes(self, query: str, answer: str, existing_memories_text: str) -> list[dict]:
        """根据本轮对话抽取值得记住的经历（写侧管道入口）"""
        try:
            import asyncio
            prompt = ChatPromptTemplate.from_template(EPISODE_EXTRACTOR_TEMPLATE)
            llm = await self.language_model_service.load_default_language_model()
            llm.temperature = 0
            chain = prompt | llm | StrOutputParser()
            # 同步 LLM 调用经线程池桥接，避免后台线程跨 loop 死锁
            raw = await asyncio.to_thread(
                lambda: chain.invoke({
                    "query": query,
                    "answer": answer,
                    "existing_memories": existing_memories_text,
                })
            )
            return self._parse_episodes(raw)
        except Exception:
            logger.exception("情景记忆抽取失败")
            return []

    def _parse_episodes(self, raw: str) -> list[dict]:
        """容错解析 LLM 输出：剥离 ```json 围栏，取第一个 JSON 对象"""
        if not raw:
            return []
        text = raw.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
        episodes = []
        for item in data.get("episodes", []):
            try:
                episodes.append({
                    "content": str(item["content"]),
                    "importance": float(item.get("importance", 0.5)),
                    "evidence": str(item.get("evidence", "")),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return episodes

    async def write_episode(
            self,
            *,
            app_id: UUID,
            user_id: UUID,
            content: str,
            importance: float,
            source: str = "llm_inferred",
    ) -> EpisodicMemory:
        """写入一条情景记忆：Postgres 落库 + embedding 入库 Weaviate"""
        # 1、向量入库（按 user_id 命名空间隔离）——同步 embeddings + 同步 weaviate 调用经线程池桥接
        import asyncio
        embedding = await asyncio.to_thread(
            self.embeddings_service.embeddings.embed_query, content,
        )
        collection = self.vector_database_service.episodic_memory_collection
        obj_id = await to_thread.run_sync(
            lambda: collection.data.insert(
                properties={
                    "app_id": str(app_id),
                    "user_id": str(user_id),
                    "content": content,
                    "importance": importance,
                    "created_at": datetime.now().timestamp(),
                },
                vector=embedding,
            ),
        )

        # 2、Postgres 落库（关联 embedding_id 便于审计/删除）
        return await self.create(
            EpisodicMemory,
            app_id=app_id, user_id=user_id,
            content=content, importance=importance,
            source=source, trust_score=0.5,
            expires_at=None, embedding_id=str(obj_id),
        )

    async def upsert_episodes(self, app_id: UUID, user_id: UUID, episodes: list[dict]) -> list[EpisodicMemory]:
        """批量写入抽取结果"""
        results = []
        for episode in episodes:
            record = await self.write_episode(
                app_id=app_id, user_id=user_id,
                content=episode["content"],
                importance=episode["importance"],
            )
            results.append(record)
        return results

    def _recency_weight(self, created_at: datetime, decay: float = 0.05) -> float:
        """新近度权重：exp(-decay * age_days)，距今越近权重越高"""
        age_days = max((datetime.now() - created_at).total_seconds() / 86400.0, 0.0)
        return math.exp(-decay * age_days)

    async def _recall_vector(self, app_id: UUID, user_id: UUID, query: str, k: int) -> list[tuple[str, float]]:
        """向量召回：near_vector + Filter(user_id)，返回 [(memory_id, similarity)]"""
        from weaviate.classes.query import Filter, MetadataQuery

        # 同步 embeddings 调用经线程池桥接
        import asyncio
        query_vector = await asyncio.to_thread(
            self.embeddings_service.embeddings.embed_query, query,
        )
        collection = self.vector_database_service.episodic_memory_collection
        filters = Filter.all_of([
            Filter.by_property("app_id").equal(str(app_id)),
            Filter.by_property("user_id").equal(str(user_id)),
        ])
        response = await to_thread.run_sync(
            lambda: collection.query.near_vector(
                near_vector=query_vector,
                limit=k,
                filters=filters,
                return_metadata=MetadataQuery(distance=True),
            ),
        )
        results = []
        for obj in response.objects:
            distance = obj.metadata.distance or 1.0
            similarity = max(1.0 - distance, 0.0)
            results.append((obj.uuid, similarity))
        return results

    async def _recall_bm25(self, app_id: UUID, user_id: UUID, query: str, k: int) -> list[tuple[str, float]]:
        """BM25 召回：Weaviate bm25 + Filter(user_id)，返回 [(memory_id, score)]"""
        from weaviate.classes.query import Filter, MetadataQuery

        collection = self.vector_database_service.episodic_memory_collection
        filters = Filter.all_of([
            Filter.by_property("app_id").equal(str(app_id)),
            Filter.by_property("user_id").equal(str(user_id)),
        ])
        response = await to_thread.run_sync(
            lambda: collection.query.bm25(
                query=query,
                query_properties=["content"],
                limit=k,
                filters=filters,
                return_metadata=MetadataQuery(score=True),
            ),
        )
        results = []
        for obj in response.objects:
            score = getattr(obj.metadata, "score", 0) or 0
            results.append((obj.uuid, float(score)))
        return results

    async def search_episodes(
            self,
            app_id: UUID,
            user_id: UUID,
            query: str,
            *,
            top_k: int = 5,
            fusion_k: int = 20,
    ) -> list[EpisodicMemory]:
        """情景记忆检索：向量 + BM25 双路召回 → RRF 融合 → 新近度/重要性加权 → top-k

        检索隔离：所有召回均带 (app_id, user_id) 过滤，防止多用户记忆混乱。
        """
        from internal.core.retrievers.rrf import rrf_fusion

        # 1、双路召回
        vector_hits = await self._recall_vector(app_id, user_id, query, fusion_k)
        bm25_hits = await self._recall_bm25(app_id, user_id, query, fusion_k)

        # 2、RRF 融合（key = memory_id）
        fused = rrf_fusion(
            [vector_hits, bm25_hits],
            key_func=lambda pair: pair[0],
        )

        if not fused:
            return []

        # 3、按 embedding_id 批量加载记录并加权排序
        embedding_ids = [str(pair[0]) for pair, _ in fused[:fusion_k]]
        stmt = (
            select(EpisodicMemory)
            .where(
                EpisodicMemory.embedding_id.in_(embedding_ids),
                EpisodicMemory.is_deleted.is_(False),
            )
        )
        records = {record.embedding_id: record for record in (await self.db.execute(stmt)).scalars().all()}

        ranked = []
        for pair, rrf_score in fused:
            record = records.get(str(pair[0]))
            if record is None:
                continue
            final_score = (
                rrf_score
                + 0.3 * self._recency_weight(record.created_at)
                + 0.4 * record.importance
            )
            ranked.append((record, final_score))

        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return [record for record, _ in ranked[:top_k]]

    async def get_recent_text(self, app_id: UUID, user_id: UUID, limit: int = 5) -> str:
        """获取最近的情景记忆文本（供写侧管道参考，避免重复记录）"""
        stmt = (
            select(EpisodicMemory)
            .where(
                EpisodicMemory.app_id == app_id,
                EpisodicMemory.user_id == user_id,
                EpisodicMemory.is_deleted.is_(False),
            )
            .order_by(desc(EpisodicMemory.created_at))
            .limit(limit)
        )
        records = (await self.db.execute(stmt)).scalars().all()
        return "\n".join(f"- {r.content}" for r in records)

    async def get_episodes(self, app_id: UUID, user_id: UUID, limit: int = 50) -> list[EpisodicMemory]:
        """获取用户在当前应用下的情景记忆记录（调试/审计，按创建时间倒序）"""
        stmt = (
            select(EpisodicMemory)
            .where(
                EpisodicMemory.app_id == app_id,
                EpisodicMemory.user_id == user_id,
                EpisodicMemory.is_deleted.is_(False),
            )
            .order_by(desc(EpisodicMemory.created_at))
            .limit(limit)
        )
        return (await self.db.execute(stmt)).scalars().all()
