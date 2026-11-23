import pytest
import sqlalchemy as sa

from package.database import build_engine

_engine = build_engine()


@pytest.mark.asyncio
async def test_sub_task_checkpoint_model_fields():
    """模型列冒烟：建表语句含关键列（依赖迁移已执行）。

    旧实现走 `internal.extension.database_extension.db.engine`（同步 Flask-SQLAlchemy），
    现改为 `package.database.build_engine()`；asyncpg 方言的 Inspector 调用必须经
    `conn.run_sync`（greenlet 桥），不能在 async 上下文直接同步 IO。
    """
    async with _engine.connect() as conn:
        def _inspect(sync_conn):
            insp = sa.inspect(sync_conn)
            if not insp.has_table("sub_task_checkpoint"):
                pytest.skip("sub_task_checkpoint 表尚未迁移")
            return {c["name"] for c in insp.get_columns("sub_task_checkpoint")}

        cols = await conn.run_sync(_inspect)
    assert {"conversation_id", "position", "query", "status", "messages", "iteration_count"} <= cols
