#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/1 21:31
@Author : sunxiaojie
@File   : vector_database_service.py
"""

from dataclasses import dataclass

from langchain_core.vectorstores import VectorStoreRetriever
from langchain_weaviate import WeaviateVectorStore
from weaviate.classes.config import Configure, DataType, Property
from weaviate.collections import Collection

from internal.extensions.weaviate import get_weaviate_client

from .embeddings_service import EmbeddingsService

# 向量数据库的集合名字
COLLECTION_NAME = 'Dataset'

# 情景记忆向量集合名（与 Dataset 集合分离，按 user_id 过滤隔离）
EPISODIC_MEMORY_COLLECTION = "EpisodicMemory"


@dataclass
class VectorDatabaseService:
    """向量数据库服务"""
    embeddings_service: EmbeddingsService

    @property
    def vector_store(self) -> WeaviateVectorStore:
        return WeaviateVectorStore(
            client=get_weaviate_client(),
            index_name=COLLECTION_NAME,
            text_key="text",
            embedding=self.embeddings_service.cache_backed_embeddings,
        )

    def get_retriever(self) -> VectorStoreRetriever:
        """获取检索器"""
        return self.vector_store.as_retriever()

    @property
    def collection(self) -> Collection:
        return get_weaviate_client().collections.get(COLLECTION_NAME)

    @property
    def episodic_memory_collection(self) -> Collection:
        """获取（必要时创建）情景记忆 Weaviate 集合。

        注意：Weaviate 客户端为模块级单例（internal/extensions/weaviate.py），
        但【不能缓存 Collection 句柄】——避免绑定过期/重建的 client 导致
        WeaviateClosedClientError。这里只缓存"集合已创建"标志（跨请求安全），
        句柄每次从当前 client 现取。
        """
        injected = getattr(self, "_episodic_memory_collection", None)
        if injected is not None:
            return injected

        client = get_weaviate_client()
        if not getattr(self, "_episodic_memory_created", False):
            if EPISODIC_MEMORY_COLLECTION not in client.collections.list_all():
                client.collections.create(
                    name=EPISODIC_MEMORY_COLLECTION,
                    vector_config=Configure.Vectors.self_provided(),
                    properties=[
                        Property(name="app_id", data_type=DataType.TEXT),
                        Property(name="user_id", data_type=DataType.TEXT),
                        Property(name="content", data_type=DataType.TEXT),
                        Property(name="importance", data_type=DataType.NUMBER),
                        Property(name="created_at", data_type=DataType.NUMBER),
                    ],
                )
            self._episodic_memory_created = True
        return client.collections.get(EPISODIC_MEMORY_COLLECTION)

    @episodic_memory_collection.setter
    def episodic_memory_collection(self, value: Collection) -> None:
        """测试注入用 setter：允许替换集合对象（monkeypatch 场景）"""
        self._episodic_memory_collection = value
