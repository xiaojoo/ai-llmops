#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import dotenv
import httpx
import psycopg

dotenv.load_dotenv()

from internal.eval.runner import load_dataset, run_dataset
from internal.service import JwtService


def _account_id() -> str:
    parts = urlsplit(os.environ["SQLALCHEMY_DATABASE_URI"])
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    with psycopg.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
        client_encoding=query.get("client_encoding", "utf8"),
        options=query.get("options", ""),
        autocommit=True,
    ) as conn:
        return str(conn.execute("select id from llmops.account order by created_at limit 1").fetchone()[0])


async def _run(args) -> int:
    dataset = load_dataset(args.dataset)
    token = JwtService.generate_token({
        "sub": _account_id(),
        "iss": "llmops",
        "exp": int(time.time()) + 1800,
    })
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=args.base_url, timeout=httpx.Timeout(30, read=300)) as client:
        report = await run_dataset(client, headers, dataset)
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if report["threshold_failures"]:
        print("阈值未通过: " + "; ".join(report["threshold_failures"]), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Agent/RAG 评测数据集")
    parser.add_argument("dataset")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"评测配置或基础设施错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
