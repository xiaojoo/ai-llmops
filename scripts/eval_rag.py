#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : eval_rag.py

RAG 检索质量评估脚本：对测试集（query + 期望 segment_id）计算
各检索策略的 hit_rate 与 MRR，量化每次改动对检索质量的影响。

用法（在项目根目录运行）：
    python scripts/eval_rag.py --dataset-id <uuid> --test-set tests/rag_test_set.json
    python scripts/eval_rag.py --dataset-id <uuid> --test-set tests/rag_test_set.json --rerank

测试集 JSON 格式：
    [
        {"query": "如何配置数据库连接池？", "expected_segment_ids": ["uuid1", "uuid2"]},
        ...
    ]

输出：semantic / full_text / hybrid 三路策略的 hit@k 与 MRR 对比表。
"""
import argparse
import json
import os
import sys
from pathlib import Path

# 允许从项目根目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("FLASK_ENV", "development")


def load_app():
    """加载 Flask 应用与依赖注入容器"""
    from app.http.app import app
    from app.http.module import injector
    from internal.service import RetrievalService
    return app, injector.get(RetrievalService)


def hit_rate(ranked_ids: list[str], expected_ids: set[str], k: int = 4) -> bool:
    """命中率：期望片段是否出现在前 k 个结果中"""
    return bool(expected_ids.intersection(ranked_ids[:k]))


def mrr(ranked_ids: list[str], expected_ids: set[str]) -> float:
    """MRR：第一个命中片段的倒数排名，未命中为 0"""
    for rank, segment_id in enumerate(ranked_ids, start=1):
        if segment_id in expected_ids:
            return 1.0 / rank
    return 0.0


def evaluate_strategy(retrieval_service, app, dataset_id: str, test_set: list[dict],
                      strategy: str, k: int, rerank_enable: bool = False) -> dict:
    """对指定检索策略执行评估，返回指标"""
    total_hit = 0
    total_mrr = 0.0

    with app.app_context():
        for case in test_set:
            query = case["query"]
            expected = set(case["expected_segment_ids"])

            documents = retrieval_service.search_in_datasets(
                dataset_ids=[dataset_id],
                query=query,
                retrieval_strategy=strategy,
                k=k,
                account_id=None,  # 评估脚本不校验账号权限
                rerank_enable=rerank_enable,
            )
            ranked_ids = [doc.metadata.get("segment_id") for doc in documents if doc.metadata.get("segment_id")]

            total_hit += 1 if hit_rate(ranked_ids, expected, k) else 0
            total_mrr += mrr(ranked_ids, expected)

    count = len(test_set)
    return {
        "strategy": strategy,
        "hit_rate": round(total_hit / count, 4) if count else 0,
        "mrr": round(total_mrr / count, 4) if count else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索质量评估")
    parser.add_argument("--dataset-id", required=True, help="知识库 id（UUID）")
    parser.add_argument("--test-set", required=True, help="测试集 JSON 文件路径")
    parser.add_argument("--k", type=int, default=4, help="Top-k（默认 4）")
    parser.add_argument("--rerank", action="store_true", help="启用 rerank（需要已配置 reranker）")
    args = parser.parse_args()

    test_set_path = Path(args.test_set)
    if not test_set_path.exists():
        print(f"测试集不存在: {test_set_path}", file=sys.stderr)
        sys.exit(1)

    with open(test_set_path, encoding="utf-8") as f:
        test_set = json.load(f)

    if not isinstance(test_set, list) or len(test_set) == 0:
        print("测试集为空或格式错误", file=sys.stderr)
        sys.exit(1)

    print(f"测试集: {test_set_path} ({len(test_set)} 条)")
    print(f"Top-k: {args.k} | rerank: {args.rerank}\n")

    app, retrieval_service = load_app()

    results = []
    for strategy in ["semantic", "full_text", "hybrid"]:
        result = evaluate_strategy(
            retrieval_service, app, args.dataset_id, test_set,
            strategy=strategy, k=args.k, rerank_enable=args.rerank,
        )
        results.append(result)
        print(f"  {result['strategy']:<10} hit_rate={result['hit_rate']:.4f}  MRR={result['mrr']:.4f}")

    print("\n完成。数值越高越好；对比各策略可定位召回瓶颈。")


if __name__ == "__main__":
    main()
