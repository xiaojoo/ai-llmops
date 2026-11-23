#!/usr/bin/env python
"""
@Time    : 2026/3/23 1:01
@Author  : sunxiaojie
@File    : weaviate_vector_service.py
"""

from dataclasses import dataclass
from uuid import UUID

import weaviate.classes as wvc
from redis import Redis
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from anyio import to_thread
from starlette.concurrency import run_in_threadpool
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.collections import Collection

from internal.exception import ForbiddenException, NotFoundException
from internal.extensions.weaviate import get_weaviate_client
from internal.model import Account, Dataset, Document

from .base_service import BaseService
from .embeddings_service import EmbeddingsService

COLLECTION_NAME = "Dataset"
# Collection 列表缓存 key 与 TTL（秒）：避免每次进页面实时连接 Weaviate
COLLECTIONS_CACHE_KEY = "weaviate:collections"
COLLECTIONS_CACHE_TTL = 60


@dataclass
class WeaviateVectorService(BaseService):
    """Weaviate 向量召回 / 同步 / 元数据查询服务（weaviate 同步客户端经 run_in_threadpool 桥接）"""
    db: AsyncSession
    embeddings_service: EmbeddingsService
    redis_client: Redis

    @property
    def collection(self) -> Collection:
        """获取 Weaviate Collection 对象"""
        return get_weaviate_client().collections.get(COLLECTION_NAME)

    async def recall(
            self,
            dataset_id: str | UUID,
            query: str,
            top_k: int = 5,
            score_threshold: float = 0.0,
            document_id: str | UUID | None = None,
    ) -> list[dict]:
        """向量召回：对 query 进行语义检索，返回 top_k 个相似分段。

        可传 document_id 限定在某个文档内召回；不传则按 dataset_id 全库召回。
        embeddings + weaviate 同步调用经 run_in_threadpool 桥接。
        """
        # 1. 将 query 编码为向量（asyncio.to_thread 线程池桥接，避免跨 loop 死锁）
        import asyncio
        query_vector = await asyncio.to_thread(
            self.embeddings_service.embeddings.embed_query, query
        )

        # 2. 构建过滤条件
        filters = Filter.by_property("dataset_id").equal(str(dataset_id))
        if document_id:
            filters = filters & Filter.by_property("document_id").equal(str(document_id))

        # 3. 向量检索（weaviate 同步客户端桥接）
        response = await run_in_threadpool(
            self.collection.query.near_vector,
            near_vector=query_vector,
            limit=top_k,
            filters=filters,
            return_metadata=MetadataQuery(distance=True),
        )

        # 3. 过滤 & 格式化结果
        results = []
        for obj in response.objects:
            distance = obj.metadata.distance or 1.0
            score = round(1 - distance, 4)
            if score < score_threshold:
                continue
            results.append({
                "segment_id": obj.properties.get("segment_id"),
                "document_id": obj.properties.get("document_id"),
                "content": obj.properties.get("text"),
                "keywords": obj.properties.get("keywords", []),
                "position": obj.properties.get("position"),
                "score": score,
                "distance": round(distance, 4),
            })

        return results

    async def delete_document(
            self,
            dataset_id: str | UUID,
            account: Account,
    ) -> None:
        """删除指定文档在 Weaviate 中的所有向量数据。"""
        await self._check_document_permission(
            UUID(str(dataset_id)), account
        )
        await self._delete_by_document(dataset_id)

    async def delete_memory(
            self,
            collection_name: str,
            app_id: str | UUID,
            account: Account,
    ) -> None:
        """按 app_id 清空记忆集合（EpisodicMemory 等）中的全部向量数据。

        记忆集合无 dataset_id（按 app_id 组织），删除语义与知识库文档不同：
        - 应用存在且归属当前账号 → 允许删除；
        - 应用不存在（已删除应用的孤儿记忆残留）→ 允许清理；
        - 应用存在但 created_by 为空（早期旧数据，无归属者）→ 允许清理；
        - 应用存在且归属他人 → 拒绝（防越权）。
        """
        from internal.model import App as AppModel

        app = await self.get(AppModel, UUID(str(app_id)))
        if app is not None:
            owner = str(app.created_by or "")
            if owner and owner != str(account.id):
                raise ForbiddenException("应用不存在或无权限")
        col = get_weaviate_client().collections.get(collection_name)
        await run_in_threadpool(
            col.data.delete_many,
            where=Filter.by_property("app_id").equal(str(app_id)),
        )

    async def get_all_collections(self) -> list[str]:
        """列出Weaviate中所有Collection的名称（带 Redis 缓存，避免每次实时连接）。"""
        try:
            cached = self.redis_client.get(COLLECTIONS_CACHE_KEY)
            if cached:
                import json as _json
                return _json.loads(cached)
        except Exception:
            pass

        # weaviate 同步客户端桥接
        collections = list((await run_in_threadpool(get_weaviate_client().collections.list_all)).keys())
        try:
            import json as _json
            self.redis_client.set(
                COLLECTIONS_CACHE_KEY,
                _json.dumps(collections),
                ex=COLLECTIONS_CACHE_TTL,
            )
        except Exception:
            pass
        return collections

    def clear_collections_cache(self) -> None:
        """清除 Collection 列表缓存（新增/删除 Collection 后调用）"""
        try:
            self.redis_client.delete(COLLECTIONS_CACHE_KEY)
        except Exception:
            pass

    async def get_all(
            self,
            collection_name: str | None = None,
            dataset_id: str | None = None,
            document_id: str | None = None,
            app_id: str | None = None,
            limit: int = 100,
            offset: int = 0,
    ) -> dict:
        """查询指定 Collection 中的所有分块数据（不含向量），支持按 dataset_id / app_id 过滤。"""
        name = collection_name or COLLECTION_NAME
        col = get_weaviate_client().collections.get(name)

        filter_parts = []
        if dataset_id:
            filter_parts.append(Filter.by_property("dataset_id").equal(str(dataset_id)))
        if document_id:
            filter_parts.append(Filter.by_property("document_id").equal(str(document_id)))
        if app_id:
            filter_parts.append(Filter.by_property("app_id").equal(str(app_id)))
        filters = Filter.all_of(filter_parts) if filter_parts else None

        # weaviate 同步客户端桥接
        agg = await run_in_threadpool(col.aggregate.over_all, total_count=True, filters=filters)
        total = agg.total_count or 0

        response = await run_in_threadpool(
            col.query.fetch_objects,
            filters=filters,
            limit=limit,
            offset=offset,
            include_vector=False,
        )

        items = []
        for obj in response.objects:
            props = obj.properties
            text = props.get("text") or props.get("content") or ""
            items.append({
                "id": str(obj.uuid),
                "segment_id": props.get("segment_id"),
                "document_id": props.get("document_id"),
                "dataset_id": props.get("dataset_id"),
                "app_id": props.get("app_id"),
                "position": props.get("position"),
                "keywords": props.get("keywords", []),
                "content_length": len(text),
                "text": text,
            })

        return {
            "collection": name,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    async def get_documents_by_collection(
            self,
            collection_name: str | None = None,
            page: int = 1,
            page_size: int = 8,
    ) -> dict:
        """查询指定 Collection 下的文档（去重 document_id，统计每个文档的分块数），支持分页。"""
        name = collection_name or COLLECTION_NAME
        col = get_weaviate_client().collections.get(name)

        try:
            props = [p.name for p in (await run_in_threadpool(col.config.get)).properties]
        except Exception:
            props = []
        if props and "document_id" not in props:
            return await self._get_documents_grouped_by_prop(col, name, "app_id", page, page_size)

        agg_response = await run_in_threadpool(
            col.aggregate.over_all,
            group_by=wvc.aggregate.GroupByAggregate(prop="document_id"),
            total_count=True,
        )

        doc_map: dict[str, dict] = {}
        group_count = len(agg_response.groups) if agg_response.groups else 0
        if group_count > 200:
            scanned = await self._aggregate_documents_by_scan(col, name)
            return self._slice_documents(name, scanned["documents"], page, page_size)

        for group in agg_response.groups:
            doc_id = str(group.grouped_by.value or "unknown")
            doc_map[doc_id] = {
                "document_id": doc_id,
                "dataset_id": "",
                "name": "",
                "segment_count": group.total_count,
            }

        if len(doc_map) <= 20:
            for doc_id, doc_info in doc_map.items():
                try:
                    resp = await run_in_threadpool(
                        col.query.fetch_objects,
                        filters=Filter.by_property("document_id").equal(str(doc_id)),
                        limit=1,
                        include_vector=False,
                    )
                    if resp.objects:
                        doc_info["dataset_id"] = str(
                            resp.objects[0].properties.get("dataset_id") or ""
                        )
                except Exception:
                    continue

        await self._fill_document_names(doc_map)
        documents = sorted(doc_map.values(), key=lambda x: x["document_id"])
        return self._slice_documents(name, documents, page, page_size)

    async def _get_documents_grouped_by_prop(
            self,
            col: Collection,
            name: str,
            prop: str,
            page: int,
            page_size: int,
    ) -> dict:
        """按指定属性（app_id 等）分组聚合文档列表。"""
        agg_response = await run_in_threadpool(
            col.aggregate.over_all,
            group_by=wvc.aggregate.GroupByAggregate(prop=prop),
            total_count=True,
        )

        doc_map: dict[str, dict] = {}
        for group in agg_response.groups:
            key = str(group.grouped_by.value or "unknown")
            doc_map[key] = {
                "document_id": key,
                "dataset_id": "",
                "name": "",
                "segment_count": group.total_count,
            }

        if prop == "app_id" and doc_map:
            await self._fill_app_names(doc_map)

        documents = sorted(doc_map.values(), key=lambda x: x["document_id"])
        result = self._slice_documents(name, documents, page, page_size)
        result["is_memory_collection"] = True
        return result

    async def _fill_app_names(self, doc_map: dict[str, dict]) -> None:
        """按 document_id（此处为 app_id）批量查询 PostgreSQL App 表，填充 name 字段"""
        if not doc_map:
            return
        try:
            from internal.model import App as AppModel

            app_ids = [UUID(doc_id) for doc_id in doc_map if doc_id != "unknown"]
            if not app_ids:
                return
            stmt = sa_select(AppModel.id, AppModel.name).where(
                AppModel.id.in_(app_ids)
            )
            name_map = {
                str(app_id): app_name
                for app_id, app_name in (await self.db.execute(stmt)).fetchall()
            }
            for doc_id, entry in doc_map.items():
                entry["name"] = name_map.get(doc_id, "")
        except Exception:
            pass

    @staticmethod
    def _slice_documents(name: str, documents: list[dict], page: int, page_size: int) -> dict:
        """按页切片文档列表，返回带总数/页码的响应结构"""
        total = len(documents)
        start = (page - 1) * page_size
        return {
            "collection": name,
            "document_count": total,
            "page": page,
            "page_size": page_size,
            "documents": documents[start:start + page_size],
        }

    async def _fill_document_names(self, doc_map: dict[str, dict]) -> None:
        """按 document_id 批量查询 PostgreSQL Document 表，填充 name 字段"""
        if not doc_map:
            return
        try:
            from internal.model import Document as DocumentModel

            doc_ids = [UUID(doc_id) for doc_id in doc_map if doc_id != "unknown"]
            if not doc_ids:
                return
            stmt = sa_select(DocumentModel.id, DocumentModel.name).where(
                DocumentModel.id.in_(doc_ids)
            )
            name_map = {
                str(doc_id): doc_name
                for doc_id, doc_name in (await self.db.execute(stmt)).fetchall()
            }
            for doc_id, entry in doc_map.items():
                entry["name"] = name_map.get(doc_id, "")
        except Exception:
            pass

    async def _aggregate_documents_by_scan(self, col, name: str) -> dict:
        """大分组数时退回一次拉取内存聚合（避免大量请求）"""
        doc_map: dict[str, dict] = {}
        after: str | None = None
        while True:
            response = await run_in_threadpool(
                col.query.fetch_objects,
                limit=500,
                after=after,
                include_vector=False,
            )
            objects = response.objects
            if not objects:
                break
            for obj in objects:
                props = obj.properties
                doc_id = props.get("document_id")
                if not doc_id:
                    continue
                doc_id = str(doc_id)
                entry = doc_map.setdefault(doc_id, {
                    "document_id": doc_id,
                    "dataset_id": str(props.get("dataset_id") or ""),
                    "name": "",
                    "segment_count": 0,
                })
                entry["segment_count"] += 1
            after = objects[-1].uuid
            if len(objects) < 500:
                break

        await self._fill_document_names(doc_map)

        documents = sorted(doc_map.values(), key=lambda x: x["document_id"])
        return {
            "collection": name,
            "document_count": len(documents),
            "documents": documents,
        }

    async def get_segments_by_document(
            self,
            document_id: str | UUID,
            limit: int = 100,
            offset: int = 0,
    ) -> dict:
        """查询指定文档下的所有分块（含原文，按 position 排序）。"""
        filters = Filter.by_property("document_id").equal(str(document_id))

        agg = await run_in_threadpool(self.collection.aggregate.over_all, total_count=True, filters=filters)
        total = agg.total_count or 0

        response = await run_in_threadpool(
            self.collection.query.fetch_objects,
            filters=filters,
            limit=limit,
            offset=offset,
            include_vector=False,
        )

        items = []
        for obj in response.objects:
            props = obj.properties
            items.append({
                "id": str(obj.uuid),
                "segment_id": props.get("segment_id"),
                "dataset_id": props.get("dataset_id"),
                "position": props.get("position"),
                "keywords": props.get("keywords", []),
                "text": props.get("text"),
            })

        items.sort(key=lambda x: x["position"] or 0)

        return {
            "document_id": str(document_id),
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    async def get_metadata(
            self,
            dataset_id: str | UUID,
            document_id: str | UUID | None = None,
            limit: int = 100,
            offset: int = 0,
    ) -> dict:
        """查询 Weaviate 中的分段元数据（不返回向量，只返回属性字段）。"""
        filters = Filter.by_property("dataset_id").equal(str(dataset_id))
        if document_id:
            filters = filters & Filter.by_property("document_id").equal(str(document_id))

        agg = await run_in_threadpool(self.collection.aggregate.over_all, total_count=True, filters=filters)
        total = agg.total_count or 0

        response = await run_in_threadpool(
            self.collection.query.fetch_objects,
            filters=filters,
            limit=limit,
            offset=offset,
            include_vector=False,
        )

        items = []
        for obj in response.objects:
            props = obj.properties
            items.append({
                "id": str(obj.uuid),
                "segment_id": props.get("segment_id"),
                "document_id": props.get("document_id"),
                "dataset_id": props.get("dataset_id"),
                "position": props.get("position"),
                "keywords": props.get("keywords", []),
                "content_length": len(props.get("text") or ""),
            })

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    async def _check_dataset_permission(self, dataset_id: UUID, account: Account) -> Dataset:
        """校验知识库存在且归属当前账号"""
        dataset = await self.get(Dataset, dataset_id)
        if dataset is None or dataset.created_by != account.id:
            raise ForbiddenException("知识库不存在或无权限")
        return dataset

    async def _check_document_permission(
            self, dataset_id: UUID, account: Account
    ) -> Document:
        """校验文档存在、归属该知识库，且当前账号有操作权限"""
        await self._check_dataset_permission(dataset_id, account)
        document = await self.get(Document, dataset_id)
        if not document or str(document.dataset_id) != str(dataset_id):
            raise NotFoundException("文档不存在或不属于该知识库")
        return document

    async def _delete_by_document(
            self,
            dataset_id: str | UUID,
    ) -> None:
        """按 dataset_id 过滤删除 Weaviate 中的分段向量（weaviate 同步客户端桥接）"""
        await run_in_threadpool(
            self.collection.data.delete_many,
            where=(
                Filter.by_property("dataset_id").equal(str(dataset_id))
            )
        )
