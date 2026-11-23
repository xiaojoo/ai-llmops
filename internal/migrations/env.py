"""独立 Alembic 异步环境（不再依赖 Flask 应用上下文）。"""
import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

# alembic 控制台脚本（venv\Scripts\alembic.exe）运行时项目根目录不在 sys.path，
# 直接执行 env.py 会 `ModuleNotFoundError: No module named 'internal'`。
# 这里基于 __file__ 推导项目根目录（与 settings.project_root 同源，不依赖进程 cwd）
# 显式加入 sys.path；打包部署（pyinstaller）可用 PROJECT_ROOT 环境变量覆盖。
# 注意：必须在 import internal.* / package.* 之前执行。
_PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT") or Path(__file__).resolve().parents[2])
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from alembic import context
from sqlalchemy.engine import Connection

import internal.model  # noqa: F401  注册全部 ORM 表到 Base.metadata（target_metadata 依赖）
from internal.config.settings import get_settings
from package.database import Base, build_engine

# 独立导入（如 pytest 直接 import 本模块）时不存在 Alembic 运行代理，
# context.config 不可用；此时跳过配置与迁移执行，仅保证模块可导入。
config = getattr(context, "config", None)
if config is not None:
    fileConfig(config.config_file_name)

    # 数据库 URL 直接取自 settings（自动补 asyncpg 驱动前缀）
    from package.database import _async_url

    config.set_main_option("sqlalchemy.url", _async_url(get_settings().sqlalchemy_database_uri))

target_metadata = Base.metadata


def process_revision_directives(context, revision, directives):  # noqa: ANN001
    if getattr(config.cmd_opts, "autogenerate", False):
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            from logging import getLogger
            getLogger("alembic.env").info("No changes in schema detected.")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # 统一经 build_engine 建引擎：其 connect 事件会把 options=-csearch_path=X
    # （.env URI 的 psycopg2 参数）应用为 SET search_path，保证 llmops schema 可见。
    connectable = build_engine()
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        asyncio.run(run_async_migrations())
