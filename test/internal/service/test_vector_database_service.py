#!/usr/bin/env python
"""VectorDatabaseService.episodic_memory_collection 测试：

回归验证 WeaviateClosedClientError 修复——Collection 句柄不可跨请求缓存
（旧 FlaskWeaviate 在 app context teardown 时 close client），必须每次从当前 client 现取。

转 async（flask/injector 移除，直接构造服务）
"""
import pytest
from unittest.mock import MagicMock, patch

from internal.service.vector_database_service import VectorDatabaseService
from internal.service.embeddings_service import EmbeddingsService


class TestEpisodicMemoryCollection:
    def test_returns_injected_value_when_set(self):
        """setter 注入（测试/替换场景）应优先返回注入对象"""
        embeddings_svc = MagicMock(spec=EmbeddingsService)
        service = VectorDatabaseService(embeddings_service=embeddings_svc)
        fake = MagicMock()
        service.episodic_memory_collection = fake
        try:
            assert service.episodic_memory_collection is fake
        finally:
            service.__dict__.pop("_episodic_memory_collection", None)

    def test_does_not_cache_collection_handle_across_access(self, monkeypatch):
        """未注入时每次访问都应从当前 client 现取句柄（不缓存），避免绑定已关闭 client"""
        embeddings_svc = MagicMock(spec=EmbeddingsService)
        service = VectorDatabaseService(embeddings_service=embeddings_svc)
        service.__dict__.pop("_episodic_memory_created", None)
        service.__dict__.pop("_episodic_memory_collection", None)

        client = MagicMock()
        client.collections.list_all.return_value = {"EpisodicMemory": object()}
        client.collections.get.return_value = MagicMock()

        # Patch get_weaviate_client to return our mock
        with patch("internal.service.vector_database_service.get_weaviate_client", return_value=client):
            service.episodic_memory_collection
            service.episodic_memory_collection

        assert client.collections.get.call_count == 2, \
            f"Collection 句柄不应被缓存，两次访问应两次现取（实际 {client.collections.get.call_count} 次）"
        service.__dict__.pop("_episodic_memory_created", None)
        service.__dict__.pop("_episodic_memory_collection", None)
