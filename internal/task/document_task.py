#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time    : 2025/12/3 18:44
@Author  : sunxiaojie
@File    : document_task.py
"""
from uuid import UUID

from celery import shared_task

# 确保 Redis broker 的 celery_app 已初始化并 set_default（否则 @shared_task 绑定无参默认 app → RabbitMQ）
from internal.task.celery_app import celery_app  # noqa: F401

# 文档异步任务统一重试策略：临时性异常（DB 断连/网络抖动/OCR 超时）自动重试，
# 指数退避 + 抖动；3 次仍失败则任务失败（文档状态置 error，可手动重新上传）。
RETRY_KWARGS = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,      # 指数退避：2s -> 4s -> 8s
    "retry_backoff_max": 60,
    "max_retries": 3,
    "retry_jitter": True,
}


def _indexing_coro(document_ids: list[UUID] | UUID, *, delete_dataset: bool = False, dataset_id: UUID | None = None):
    """构造 IndexingService 调用协程（worker_run 的 coro_factory）。

    按操作分派：build_documents / update_document_enabled / delete_document / delete_dataset。
    """
    from internal.container import _get_sync_redis, create_indexing_service

    redis_client = _get_sync_redis()

    async def _coro(session):
        service = create_indexing_service(session, redis_client)
        if delete_dataset:
            return await service.delete_dataset(dataset_id)
        if isinstance(document_ids, UUID) and dataset_id is not None:
            return await service.delete_document(dataset_id, document_ids)
        if isinstance(document_ids, UUID):
            return await service.update_document_enabled(document_ids)
        return await service.build_documents(document_ids)

    return _coro


def _run_with_engine(coro_factory):
    """每任务独立 engine（threads 池下各线程各自 asyncio.run 新 loop，共享全局 engine
    会跨 loop 复用 asyncpg 连接报 InterfaceError）；engine_factory 让创建与 dispose 同 loop。"""
    from package.database import build_engine, worker_run

    worker_run(coro_factory, engine_factory=build_engine)


@shared_task(**RETRY_KWARGS)
def build_documents(document_ids: list[UUID]) -> None:
    """根据传递的文档id列表，构建文档"""
    _run_with_engine(_indexing_coro(document_ids))


@shared_task(**RETRY_KWARGS)
def update_document_enabled(document_id: UUID) -> None:
    """根据传递的文档id修改文档状态"""
    _run_with_engine(_indexing_coro(document_id))


@shared_task(**RETRY_KWARGS)
def delete_document(dataset_id: UUID, document_id: UUID) -> None:
    """根据传递的文档id删除文档信息"""
    _run_with_engine(_indexing_coro(document_id, dataset_id=dataset_id))
