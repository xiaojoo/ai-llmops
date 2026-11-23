#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : eval_chat_history.py

基于历史对话文档的召回评估：
- 从 _chat_history.md 解析每轮对话的用户问题作为测试 query
- 期望命中：包含该问题文本的片段（该轮对话内容）
- 对 semantic / full_text / hybrid 三种策略，在 top-k=1/3/5/10 下统计：
    hit_rate（命中率）：期望片段出现在结果中的 query 占比
    recall（召回率）：命中的期望片段数 / 期望片段总数（每个 query 期望 1 个片段）
    mrr（平均倒数排名）

用法：
    python scripts/eval_chat_history.py [--dataset-id <uuid>] [--doc _chat_history.md]
"""
import argparse
import re
import sys
from pathlib import Path

# 兼容 Windows GBK 控制台输出中文
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATASET_ID = "be2f9b05-805d-46d2-a01b-b2292f1b7da5"
ACCOUNT_ID = "b63ccd33-8653-4535-a6eb-9db7517e42ec"


def parse_turns(md_path: Path) -> list[tuple[str, str]]:
    """解析对话文档，返回 [(用户问题, 助手回复)] 列表"""
    text = md_path.read_text(encoding="utf-8")
    # 按 "## 第 N 轮对话" 切块
    blocks = re.split(r"## 第 \d+ 轮对话", text)
    turns = []
    for block in blocks[1:]:
        user_match = re.search(r"### 用户\s*\n(.*?)\n### 助手", block, re.DOTALL)
        asst_match = re.search(r"### 助手\s*\n(.*)$", block, re.DOTALL)
        if user_match and asst_match:
            user_q = user_match.group(1).strip()
            asst_a = asst_match.group(1).strip()
            if user_q and asst_a:
                turns.append((user_q, asst_a))
    return turns


def main() -> None:
    parser = argparse.ArgumentParser(description="历史对话召回评估")
    parser.add_argument("--dataset-id", default=DATASET_ID)
    parser.add_argument("--doc", default="scripts/_chat_history.md")
    parser.add_argument("--top-ks", default="1,3,5,10", help="逗号分隔的 top-k 列表")
    args = parser.parse_args()

    md_path = Path(args.doc)
    turns = parse_turns(md_path)
    print(f"解析到 {len(turns)} 轮对话（有用户问题+助手回复）")

    import logging
    logging.disable(logging.CRITICAL)
    import dotenv
    dotenv.load_dotenv()
    from sqlalchemy import select

    from app.http.app import app
    from internal.model import Segment

    top_ks = [int(x) for x in args.top_ks.split(",")]

    with app.app_context():
        from app.http.module import injector
        from internal.service.retrieval_service import RetrievalService
        rs = injector.get(RetrievalService)
        db = app.extensions["sqlalchemy"]

        # 1、加载对话文档全部片段（期望片段 = 包含用户问题文本的片段）
        select(Segment.id, Segment.content).where(
            Segment.dataset_id == args.dataset_id,
            Segment.document_id.in_(select(Segment.document_id).where(
                Segment.dataset_id == args.dataset_id,
            )),
        )
        # 简化：直接按内容匹配
        segments = db.session.execute(
            select(Segment.id, Segment.content).where(Segment.dataset_id == args.dataset_id)
        ).fetchall()
        print(f"知识库片段总数: {len(segments)}")

        # 2、构建每个 query 的期望片段集合（包含用户问题文本的片段 id）
        queries = []
        for user_q, asst_a in turns:
            # 期望片段：内容包含用户问题前 8 个字符（降低跨块截断导致的误判）
            q_key = user_q[:8].strip()
            expected = set()
            for seg_id, content in segments:
                if q_key and q_key in content:
                    expected.add(str(seg_id))
            queries.append((user_q, expected))

        # 过滤有期望片段的 query
        valid_queries = [(q, e) for q, e in queries if e]
        print(f"有效测试 query（有期望片段）: {len(valid_queries)}/{len(queries)}\n")

        # 3、逐策略评估
        strategies = ["semantic", "full_text", "hybrid"]
        for strategy in strategies:
            print(f"===== 策略: {strategy} =====")
            for k in top_ks:
                hit = 0
                mrr_sum = 0.0
                for q, expected in valid_queries:
                    docs = rs.search_in_datasets(
                        dataset_ids=[args.dataset_id],
                        query=q,
                        retrieval_strategy=strategy,
                        k=k,
                        score=0.0,
                        account_id=ACCOUNT_ID,
                    )
                    ranked_ids = [d.metadata.get("segment_id") for d in docs if d.metadata.get("segment_id")]
                    # 命中：期望片段在结果中
                    found = False
                    for rank, sid in enumerate(ranked_ids, 1):
                        if sid in expected:
                            found = True
                            mrr_sum += 1.0 / rank
                            break
                    if found:
                        hit += 1
                hit_rate = hit / len(valid_queries)
                mrr = mrr_sum / len(valid_queries)
                print(f"  top-{k:<3} hit_rate={hit_rate:.3f} ({hit}/{len(valid_queries)})  MRR={mrr:.3f}")
            print()

        # 4、hybrid 策略下逐 query 明细（top-5）
        print("===== hybrid top-5 逐 query 明细 =====")
        for idx, (q, expected) in enumerate(valid_queries, 1):
            docs = rs.search_in_datasets(
                dataset_ids=[args.dataset_id],
                query=q,
                retrieval_strategy="hybrid",
                k=5,
                score=0.0,
                account_id=ACCOUNT_ID,
            )
            ranked = [d.metadata.get("segment_id") for d in docs if d.metadata.get("segment_id")]
            hit_pos = next((i + 1 for i, sid in enumerate(ranked) if sid in expected), None)
            q_short = q[:28].replace("\n", " ")
            mark = "HIT" if hit_pos else "miss"
            print(f"  [{idx:>2}] {mark:<5} {'pos=' + str(hit_pos) if hit_pos else ''} | {q_short}")


if __name__ == "__main__":
    main()
