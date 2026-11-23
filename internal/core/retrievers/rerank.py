#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : rerank.py

Rerank 交叉编码器层：把召回候选（Top N）精排为 Top k。
支持本地模型（bge-reranker-v2-m3）与 DashScope API 两种实现，
通过 RERANK_PROVIDER 环境变量切换（local | api）。
"""
import os

from langchain_core.documents import Document as LCDocument
from pydantic import BaseModel, Field

# 默认本地 reranker 模型名
DEFAULT_LOCAL_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
# 默认 API reranker 模型名（DashScope）
DEFAULT_API_RERANK_MODEL = "gte-rerank"


class Reranker(BaseModel):
    """Rerank 基类：对候选文档按与 query 的相关性重排"""

    model_name: str = Field(default="")
    top_n: int = Field(default=20)

    def rerank(
            self,
            query: str,
            documents: list[LCDocument],
    ) -> list[LCDocument]:
        """返回重排后的文档列表（截断到 top_n）"""
        if not documents:
            return []
        return self._rerank(query, documents)[: self.top_n]

    def _rerank(self, query: str, documents: list[LCDocument]) -> list[LCDocument]:
        raise NotImplementedError


class LocalReranker(Reranker):
    """本地 bge-reranker 交叉编码器"""

    model_name: str = Field(default=DEFAULT_LOCAL_RERANK_MODEL)
    batch_size: int = Field(default=32)

    def _rerank(self, query: str, documents: list[LCDocument]) -> list[LCDocument]:
        from sentence_transformers import CrossEncoder

        # 本地模型目录优先（兼容离线部署），否则走 HuggingFace 缓存
        model_path = self.model_name
        if os.path.isdir(model_path):
            model_path = os.path.abspath(model_path)
        else:
            legacy_dir = os.path.join(
                os.getcwd(), "internal", "core", "rerank", self.model_name.split("/")[-1]
            )
            if os.path.isdir(legacy_dir) and os.listdir(legacy_dir):
                model_path = legacy_dir

        cross_encoder = CrossEncoder(model_path)
        pairs = [[query, doc.page_content] for doc in documents]
        scores = cross_encoder.predict(pairs, batch_size=self.batch_size)

        ranked = sorted(
            zip(documents, scores),
            key=lambda pair: pair[1],
            reverse=True,
        )
        for doc, score in ranked:
            doc.metadata["rerank_score"] = float(score)
        return [doc for doc, _ in ranked]


class ApiReranker(Reranker):
    """DashScope API rerank（gte-rerank 等）"""

    model_name: str = Field(default=DEFAULT_API_RERANK_MODEL)
    api_key: str = Field(default="")
    api_base: str = Field(default="")

    def _rerank(self, query: str, documents: list[LCDocument]) -> list[LCDocument]:
        import dashscope

        if not self.api_key:
            raise RuntimeError("使用 API rerank 服务时需配置 RERANK_API_KEY 环境变量")
        dashscope.api_key = self.api_key
        if self.api_base:
            # dashscope 的 base 要求以 /api/v1 结尾，兼容配置里省略该后缀的写法
            base = self.api_base.rstrip("/")
            dashscope.base_http_api_url = base if base.endswith("/api/v1") else base + "/api/v1"

        response = dashscope.TextReRank.call(
            model=self.model_name,
            query=query,
            documents=[doc.page_content for doc in documents],
        )
        if response.status_code != 200:
            raise RuntimeError(f"rerank 服务调用失败: {response.code} {response.message}")

        results = sorted(
            response.output["results"],
            key=lambda item: item["relevance_score"],
            reverse=True,
        )
        ranked = []
        for item in results:
            index = item["index"]
            doc = documents[index]
            doc.metadata["rerank_score"] = float(item["relevance_score"])
            ranked.append(doc)
        return ranked


def create_reranker(
        enable: bool = False,
        top_n: int = 20,
) -> Reranker | None:
    """按环境变量 RERANK_PROVIDER 创建 reranker；未启用或未配置时返回 None"""
    if not enable:
        return None

    provider_name = os.getenv("RERANK_PROVIDER", "local").strip().lower()
    if provider_name == "api":
        return ApiReranker(
            model_name=os.getenv("RERANK_MODEL", DEFAULT_API_RERANK_MODEL),
            api_key=os.getenv("RERANK_API_KEY", ""),
            api_base=os.getenv("RERANK_API_BASE", ""),
            top_n=top_n,
        )
    return LocalReranker(
        model_name=os.getenv("RERANK_MODEL", DEFAULT_LOCAL_RERANK_MODEL),
        top_n=top_n,
    )
