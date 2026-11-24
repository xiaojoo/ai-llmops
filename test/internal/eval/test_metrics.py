import json

import pytest

from internal.eval.metrics import hit_at_k, mrr, percentile, score_agent, score_rag
from internal.eval.runner import load_dataset, run_dataset


def test_percentile_and_retrieval_metrics():
    assert percentile([10, 20, 30, 40], 0.95) == pytest.approx(38.5)
    hits = [{"id": "a"}, {"id": "b"}]
    assert hit_at_k(["b"], hits, 1) == 0
    assert hit_at_k(["b"], hits, 2) == 1
    assert mrr(["b"], hits) == 0.5


def test_agent_and_rag_scoring():
    passed, failures = score_agent(
        {"answer": "向量数据库存储向量", "tools": ["search"], "terminal": True, "had_error": False},
        {"contains": ["向量"], "tools": ["search"]},
    )
    assert passed and not failures
    passed, failures = score_rag(
        {"hits": [{"id": "a"}, {"id": "b"}]},
        {"segment_ids": ["b"], "k": 2, "min_mrr": 0.4},
    )
    assert passed and not failures


def test_load_json_dataset(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"target": "agent", "cases": []}), encoding="utf-8")
    assert load_dataset(path)["cases"] == []


@pytest.mark.asyncio
async def test_run_dataset_threshold_gate(monkeypatch):
    async def fake_agent(_client, _headers, case):
        return {
            "answer": "ok",
            "events": ["agent_message", "agent_end"],
            "tools": [],
            "latency_ms": 10,
            "total_tokens": 3,
            "total_cost": 0.1,
            "tool_errors": 0,
            "terminal": True,
            "had_error": False,
        }

    monkeypatch.setattr("internal.eval.runner.run_agent_case", fake_agent)
    dataset = {
        "target": "agent",
        "cases": [{"id": "ok", "app_id": "app", "input": {"query": "q"}, "expect": {"contains": ["ok"]}}],
        "thresholds": {"min_success_rate": 1, "max_p95_latency_ms": 100},
    }
    report = await run_dataset(None, {}, dataset)
    assert report["summary"]["passed"] == 1
    assert report["threshold_failures"] == []

    dataset["thresholds"]["min_success_rate"] = 1.1
    report = await run_dataset(None, {}, dataset)
    assert report["threshold_failures"]

    async def fake_error(_client, _headers, _case):
        return {"answer": "ok", "events": ["error"], "tools": [], "latency_ms": 1, "terminal": True, "had_error": True}

    monkeypatch.setattr("internal.eval.runner.run_agent_case", fake_error)
    report = await run_dataset(None, {}, dataset)
    assert report["summary"]["passed"] == 0

    async def fake_truncated(_client, _headers, _case):
        return {
            "answer": "ok",
            "events": ["agent_message"],
            "tools": [],
            "latency_ms": 1,
            "terminal": False,
            "had_error": False,
        }

    monkeypatch.setattr("internal.eval.runner.run_agent_case", fake_truncated)
    report = await run_dataset(None, {}, dataset)
    assert report["summary"]["passed"] == 0

    with pytest.raises(ValueError, match="不能为空"):
        await run_dataset(None, {}, {"target": "agent", "cases": []})
