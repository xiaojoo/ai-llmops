from __future__ import annotations

import math
import re
from typing import Any


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def hit_at_k(expected: list[str], hits: list[dict[str, Any]], k: int) -> float:
    if not expected:
        return 1.0
    actual = {str(hit.get("id") or hit.get("segment_id") or "") for hit in hits[:k]}
    return 1.0 if any(item in actual for item in expected) else 0.0


def mrr(expected: list[str], hits: list[dict[str, Any]]) -> float:
    if not expected:
        return 1.0
    for index, hit in enumerate(hits, start=1):
        identity = str(hit.get("id") or hit.get("segment_id") or "")
        if identity in expected:
            return 1.0 / index
    return 0.0


def score_agent(result: dict[str, Any], expect: dict[str, Any]) -> tuple[bool, list[str]]:
    answer = str(result.get("answer") or "")
    failures: list[str] = []
    if not result.get("terminal"):
        failures.append("Agent 流未正常结束")
    if result.get("had_error"):
        failures.append("Agent 流包含 error 事件")
    for keyword in expect.get("contains") or []:
        if keyword not in answer:
            failures.append(f"缺少关键词: {keyword}")
    pattern = expect.get("regex")
    if pattern and re.search(pattern, answer, re.DOTALL) is None:
        failures.append(f"未匹配正则: {pattern}")
    used_tools = set(result.get("tools") or [])
    for tool in expect.get("tools") or []:
        if tool not in used_tools:
            failures.append(f"未调用工具: {tool}")
    return not failures, failures


def score_rag(result: dict[str, Any], expect: dict[str, Any]) -> tuple[bool, list[str]]:
    hits = result.get("hits") or []
    expected = expect.get("segment_ids") or []
    k = int(expect.get("k") or 5)
    hit = hit_at_k(expected, hits, k)
    reciprocal = mrr(expected, hits)
    minimum_hit = float(expect.get("min_hit_at_k", 1.0))
    minimum_mrr = float(expect.get("min_mrr", 0.0))
    failures = []
    if hit < minimum_hit:
        failures.append(f"hit@{k}={hit:.2f} 低于 {minimum_hit:.2f}")
    if reciprocal < minimum_mrr:
        failures.append(f"MRR={reciprocal:.2f} 低于 {minimum_mrr:.2f}")
    return not failures, failures
