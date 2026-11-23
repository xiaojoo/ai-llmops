#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : rrf.py

RRF（Reciprocal Rank Fusion）融合算法：对多路召回结果按排名融合，
分数与各路分数尺度无关，比固定加权更稳定。

融合对象需要提供稳定可哈希的身份标识：LangChain Document 使用
metadata["segment_id"]（或 node_id）作为 key。
"""
from collections.abc import Callable, Iterable
from typing import Any

RRF_K = 60  # 标准 RRF 常数


def _default_key(item: Any) -> Any:
    """默认取 Document 的 segment_id 作为身份标识"""
    return item.metadata.get("segment_id") or item.metadata.get("node_id")


def rrf_fusion(
        ranked_lists: Iterable[Iterable[Any]],
        k: int = RRF_K,
        key_func: Callable[[Any], Any] = _default_key,
) -> list[tuple[Any, float]]:
    """融合多路排名列表，返回 [(item, rrf_score), ...]，按分数降序排列。

    - key_func 用于提取每个 item 的稳定身份（默认取 Document.metadata 的
      segment_id/node_id）；同一路内重复元素只计第一次出现。
    """
    scores: dict[Any, float] = {}
    items: dict[Any, Any] = {}

    for ranked in ranked_lists:
        seen = set()
        for rank, item in enumerate(ranked, start=1):
            key = key_func(item)
            if key is None:
                continue
            if key in seen:
                continue
            seen.add(key)
            items[key] = item
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    return sorted(
        ((items[key], score) for key, score in scores.items()),
        key=lambda pair: pair[1],
        reverse=True,
    )
