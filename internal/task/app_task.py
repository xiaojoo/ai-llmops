#!/usr/bin/env python
"""
@Time    : 2026/1/18 21:55
@Author  : sunxiaojie
@File    : app_task.py

"""
from uuid import UUID

from celery import shared_task

from internal.task.celery_app import celery_app  # noqa: F401


@shared_task
def auto_create_app(
        name: str,
        description: str,
        account_id: UUID,
        app_type: str = "agent",
) -> None:
    """根据传递的名称、描述、账号id创建一个Agent"""
    from package.database import build_engine, worker_run
    from internal.container import (
        _get_sync_redis,
        create_app_service,
        create_cos_service,
        create_memory_provider_resolver,
        create_retrieval_service,
    )

    redis_client = _get_sync_redis()

    async def _coro(session):
        retrieval_service = create_retrieval_service(session, redis_client)
        app_service = create_app_service(
            session,
            retrieval_service=retrieval_service,
            redis_client=redis_client,
            cos_service=create_cos_service(session),
            memory_provider_resolver=create_memory_provider_resolver(session),
        )
        return await app_service.auto_create_app(name, description, account_id, app_type)

    # 每任务独立 engine（threads 池下跨 loop 共享 asyncpg 连接会报 InterfaceError）；
    # engine_factory 让创建与 dispose 同 loop
    from package.database import build_engine, worker_run

    worker_run(_coro, engine_factory=build_engine)
