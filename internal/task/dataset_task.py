#!/usr/bin/env python
"""
@Time    : 2025/12/9 23:53
@Author  : sunxiaojie
@File    : dataset_task.py

"""
from uuid import UUID

from celery import shared_task

from internal.task.celery_app import celery_app  # noqa: F401


@shared_task
def delete_dataset(dataset_id: UUID) -> None:
    """根据传递的知识库id删除特定的知识库信息"""
    from package.database import build_engine, worker_run
    from internal.container import _get_sync_redis, create_indexing_service

    redis_client = _get_sync_redis()

    async def _coro(session):
        service = create_indexing_service(session, redis_client)
        return await service.delete_dataset(dataset_id)

    # 每任务独立 engine（threads 池下跨 loop 共享 asyncpg 连接会报 InterfaceError）；
    # engine_factory 让创建与 dispose 同 loop
    from package.database import build_engine, worker_run

    worker_run(_coro, engine_factory=build_engine)
