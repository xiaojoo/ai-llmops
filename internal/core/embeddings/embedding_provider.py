#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : embedding_provider.py

Embedding 提供者抽象层：支持本地模型（bge-m3 等）与 API 服务（DashScope 等）两种实现，
通过环境变量 EMBEDDING_PROVIDER 切换（local | api）。
"""
import functools
import os

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field

from internal.config.settings import get_settings

# 默认本地模型名（离线推理时从本地缓存加载；与存量向量数据维度保持一致）
DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-zh"
# 默认 API 模型名（DashScope）
DEFAULT_API_EMBEDDING_MODEL = "text-embedding-v3"


class LocalEmbeddingProvider(Embeddings, BaseModel):
    """本地 HuggingFace 模型嵌入提供者（离线推理）"""

    model_name: str = Field(default=DEFAULT_LOCAL_EMBEDDING_MODEL)
    device: str = Field(default="cpu")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from langchain_huggingface import HuggingFaceEmbeddings

        # 本地模型：优先使用环境变量/参数指定的路径；其次回退到
        # internal/core/embeddings/<模型名> 目录（兼容原有离线部署结构），
        # 最后交给 HuggingFace 缓存加载。
        model_path = self.model_name
        if os.path.isdir(model_path):
            model_path = os.path.abspath(model_path)
        else:
            legacy_dir = os.path.join(
                os.getcwd(), "internal", "core", "embeddings", self.model_name.split("/")[-1]
            )
            if os.path.isdir(legacy_dir) and os.listdir(legacy_dir):
                model_path = legacy_dir

        self._embeddings = HuggingFaceEmbeddings(
            model_name=model_path,
            model_kwargs={"device": self.device},
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)


class ApiEmbeddingProvider(Embeddings, BaseModel):
    """DashScope API 嵌入提供者（text-embedding-v3 等）"""

    model_name: str = Field(default=DEFAULT_API_EMBEDDING_MODEL)
    api_key: str = Field(default="")
    api_base: str = Field(default="")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        import dashscope

        if not self.api_key:
            raise RuntimeError(
                "使用 API 嵌入服务时需配置 EMBEDDING_API_KEY 环境变量"
            )
        dashscope.api_key = self.api_key
        if self.api_base:
            # dashscope 的 base 要求以 /api/v1 结尾，兼容配置里省略该后缀的写法
            base = self.api_base.rstrip("/")
            dashscope.base_http_api_url = base if base.endswith("/api/v1") else base + "/api/v1"

    def _call(self, texts: list[str]) -> list[list[float]]:
        import dashscope

        response = dashscope.TextEmbedding.call(
            model=self.model_name,
            input=texts,
        )
        if response.status_code != 200:
            raise RuntimeError(f"嵌入服务调用失败: {response.code} {response.message}")
        return [item["embedding"] for item in response.output["embeddings"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # DashScope 单次最大 25 条文本，分批调用
        batch_size = 25
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            results.extend(self._call(texts[i:i + batch_size]))
        return results

    def embed_query(self, text: str) -> list[float]:
        return self._call([text])[0]


@functools.lru_cache(maxsize=None)
def create_embedding_provider() -> Embeddings:
    """根据环境变量 EMBEDDING_PROVIDER 创建对应的嵌入提供者

    OOM 修复（附注⑳）：进程级单例缓存——每次调用新建会导致本地模型（bge-small-zh）
    反复加载到内存且 GC 不回收 torch 权重（每实例 100MB+）。而每次知识库检索
    （请求/工作流节点/工具桥接）都会经 create_retrieval_service → create_embeddings_service
    调用本函数，无缓存时 uvicorn 进程内存只增不减直至爆满。
    配置经 lifespan apply_to_env 注入后固定，首调缓存安全。
    """
    provider_name = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()

    if provider_name == "api":
        return ApiEmbeddingProvider(
            model_name=os.getenv("EMBEDDING_MODEL", DEFAULT_API_EMBEDDING_MODEL),
            api_key=os.getenv("EMBEDDING_API_KEY", ""),
            api_base=os.getenv("EMBEDDING_API_BASE", ""),
        )

    if provider_name == "local":
        return LocalEmbeddingProvider(
            model_name=os.getenv("EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL),
            # 设备读取统一走 settings（DB 侧 system_config 注入的 EMBEDDING_DEVICE
            # 经 apply_to_env 进 os.environ，get_settings() 首次调用前仍生效）
            device=get_settings().embedding_device,
        )

    raise RuntimeError(
        f"不支持的 EMBEDDING_PROVIDER: {provider_name}，可选值为 local / api"
    )
