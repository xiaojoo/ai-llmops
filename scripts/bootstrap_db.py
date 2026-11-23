#!/usr/bin/env python
"""数据库引导脚本：面向空库/新部署。

背景：迁移链的基线 revision（273f811b2cf4）是 no-op 锚点（当年表结构由
create_all 在应用启动时建立），后续迁移都假设表已存在——因此**全新数据库
无法靠 `alembic upgrade head` 从零建表**（会在 add message.is_archived 处
报 relation "message" does not exist）。

本脚本等价于「应用启动时自动建表 + 版本对齐」：
  1. system_config 表不存在（空库/首次部署）→ 全量 create_all 建表
     （与 app/http/app.py lifespan 第 5 步同逻辑，导入 internal.model 注册全部 ORM 表）
  2. alembic_version 对齐到 head（stamp head）：
     之后 entrypoint / 手动跑 `alembic upgrade head` 均为 no-op，不会误报失败

对已有库幂等：表已存在则跳过 create_all；版本已在 head 则 stamp 无操作。

用法：
  python scripts/bootstrap_db.py          # 仓库根目录执行（容器内 WORKDIR=/llmops 同）
"""
import asyncio
import sys
from pathlib import Path

# 项目根目录入 sys.path（兼容 `python scripts/bootstrap_db.py` 与 `python -m scripts.bootstrap_db`）
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect

import internal.model  # noqa: F401  注册全部 ORM 表到 Base.metadata（与 alembic env.py 一致）
from package.database import Base, build_engine

ALEMBIC_INI = _ROOT / "internal" / "migrations" / "alembic.ini"


async def _ensure_tables() -> None:
    engine = build_engine()
    try:
        async with engine.begin() as conn:
            table_exists = await conn.run_sync(lambda c: sa_inspect(c).has_table("system_config"))
            if table_exists:
                print("system_config 已存在，跳过 create_all（存量库）")
                return
            await conn.run_sync(Base.metadata.create_all)
            print("create_all 完成：空库已建立全部业务表")
    finally:
        await engine.dispose()


def _stamp_head() -> None:
    cfg = Config(str(ALEMBIC_INI))
    command.stamp(cfg, "head")
    print("alembic_version 已对齐 head")


def main() -> None:
    asyncio.run(_ensure_tables())
    _stamp_head()
    print("数据库引导完成")


if __name__ == "__main__":
    main()
