from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from .metrics import percentile, score_agent, score_rag


def load_dataset(path: str | Path) -> dict[str, Any]:
    content = Path(path).read_text(encoding="utf-8")
    data = json.loads(content) if str(path).lower().endswith(".json") else yaml.safe_load(content)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("评测数据集必须是包含 cases 数组的对象")
    return data


async def run_agent_case(client: httpx.AsyncClient, headers: dict[str, str], case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    answer: list[str] = []
    events: list[str] = []
    tools: list[str] = []
    stats: dict[str, dict[str, Any]] = {}
    trace_id = ""
    run_id = ""
    tool_errors = 0
    terminal = False
    had_error = False
    buffer = ""
    async with client.stream(
        "POST",
        f"/apps/{case['app_id']}/conversations",
        json={"query": case["input"]["query"], "conversation_id": ""},
        headers={**headers, "Accept": "text/event-stream"},
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                event = ""
                data: dict[str, Any] = {}
                for line in raw.splitlines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        try:
                            data = json.loads(line[5:].strip())
                        except ValueError:
                            data = {}
                if not event or event == "ping":
                    continue
                events.append(event)
                if event in {"agent_end", "stop", "timeout", "error"}:
                    terminal = True
                if event == "error":
                    had_error = True
                trace_id = trace_id or str(data.get("trace_id") or "")
                run_id = run_id or str(data.get("run_id") or "")
                if event == "agent_message":
                    answer.append(data.get("thought") or data.get("answer") or "")
                if event == "agent_action" and data.get("tool"):
                    tools.append(str(data["tool"]))
                if event == "error" or (
                    event == "agent_action"
                    and str(data.get("observation") or "").startswith("工具执行出错")
                ):
                    tool_errors += 1
                if data.get("id"):
                    stats[str(data["id"])] = data
    return {
        "answer": "".join(answer),
        "events": events,
        "tools": tools,
        "trace_id": trace_id,
        "run_id": run_id,
        "latency_ms": (time.perf_counter() - started) * 1000,
        "total_tokens": sum(int(item.get("total_token_count") or 0) for item in stats.values()),
        "total_cost": sum(float(item.get("total_price") or 0) for item in stats.values()),
        "tool_errors": tool_errors,
        "terminal": terminal,
        "had_error": had_error,
    }


async def run_rag_case(client: httpx.AsyncClient, headers: dict[str, str], case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    response = await client.post(
        f"/datasets/{case['dataset_id']}/hit",
        json=case["input"],
        headers=headers,
    )
    response.raise_for_status()
    body = response.json()
    return {
        "hits": body.get("data") or [],
        "latency_ms": (time.perf_counter() - started) * 1000,
        "trace_id": response.headers.get("x-trace-id", ""),
    }


async def run_dataset(client: httpx.AsyncClient, headers: dict[str, str], dataset: dict[str, Any]) -> dict[str, Any]:
    target = dataset.get("target", "agent")
    if not dataset["cases"]:
        raise ValueError("评测数据集不能为空")
    results = []
    for raw_case in dataset["cases"]:
        case = dict(raw_case)
        if target == "agent" and "app_id" not in case:
            case["app_id"] = dataset.get("app_id")
        if target == "rag" and "dataset_id" not in case:
            case["dataset_id"] = dataset.get("dataset_id")
        try:
            result = await (
                run_agent_case(client, headers, case)
                if target == "agent"
                else run_rag_case(client, headers, case)
            )
            passed, failures = (
                score_agent(result, case.get("expect") or {})
                if target == "agent"
                else score_rag(result, case.get("expect") or {})
            )
            results.append({"id": case.get("id"), "passed": passed, "failures": failures, **result})
        except Exception as exc:
            results.append({"id": case.get("id"), "passed": False, "failures": [str(exc)]})
    latencies = [float(item.get("latency_ms") or 0) for item in results]
    summary = {
        "target": target,
        "cases": len(results),
        "passed": sum(bool(item["passed"]) for item in results),
        "success_rate": sum(bool(item["passed"]) for item in results) / len(results) if results else 0.0,
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in results),
        "total_cost": sum(float(item.get("total_cost") or 0) for item in results),
    }
    if target == "agent":
        summary["tool_errors"] = sum(int(item.get("tool_errors") or 0) for item in results)
        summary["tool_error_rate"] = summary["tool_errors"] / max(1, sum(len(item.get("tools") or []) for item in results))
    thresholds = dataset.get("thresholds") or {}
    failures = []
    if summary["success_rate"] < float(thresholds.get("min_success_rate", 0)):
        failures.append("success_rate 低于阈值")
    if summary["p95_latency_ms"] > float(thresholds.get("max_p95_latency_ms", float("inf"))):
        failures.append("p95_latency_ms 高于阈值")
    if target == "agent" and summary["tool_error_rate"] > float(thresholds.get("max_tool_error_rate", float("inf"))):
        failures.append("tool_error_rate 高于阈值")
    if summary["total_cost"] > float(thresholds.get("max_total_cost", float("inf"))):
        failures.append("total_cost 高于阈值")
    return {"summary": summary, "threshold_failures": failures, "results": results}
