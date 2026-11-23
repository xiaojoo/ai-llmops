#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time   : 2025/12/1 20:47
@Author : sunxiaojie
@File   : embeddings_service.py
"""
import hashlib
from typing import Iterator, Optional, Sequence, Tuple

import tiktoken
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.stores import ByteStore
from redis import Redis

from internal.core.embeddings import create_embedding_provider



class RedisByteStore(ByteStore):
    def __init__(self, client: Redis):
        self.client = client

    def mget(self, keys: Sequence[str]) -> list[Optional[bytes]]:
        return self.client.mget(list(keys))

    def mset(self, key_value_pairs: Sequence[Tuple[str, bytes]]) -> None:
        pipe = self.client.pipeline()
        for key, value in key_value_pairs:
            pipe.set(key, value)
        pipe.execute()

    def mdelete(self, keys: Sequence[str]) -> None:
        self.client.delete(*keys)

    def yield_keys(self, *, prefix: Optional[str] = None) -> Iterator[str]:
        pattern = prefix if prefix else "*"
        for key in self.client.scan_iter(match=pattern):
            yield key.decode("utf-8")


class EmbeddingsService:
    """文本嵌入式模型服务（推理经线程池桥接）"""

    def __init__(self, redis: Redis):
        """构造函数、初始化文本嵌入模型客户端、存储器、缓存客户端"""

        # 1. 按配置创建嵌入提供者（本地 bge-m3 或 DashScope API）
        self._embeddings: Embeddings = create_embedding_provider()

        # 创建带有模型标识的自定义编码器
        namespace = getattr(self._embeddings, "model_name", "embedding")

        def namespaced_sha256_encoder(text: str) -> str:
            full_key = f"{namespace}:{text}"
            return hashlib.sha256(full_key.encode()).hexdigest()

        self._store = RedisByteStore(client=redis)

        self._cache_backed_embeddings = CacheBackedEmbeddings.from_bytes_store(
            self._embeddings,
            self._store,
            key_encoder=namespaced_sha256_encoder,
        )

    @classmethod
    def calculate_token_count(cls, query: str) -> int:
        """计算传入文本的token数"""
        encoding = tiktoken.encoding_for_model("gpt-3.5")
        return len(encoding.encode(query))

    @property
    def store(self) -> RedisByteStore:
        return self._store

    @property
    def embeddings(self) -> Embeddings:
        return self._embeddings

    @embeddings.setter
    def embeddings(self, value: Embeddings) -> None:
        """测试注入用 setter：允许替换嵌入模型实例（monkeypatch 场景）"""
        self._embeddings = value

    @property
    def cache_backed_embeddings(self) -> CacheBackedEmbeddings:
        return self._cache_backed_embeddings
