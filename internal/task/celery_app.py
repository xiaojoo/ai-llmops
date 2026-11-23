# internal/task/celery_app.py
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import dotenv
from celery import Celery
from celery.signals import worker_ready

from internal.config.settings import get_settings

T = TypeVar("T")


def _broker_url(settings) -> str:
    return f"redis://:{settings.redis_password or ''}@{settings.redis_host}:{settings.redis_port}/{settings.celery_broker_db}"


def create_celery() -> Celery:
    s = get_settings()
    app = Celery(
        "llmops",
        broker=_broker_url(s),
        backend=_broker_url(s).rsplit("/", 1)[0] + f"/{s.celery_result_backend_db}",
        # 显式 include 任务模块：autodiscover_tasks 只扫描各包的 tasks.py，
        # 本项目的任务散落在 document_task/dataset_task/app_task 等文件，必须显式列出
        # （否则 worker 显示 [tasks] 为空，收到消息报 unregistered task）。
        include=[
            "internal.task.document_task",
            "internal.task.dataset_task",
            "internal.task.app_task",
        ],
    )
    app.conf.update(
        task_ignore_result=s.celery_task_ignore_result,
        result_expires=s.celery_result_expires,
        broker_connection_retry_on_startup=s.celery_broker_connection_retry_on_startup,
    )
    app.autodiscover_tasks(["internal.task"])
    return app


celery_app = create_celery()
# 关键：@shared_task 装饰器绑定 Celery「默认 app」（无参 Celery() 的 broker 是 amqp://localhost →
# RabbitMQ，非本项目配置）。必须 set_default() 让 Redis broker 生效，否则任务 delay() 连错 broker。
celery_app.set_default()


def _bootstrap_worker() -> None:
    """worker 进程启动装配（等价 uvicorn lifespan 的基建部分，worker 无 FastAPI lifespan）：

    1. dotenv 载入 os.environ（worker 进程独立于 app 启动，settings 依赖 env）
    2. build_engine + set_default_session_factory（worker_run 依赖默认会话工厂）
    3. DB 配置注入 os.environ（system_config 表 → env，须在 get_settings 首次调用前）
    4. get_settings.cache_clear() 重建单例（读取注入后的 env）
    5. init_redis（任务体 _get_sync_redis 依赖）
    """
    # Celery 只在导入 -A 应用模块期间（utils.imports.cwd_in_path）把进程 cwd 临时加入
    # sys.path，worker_ready 时该条目已被移除；而本函数及任务体内部都是懒加载
    # `from package.database import ...`（项目根下的顶层包），届时根目录不在 sys.path →
    # ModuleNotFoundError: No module named 'package'。此处基于 __file__ 推导项目根目录
    # （与 settings.project_root 同源）重新加入 sys.path，一次插入、进程生命周期内生效，
    # 不依赖进程 cwd；打包部署（pyinstaller）可用 PROJECT_ROOT 环境变量覆盖。
    import os
    import sys
    from pathlib import Path

    _project_root = str(Path(os.environ.get("PROJECT_ROOT") or Path(__file__).resolve().parents[2]))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    dotenv.load_dotenv()

    # 定向过滤 dashscope 的 Assistants API 废弃警告（同 app/http/app.py）。
    # 顺序约束：必须先导入 weaviate——其导入链会 simplefilter("default") 插入全匹配
    # Warning 过滤器，若本过滤注册在其前会被遮蔽失效；注册后再导入会触发 dashscope
    # 的 internal.service（下方 SystemConfigService 导入链）。
    import warnings

    import weaviate  # noqa: F401  仅触发导入（插入 default::Warning 过滤器）

    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r"The Assistants API \(dashscope\.assistants\) is deprecated.*",
    )

    from package.database import (
        build_engine,
        build_sessionmaker,
        set_default_session_factory,
        worker_run,
    )

    engine = build_engine()
    set_default_session_factory(build_sessionmaker(engine))

    from internal.service import SystemConfigService

    try:
        worker_run(lambda session: SystemConfigService(db=session).apply_to_env())
    except Exception as e:  # noqa: BLE001
        print(f"[celery] DB 配置注入失败，使用 .env/compose 配置: {e}")

    get_settings.cache_clear()
    get_settings()

    from internal.extensions.redis import init_redis

    init_redis()


@worker_ready.connect
def _on_worker_ready(sender=None, **kwargs) -> None:  # noqa: ARG001
    """worker 就绪钩子：worker_ready 在主进程触发（threads/solo 池同样生效，
    worker_process_init 在 threads 池下不触发——任务执行会报会话工厂未初始化）。"""
    _bootstrap_worker()


def run_async(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """任务体内执行异步服务调用（P5 起使用；无 Flask app_context）。"""
    return asyncio.run(coro_factory())
