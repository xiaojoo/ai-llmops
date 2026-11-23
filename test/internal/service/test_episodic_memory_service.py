#!/usr/bin/env python
"""EpisodicMemoryService 写侧管道测试：LLM 抽取经历 + 向量入库

service 经 container 工厂构造（真实 db_session），load_default_language_model
为 AsyncMock，方法全 await；向量依赖（embeddings / episodic_memory_collection）替换为假实现。
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.container import create_episodic_memory_service


class FakeEpisodeLLM:
    temperature = 0.0

    def __init__(self, reply):
        self.reply = reply

    def invoke(self, inputs):
        return self.reply

    def __call__(self, inputs):
        return self.reply


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class TestEpisodicWrite:
    @pytest.mark.asyncio
    async def test_extract_episodes_parses(self, db_session, monkeypatch):
        service = create_episodic_memory_service(db_session)
        raw = (
            '```json\n{"episodes": [{"content": "用户询问北京天气，Agent 推荐了周末行程", '
            '"importance": 0.8, "evidence": "用户连续询问北京相关话题"}]}\n```'
        )
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            AsyncMock(return_value=FakeEpisodeLLM(raw)),
        )

        episodes = await service.extract_episodes("北京天气怎么样", "为您推荐了行程", "")

        assert len(episodes) == 1
        assert episodes[0]["content"].startswith("用户询问北京天气")
        assert episodes[0]["importance"] == 0.8

    @pytest.mark.asyncio
    async def test_write_episode_persists_and_embeds(self, db_session, monkeypatch):
        service = create_episodic_memory_service(db_session)
        # 替换向量相关依赖：embeddings 与 weaviate 集合
        fake_collection = MagicMock()
        fake_collection.data.insert.return_value = "obj-id-123"
        monkeypatch.setattr(
            service.vector_database_service, "episodic_memory_collection",
            fake_collection,
        )
        monkeypatch.setattr(service.embeddings_service, "embeddings", FakeEmbeddings())

        episode = await service.write_episode(
            app_id=uuid4(), user_id=uuid4(),
            content="用户询问北京天气，Agent 推荐了行程",
            importance=0.8,
        )

        assert episode.embedding_id == "obj-id-123"
        assert episode.importance == 0.8
        fake_collection.data.insert.assert_called_once()


class TestEpisodicSearch:
    def test_recency_weight_decays(self):
        service = create_episodic_memory_service(MagicMock())
        now = datetime.now()
        assert service._recency_weight(now) == 1.0
        old = service._recency_weight(now - timedelta(days=30))
        assert 0 < old < 1.0, "30 天前经历的新近度权重应小于 1"

    @pytest.mark.asyncio
    async def test_search_fuses_and_ranks(self, db_session, monkeypatch):
        service = create_episodic_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()

        # 向量依赖替换为假实现（避免真实连接模型/weaviate）
        fake_collection = MagicMock()
        # 两条写入分别返回不同对象 id（embedding_id），与后续假召回按 embedding_id 匹配一致
        fake_collection.data.insert.side_effect = ["obj-id-1", "obj-id-2"]
        monkeypatch.setattr(
            service.vector_database_service, "episodic_memory_collection",
            fake_collection,
        )
        monkeypatch.setattr(service.embeddings_service, "embeddings", FakeEmbeddings())

        # 写入两条经历（写侧管道复用 FakeEmbeddings）
        episodes = []
        for content, importance in [
            ("用户正在准备搬家到北京，已完成房源搜索", 0.9),
            ("用户偏好用表格对比方案", 0.6),
        ]:
            ep = await service.write_episode(
                app_id=app_id, user_id=user_id,
                content=content, importance=importance,
            )
            episodes.append(ep)

        # 双路召回：monkeypatch 返回固定排名（向量路命中第二条，BM25 路命中第一条）
        # 注意：召回返回的 key 是 embedding_id（Weaviate 对象 id），不是 EpisodicMemory.id
        async def fake_vector(app_id, user_id, query, k):
            return [("obj-id-2", 0.8)]

        async def fake_bm25(app_id, user_id, query, k):
            return [("obj-id-1", 1.2)]

        monkeypatch.setattr(service, "_recall_vector", fake_vector)
        monkeypatch.setattr(service, "_recall_bm25", fake_bm25)

        results = await service.search_episodes(app_id, user_id, "北京搬家")

        assert len(results) >= 1
        assert all(isinstance(r, type(episodes[0])) for r in results)
        assert len(results) == 2, "两条经历各被一路命中，应返回 2 条"
        assert results[0].id == episodes[0].id, "importance 0.9 的经历应排在前面（加权排序）"
