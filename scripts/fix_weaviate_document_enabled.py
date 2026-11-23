#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : fix_weaviate_document_enabled.py

存量数据修复脚本：把 Weaviate 中 document_enabled 字段与 PostgreSQL 中
Document.enabled 状态同步。

背景：旧版索引代码写入 Weaviate 时从未设置 document_enabled=True，
导致新检索器（按 document_enabled 过滤）在存量数据上返回 0 结果。

用法（项目根目录）：
    python scripts/fix_weaviate_document_enabled.py [--dry-run]

--dry-run：只统计将要更新的对象数，不实际执行。
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.CRITICAL)

from internal.model import Document


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 Weaviate document_enabled 与数据库状态")
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    args = parser.parse_args()

    import dotenv
    dotenv.load_dotenv()

    from sqlalchemy import select

    from app.http.app import app
    from app.http.module import injector
    from internal.service.vector_database_service import VectorDatabaseService

    with app.app_context():
        db = app.extensions["sqlalchemy"]
        vdb = injector.get(VectorDatabaseService)
        collection = vdb.collection

        # 1、查询所有文档的启用状态
        documents = db.session.execute(select(Document.id, Document.dataset_id, Document.enabled)).fetchall()
        print(f"数据库文档总数: {len(documents)}")

        # 按 dataset_id 聚合，便于批量过滤
        from collections import defaultdict
        dataset_docs = defaultdict(list)
        for doc_id, dataset_id, enabled in documents:
            dataset_docs[str(dataset_id)].append((str(doc_id), enabled))

        total_updated = 0
        total_checked = 0

        # 2、按知识库遍历，更新对应对象的 document_enabled
        for dataset_id, doc_list in dataset_docs.items():
            from weaviate.classes.query import Filter
            # 该知识库下所有对象
            objects = collection.query.fetch_objects(
                filters=Filter.by_property("dataset_id").contains_any([dataset_id]),
                limit=10000,
            ).objects
            for obj in objects:
                total_checked += 1
                props = obj.properties
                doc_id = str(props.get("document_id", ""))
                segment_enabled = bool(props.get("segment_enabled", False))

                # 找到该片段所属文档的启用状态
                doc_enabled = None
                for d_id, enabled in doc_list:
                    if d_id == doc_id:
                        doc_enabled = enabled
                        break

                if doc_enabled is None:
                    continue

                new_value = bool(doc_enabled) and segment_enabled
                if props.get("document_enabled") != new_value:
                    total_updated += 1
                    if not args.dry_run:
                        collection.data.update(
                            uuid=obj.uuid,
                            properties={"document_enabled": new_value},
                        )

        print(f"检查对象数: {total_checked}")
        print(f"需更新对象数: {total_updated}")
        if args.dry_run:
            print("dry-run 模式，未实际执行更新。去掉 --dry-run 后执行。")
        else:
            print("完成。")


if __name__ == "__main__":
    main()
