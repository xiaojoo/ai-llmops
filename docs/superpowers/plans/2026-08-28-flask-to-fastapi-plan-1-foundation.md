# Plan 1: 契约基线 + 异步基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Flask→FastAPI 迁移的契约基线（153 路由清单 + 响应样例），并搭建一套与业务代码解耦的异步基础设施（settings / async DB / Alembic async / Redis / Weaviate / 日志 / Celery / 最小 FastAPI pilot），全部落在 `release_fastApi` 分支。

**Architecture:** 所有新基建模块（`internal/config/settings.py`、`package/database.py`、`internal/extensions/`、`internal/task/celery_app.py`、`app/http/app_fastapi.py`）以**纯新增**方式落地，不触碰任何仍依赖 Flask 的代码（services/handlers/models/router）。旧 Flask 应用从本计划起冻结（不再作为运行基线），回归基线 = 路由清单 + 黄金样例 + 新基建测试。

**Tech Stack:** FastAPI（最新稳定版）、uvicorn、pydantic v2 + pydantic-settings、SQLAlchemy 2.x async（asyncpg）、Alembic（async env）、redis-py `redis.asyncio`、weaviate-client v4、Celery、pytest + pytest-asyncio + httpx、aiosqlite（测试用）。

**Spec:** `docs/superpowers/specs/2026-08-28-flask-to-fastapi-design.md`

## Global Constraints

- 所有提交必须落在 `release_fastApi` 分支（`git checkout release_fastApi` 前置确认）。
- **最新稳定版本 + 最新语法**：SQLAlchemy 2.x 用 `Mapped[]`/`mapped_column`/`select()`；Pydantic v2 惯用法；FastAPI 最新版；**不写兼容旧 API 的垫片**。
- 153 条路由的 URL/方法/响应契约（code/message/data）与 SSE 事件协议在后续阶段保持不变；本计划只采集基线，不改任何契约。
- 数据库表结构不变（迁移版本文件复用）。
- 本计划禁止修改：`internal/handler/*`、`internal/service/*`、`internal/model/*`、`internal/router/router.py`、`package/response/*`、`package/sqlalchemy/*`。
- 旧 venv（`venv/`）物理上保留 flask 包以便过渡期 import；`requirements.txt` 从本计划起**移除全部 flask*/gevent/eventlet**（新部署不再安装）。
- 测试数据库：单元测试用 `sqlite+aiosqlite:///:memory:`；需要真实 Postgres 的验证（alembic、redis ping）标记 `@pytest.mark.integration`，无环境时 skip。

---

## Task 1: 路由清单提取（契约基线）

**Files:**
- Create: `scripts/migration/extract_routes.py`
- Create: `test/migration/test_extract_routes.py`
- Produce: `docs/migration/route-inventory.md`

**Interfaces:**
- Produces: `extract_routes.extract() -> list[tuple[blueprint: str, method: str, path: str, view: str]]`；`main()` 写出 `docs/migration/route-inventory.md`。

- [ ] **Step 1: 写失败测试**

```python
# test/migration/test_extract_routes.py
from scripts.migration.extract_routes import extract


def test_extract_counts():
    routes = extract()
    assert len(routes) >= 150


def test_extract_known_routes():
    routes = extract()
    keys = {(bp, m, p) for bp, m, p, _ in routes}
    assert ("bp", "GET", "/ping") in keys
    assert ("bp", "POST", "/apps") in keys
    assert ("openapi_bp", "POST", "/openapi/chat") in keys
    assert ("openapi_bp", "POST", "/webhook") in keys
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/migration/test_extract_routes.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'scripts.migration'`

- [ ] **Step 3: 实现提取脚本**

```python
# scripts/migration/extract_routes.py
"""从 internal/router/router.py 提取 153 条路由清单（AST 解析，无需 Flask 运行时）。"""
import ast
from pathlib import Path

ROUTER = Path("internal/router/router.py")
OUT = Path("docs/migration/route-inventory.md")


def extract() -> list[tuple[str, str, str, str]]:
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    routes: list[tuple[str, str, str, str]] = []  # (blueprint, method, path, view)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_url_rule" or not isinstance(node.func.value, ast.Name):
            continue
        bp_name = node.func.value.id  # bp | openapi_bp
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        rule = kwargs.get("rule") or (node.args[0] if node.args else None)
        view = kwargs.get("view_func")
        if not isinstance(rule, ast.Constant) or not isinstance(view, ast.Attribute):
            continue
        methods = kwargs.get("methods")
        if isinstance(methods, ast.List):
            for elt in methods.elts:
                if isinstance(elt, ast.Constant):
                    routes.append((bp_name, elt.value, rule.value, view.attr))
        else:
            routes.append((bp_name, "GET", rule.value, view.attr))
    return routes


def main() -> None:
    routes = extract()
    lines = [
        "# 路由清单（Flask → FastAPI 契约基线）",
        "",
        "| 蓝图 | 方法 | 路径 | Handler 方法 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {b} | {m} | {p} | {v} |" for b, m, p, v in sorted(routes)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"提取 {len(routes)} 条路由 -> {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 创建 `scripts/migration/__init__.py`（空文件），运行确认通过**

Run: `venv/Scripts/python -m pytest test/migration/test_extract_routes.py -v`
Expected: PASS（若实际路由数与断言不符，以提取结果为准并调整断言下限，但不得低于 150）

- [ ] **Step 5: 生成清单文档**

Run: `venv/Scripts/python -m scripts.migration.extract_routes`
Expected: 输出 `docs/migration/route-inventory.md`，行数 ≥ 155

- [ ] **Step 6: 提交**

```bash
git add scripts/migration test/migration docs/migration
git commit -m "chore(migration): 提取 153 路由契约基线清单（P0）"
```

---

## Task 2: 黄金响应样例采集（旧 Flask 应用，冻结前最后一次运行）

**Files:**
- Create: `docs/migration/golden/401-shape.json`
- Create: `docs/migration/golden/ping.json`
- Create: `docs/migration/golden/default-app-icon.json`
- Create: `scripts/migration/capture_golden.py`

**Interfaces:**
- Produces: 三类响应结构的**字段级样例**：未认证 401 结构（code/message/data）、`/ping` 结构、`/default-app-icon` 行为。

- [ ] **Step 1: 启动旧 Flask 应用（后台）**

Run（后台任务）: `venv/Scripts/python scripts/start_backend.py`
Expected: 日志出现 `running (debug=False)`；端口 5000 可访问（旧脚本硬编码 5000；若端口被占改用 `FLASK_RUN_PORT` 环境变量，以实际为准）

- [ ] **Step 2: 写采集脚本并运行**

```python
# scripts/migration/capture_golden.py
"""冻结前采集旧 Flask 应用的响应结构样例（契约基线）。"""
import json
from pathlib import Path

import requests

BASE = "http://127.0.0.1:5000"
OUT = Path("docs/migration/golden")
OUT.mkdir(parents=True, exist_ok=True)


def dump(name: str, resp: requests.Response) -> None:
    payload = {"status_code": resp.status_code, "headers": dict(resp.headers), "body": resp.text}
    (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{name}: status={resp.status_code} body={resp.text[:200]}")


def main() -> None:
    dump("401-shape", requests.get(f"{BASE}/apps"))            # 无 token，认证中间件拦截
    dump("ping", requests.get(f"{BASE}/ping"))                 # 健康检查
    dump("default-app-icon", requests.get(f"{BASE}/default-app-icon"))


if __name__ == "__main__":
    main()
```

Run: `venv/Scripts/python scripts/migration/capture_golden.py`
Expected: 三个 json 落盘；`401-shape.json` 的 body 为 `{"code":..., "message":..., "data":...}` 结构（code 为未授权码，以实际 HttpCode 值为准）

- [ ] **Step 3: 停止旧应用后台任务，提交**

```bash
git add docs/migration/golden scripts/migration/capture_golden.py
git commit -m "chore(migration): 采集旧 Flask 黄金响应样例（401/ping/icon）（P0）"
```

---

## Task 3: requirements 更新（最新版本，移除全部 flask*）

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements_dev.txt`

**Interfaces:**
- Produces: 安装命令 `venv/Scripts/pip install -U fastapi "uvicorn[standard]" asyncpg greenlet python-multipart aiosqlite pydantic-settings pytest-asyncio`

- [ ] **Step 1: 从 `requirements.txt` 删除以下行**

```text
Flask==3.1.3
flask-cors==6.0.5
Flask-Login==0.6.3
Flask-Migrate==4.1.0
Flask-SQLAlchemy==3.1.1
flask_weaviate==1.1.0
Flask-WTF==1.3.0
gevent==26.8.0
eventlet==0.41.2
Werkzeug==3.1.8
WTForms==3.2.2
```

- [ ] **Step 2: 在 `requirements.txt` 末尾追加（最新稳定版，不钉死版本）**

```text
# --- Flask → FastAPI 迁移（最新稳定版） ---
fastapi
uvicorn[standard]
asyncpg
greenlet
python-multipart
pydantic-settings
```

- [ ] **Step 3: `requirements_dev.txt` 同步：同样删除全部 flask*/gevent/eventlet 行，追加测试依赖**

```text
pytest-asyncio
aiosqlite
httpx
```

- [ ] **Step 4: 安装到 venv 并验证**

Run: `venv/Scripts/pip install -U fastapi "uvicorn[standard]" asyncpg greenlet python-multipart pydantic-settings pytest-asyncio aiosqlite httpx`
Run: `venv/Scripts/python -c "import fastapi, uvicorn, asyncpg, sqlalchemy, pydantic_settings; print(fastapi.__version__, sqlalchemy.__version__)"`
Expected: 打印版本号，无 ImportError

- [ ] **Step 5: 提交**

```bash
git add requirements.txt requirements_dev.txt
git commit -m "chore(deps): 移除 flask*/gevent/eventlet，引入 fastapi/uvicorn/asyncpg 等最新依赖"
```

---

## Task 4: settings 单例（pydantic-settings）

**Files:**
- Create: `internal/config/__init__.py`（如不存在）
- Create: `internal/config/settings.py`
- Test: `test/internal/config/test_settings.py`

**Interfaces:**
- Consumes: `.env`（`python-dotenv` 已由 pydantic-settings 的 `env_file` 处理）
- Produces: `get_settings() -> Settings`（`lru_cache` 单例）；字段名与旧 `Config`/`DEFAULT_CONFIG` 对齐，供后续所有模块引用。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/config/test_settings.py
from internal.config.settings import Settings, get_settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.sqlalchemy_pool_size == 30
    assert s.redis_host == "localhost"
    assert s.assistant_agent_id == "dd2d4f79-4a46-4393-947e-afd078fb85a7"


def test_env_override(monkeypatch):
    monkeypatch.setenv("REDIS_PORT", "9999")
    s = Settings(_env_file=None)
    assert s.redis_port == 9999


def test_singleton():
    assert get_settings() is get_settings()
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/internal/config/test_settings.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 settings**

```python
# internal/config/settings.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置单例（读取 .env，字段名与旧 config/default_config.py 对齐）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SQLAlchemy
    sqlalchemy_database_uri: str = ""
    sqlalchemy_pool_size: int = 30
    sqlalchemy_pool_recycle: int = 3600
    sqlalchemy_echo: bool = False

    # Weaviate
    weaviate_http_host: str = "localhost"
    weaviate_http_port: int = 8080
    weaviate_grpc_host: str = "localhost"
    weaviate_grpc_port: int = 50051
    weaviate_api_key: str = ""

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_username: str = ""
    redis_password: str = ""
    redis_db: int = 0
    redis_use_ssl: bool = False
    redis_socket_timeout: float = 5.0
    redis_connect_timeout: float = 5.0

    # Celery
    celery_broker_db: int = 1
    celery_result_backend_db: int = 1
    celery_task_ignore_result: bool = False
    celery_result_expires: int = 3600
    celery_broker_connection_retry_on_startup: bool = True

    # 业务
    assistant_agent_id: str = "dd2d4f79-4a46-4393-947e-afd078fb85a7"
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh"
    embedding_device: str = "cpu"
    embedding_api_key: str = ""
    embedding_api_base: str = ""
    rerank_provider: str = "local"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_api_key: str = ""
    rerank_api_base: str = ""
    query_rewrite_model: str = "deepseek-v4-flash"
    storage_provider: str = "cos"
    miniio_api_url: str = "http://localhost:9001"
    miniio_timeout: int = 60
    mode: str = ""  # api | celery | local（对齐旧 MODE 环境变量）


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python -m pytest test/internal/config/test_settings.py -v`
Expected: PASS（注意：本地 `.env` 若设置过 `SQLALCHEMY_POOL_SIZE` 等，`test_defaults` 会失败——改用 `_env_file=None` 已规避；`test_env_override` 的 monkeypatch 生效）

- [ ] **Step 5: 提交**

```bash
git add internal/config test/internal/config
git commit -m "feat(config): pydantic-settings 全局配置单例（替换 Flask Config）"
```

---

## Task 5: 异步数据库层（package/database.py）

**Files:**
- Create: `package/database.py`
- Test: `test/package/test_database.py`

**Interfaces:**
- Consumes: `internal.config.settings.get_settings`
- Produces:
  - `Base(DeclarativeBase)` —— 后续全部 model 改继承它；
  - `build_engine(url: str | None = None, **opts) -> AsyncEngine`（URL 自动 `postgresql://` → `postgresql+asyncpg://`；测试可注入 sqlite+aiosqlite）；
  - `build_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`；
  - `get_db() -> AsyncIterator[AsyncSession]`：请求作用域会话，成功 commit / 异常 rollback；
  - `async_session_context()`：后台线程/Celery 用的独立会话上下文（`asyncio.run` 内使用）。

- [ ] **Step 1: 写失败测试**

```python
# test/package/test_database.py
import pytest
from sqlalchemy import select, String
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base, build_engine, build_sessionmaker, get_db


class Item(Base):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


@pytest.mark.asyncio
async def test_session_commit_and_query():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = build_sessionmaker(engine)

    async with Session() as s:
        s.add(Item(name="hello"))
        await s.commit()

    async with Session() as s:
        rows = (await s.execute(select(Item))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "hello"
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_error():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = build_sessionmaker(engine)

    async def consume():
        gen = get_db(Session)
        s = await gen.__anext__()
        s.add(Item(name="ghost"))
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("boom"))
        await gen.aclose()

    await consume()

    async with Session() as s:
        rows = (await s.execute(select(Item))).scalars().all()
        assert rows == []
    await engine.dispose()


def test_asyncpg_url_rewrite():
    from package.database import _async_url
    assert _async_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _async_url("sqlite+aiosqlite:///:memory:") == "sqlite+aiosqlite:///:memory:"
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/package/test_database.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'package.database'`

- [ ] **Step 3: 实现**

```python
# package/database.py
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from internal.config.settings import get_settings


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Base(DeclarativeBase):
    """全量 async 后所有 ORM model 的统一基类。"""


def build_engine(url: str | None = None, **opts) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        _async_url(url or settings.sqlalchemy_database_uri),
        pool_size=opts.pop("pool_size", settings.sqlalchemy_pool_size),
        pool_recycle=opts.pop("pool_recycle", settings.sqlalchemy_pool_recycle),
        echo=opts.pop("echo", settings.sqlalchemy_echo),
        **opts,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """请求作用域会话：成功统一 commit，异常统一 rollback（替代旧 auto_commit）。"""
    factory = session_factory or _DEFAULT_SESSION_FACTORY
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# lifespan 启动后注入；未注入时访问抛明确错误
_DEFAULT_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = None


def set_default_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _DEFAULT_SESSION_FACTORY
    _DEFAULT_SESSION_FACTORY = factory


def get_default_session_factory() -> async_sessionmaker[AsyncSession]:
    if _DEFAULT_SESSION_FACTORY is None:
        raise RuntimeError("会话工厂未初始化：请先在 lifespan 中调用 set_default_session_factory()")
    return _DEFAULT_SESSION_FACTORY
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python -m pytest test/package/test_database.py -v`
Expected: PASS（若 `get_db(Session)` 显式传工厂的用法与实现不一致，以测试为准修正实现签名，但保留 `get_db()` 无参默认）

- [ ] **Step 5: 提交**

```bash
git add package/database.py test/package
git commit -m "feat(db): async SQLAlchemy 引擎/会话工厂/请求作用域 get_db（Mapped/mapped_column 最新语法）"
```

---

## Task 6: Alembic 独立化（async env.py）

**Files:**
- Modify: `internal/migrations/env.py`
- Test: `test/migration/test_alembic_env.py`（仅验证 env.py 可导入 + URL 改写逻辑；真实 upgrade 标 integration）

**Interfaces:**
- Consumes: `internal.config.settings.get_settings`、`internal.extension.database_extension.db.metadata`（模型转换前的过渡来源，模型转换后改 `package.database.Base.metadata`）
- Produces: 独立于 Flask 的 Alembic 异步环境；`alembic upgrade head` 在真实库可执行。

- [ ] **Step 1: 写失败测试**

```python
# test/migration/test_alembic_env.py
import importlib
import sys


def test_env_imports_without_flask_app():
    # 移除 flask 应用上下文相关符号依赖：env.py 顶层不得再 import flask
    import internal.migrations.env as env  # noqa: F401
    source = open("internal/migrations/env.py", encoding="utf-8").read()
    assert "from flask" not in source
    assert "current_app" not in source
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/migration/test_alembic_env.py -v`
Expected: FAIL（现有 env.py 含 `from flask import current_app`）

- [ ] **Step 3: 重写 env.py（整体替换）**

```python
# internal/migrations/env.py
"""独立 Alembic 异步环境（不再依赖 Flask 应用上下文）。"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from internal.config.settings import get_settings
from internal.extension.database_extension import db  # 过渡：模型转换后改为 package.database.Base

config = context.config
fileConfig(config.config_file_name)

# 数据库 URL 直接取自 settings（自动补 asyncpg 驱动前缀）
from package.database import _async_url

config.set_main_option("sqlalchemy.url", _async_url(get_settings().sqlalchemy_database_uri))

target_metadata = db.metadata


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
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python -m pytest test/migration/test_alembic_env.py -v`
Expected: PASS

- [ ] **Step 5: 真实库验证（integration，需本地 Postgres 可达）**

Run: `venv/Scripts/alembic -c internal/migrations/alembic.ini upgrade head`（若 ini 路径不同以实际为准；需在包含 `internal/migrations/` 的目录执行）
Expected: 迁移脚本依次执行成功（`alembic_version` 更新到 head）

- [ ] **Step 6: 提交**

```bash
git add internal/migrations/env.py test/migration/test_alembic_env.py
git commit -m "refactor(migrations): Alembic 独立化（async env，移除 flask current_app 依赖）"
```

---

## Task 7: Redis / Weaviate / 日志 bootstrap（internal/extensions/ 新包）

**Files:**
- Create: `internal/extensions/__init__.py`
- Create: `internal/extensions/redis.py`
- Create: `internal/extensions/weaviate.py`
- Create: `internal/extensions/logging.py`
- Test: `test/internal/extensions/test_extensions.py`

**Interfaces:**
- Consumes: `get_settings()`
- Produces:
  - `init_redis() -> redis.asyncio.Redis`（模块级 `redis_client` 单例；同步 `sync_redis_client` 供 AgentQueueManager 过渡期使用）；
  - `init_weaviate() -> weaviate.Client`（模块级 `weaviate_client`）；
  - `init_logging() -> None`（幂等：重复调用不重复挂 handler）。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/extensions/test_extensions.py
import logging

import internal.extensions.logging as logging_ext
import internal.extensions.redis as redis_ext


def test_logging_idempotent():
    before = len(logging.getLogger().handlers)
    logging_ext.init_logging()
    after = len(logging.getLogger().handlers)
    assert after == before + 1  # 首次调用挂载一个文件 handler
    logging_ext.init_logging()  # 幂等：不重复挂载
    assert len(logging.getLogger().handlers) == after


def test_redis_client_is_async_redis():
    client = redis_ext.init_redis()
    import redis.asyncio
    assert isinstance(client, redis.asyncio.Redis)
    assert client.connection_pool.connection_kwargs["host"] == "localhost"
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/internal/extensions/test_extensions.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现三个模块**

```python
# internal/extensions/redis.py
import redis.asyncio as aioredis
import redis as sync_redis

from internal.config.settings import get_settings

redis_client: aioredis.Redis | None = None
sync_redis_client: sync_redis.Redis | None = None


def init_redis() -> aioredis.Redis:
    global redis_client, sync_redis_client
    if redis_client is not None:
        return redis_client
    s = get_settings()
    common = dict(
        host=s.redis_host, port=s.redis_port, username=s.redis_username or None,
        password=s.redis_password or None, db=s.redis_db,
        socket_timeout=s.redis_socket_timeout, socket_connect_timeout=s.redis_connect_timeout,
        ssl=s.redis_use_ssl, decode_responses=False,
    )
    redis_client = aioredis.Redis(**common)
    sync_redis_client = sync_redis.Redis(**common)
    return redis_client
```

```python
# internal/extensions/weaviate.py
import weaviate

from internal.config.settings import get_settings

weaviate_client: weaviate.WeaviateClient | None = None


def init_weaviate() -> weaviate.WeaviateClient:
    global weaviate_client
    if weaviate_client is not None:
        return weaviate_client
    s = get_settings()
    auth = weaviate.auth.AuthApiKey(s.weaviate_api_key) if s.weaviate_api_key else None
    weaviate_client = weaviate.connect_to_custom(
        http_host=s.weaviate_http_host, http_port=s.weaviate_http_port,
        grpc_host=s.weaviate_grpc_host, grpc_port=s.weaviate_grpc_port,
        auth_credentials=auth, skip_init_checks=True,
    )
    return weaviate_client
```

```python
# internal/extensions/logging.py
import atexit
import logging
import os
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

_initialized = False


def init_logging() -> None:
    global _initialized
    if _initialized:
        return
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if os.getenv("FLASK_ENV") == "development" else logging.WARNING)
    log_folder = os.path.join(os.getcwd(), "storage", "logs")
    os.makedirs(log_folder, exist_ok=True)
    handler = ConcurrentTimedRotatingFileHandler(
        os.path.join(log_folder, "app.log"), when="midnight", interval=1,
        backupCount=30, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(filename)s -> %(funcName)s line:%(lineno)d [%(levelname)s]: %(message)s",
    ))
    root.addHandler(handler)
    atexit.register(handler.close)
    if os.getenv("FLASK_ENV") == "development":
        console = logging.StreamHandler()
        console.setFormatter(handler.formatter)
        root.addHandler(console)
    _initialized = True
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python -m pytest test/internal/extensions/test_extensions.py -v`
Expected: PASS（weaviate 若未装新版，`pip install -U weaviate-client` 后重跑；测试仅 import，不连真实服务）

- [ ] **Step 5: 提交**

```bash
git add internal/extensions test/internal/extensions
git commit -m "feat(extensions): Redis(async)/Weaviate/日志 bootstrap 独立模块"
```

---

## Task 8: Celery 独立化（internal/task/celery_app.py）

**Files:**
- Create: `internal/task/celery_app.py`
- Test: `test/internal/task/test_celery_app.py`

**Interfaces:**
- Consumes: `get_settings()`
- Produces: `celery_app: Celery`（broker/backend 取自 settings，`task_cls` 不再包 Flask app_context）；`async_task_runner(coro_factory)` 工具：在任务体内 `asyncio.run` 执行异步服务调用（P5 起任务体改用）。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/task/test_celery_app.py
from internal.task.celery_app import celery_app


def test_celery_config():
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.main == "llmops"
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/internal/task/test_celery_app.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# internal/task/celery_app.py
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from celery import Celery

from internal.config.settings import get_settings

T = TypeVar("T")


def _broker_url(settings) -> str:
    return f"redis://:{settings.redis_password or ''}@{settings.redis_host}:{settings.redis_port}/{settings.celery_broker_db}"


def create_celery() -> Celery:
    s = get_settings()
    app = Celery("llmops", broker=_broker_url(s), backend=_broker_url(s).rsplit("/", 1)[0] + f"/{s.celery_result_backend_db}")
    app.conf.update(
        task_ignore_result=s.celery_task_ignore_result,
        result_expires=s.celery_result_expires,
        broker_connection_retry_on_startup=s.celery_broker_connection_retry_on_startup,
    )
    app.autodiscover_tasks(["internal.task"])
    return app


celery_app = create_celery()


def run_async(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """任务体内执行异步服务调用（P5 起使用；无 Flask app_context）。"""
    return asyncio.run(coro_factory())
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python -m pytest test/internal/task/test_celery_app.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/task/celery_app.py test/internal/task/test_celery_app.py
git commit -m "feat(celery): Celery 独立化（settings 配置，移除 FlaskTask/app_context）"
```

---

## Task 9: 最小 FastAPI pilot（app/http/app_fastapi.py）

**Files:**
- Create: `app/http/app_fastapi.py`
- Test: `test/app/test_app_fastapi.py`

**Interfaces:**
- Consumes: Task 4–7 全部产物
- Produces: `app: FastAPI`（title=llmops）；lifespan 装配 engine/session/redis/weaviate/日志；`GET /healthz`；自动 `/docs`。Web 翻转时此文件演进为正式 `app/http/app.py`。

- [ ] **Step 1: 写失败测试**

```python
# test/app/test_app_fastapi.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.http.app_fastapi import app


@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_openapi_docs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "llmops"
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python -m pytest test/app/test_app_fastapi.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# app/http/app_fastapi.py
"""FastAPI pilot：装配异步基础设施。Web 翻转时演进为 app/http/app.py。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from internal.config.settings import get_settings
from internal.extensions.logging import init_logging
from internal.extensions.redis import init_redis
from internal.extensions.weaviate import init_weaviate
from package.database import Base, build_engine, build_sessionmaker, set_default_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_logging()
    engine = build_engine()
    set_default_session_factory(build_sessionmaker(engine))
    app.state.engine = engine
    init_redis()
    init_weaviate()
    if settings.mode not in ("celery", "local"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="llmops", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python -m pytest test/app/test_app_fastapi.py -v`
Expected: PASS（`create_all` 在 Base 尚无模型时为空操作；redis/weaviate 初始化仅建客户端不建连接）

- [ ] **Step 5: 手工冒烟**

Run: `venv/Scripts/python -m uvicorn app.http.app_fastapi:app --port 5010`
Expected: `http://127.0.0.1:5010/healthz` 返回 `{"status":"ok"}`；`/docs` 可打开

- [ ] **Step 6: 提交**

```bash
git add app/http/app_fastapi.py test/app
git commit -m "feat(http): FastAPI pilot（lifespan 装配异步基建 + /healthz + /docs）"
```

---

## Task 10: 全量回归与收尾

**Files:**
- Create: `docs/migration/progress.md`（迁移进度跟踪，本计划里程碑勾选）

**Interfaces:**
- Produces: 本计划里程碑验收记录；后续计划入口。

- [ ] **Step 1: 运行全部新增测试**

Run: `venv/Scripts/python -m pytest test/migration test/package test/internal/config test/internal/extensions test/internal/task test/app -v`
Expected: 全绿

- [ ] **Step 2: 核对冻结边界（本计划不得改动的目录无 diff）**

Run: `git status --short -- internal/handler internal/service internal/model internal/router package/response package/sqlalchemy`
Expected: 无输出（这些目录在本计划零改动）

- [ ] **Step 3: 写迁移进度记录**

```markdown
# 迁移进度（Flask → FastAPI）

## Plan 1（2026-08-28）：契约基线 + 异步基础设施 —— 完成
- [x] 153 路由清单（docs/migration/route-inventory.md）
- [x] 黄金响应样例（docs/migration/golden/）
- [x] requirements 移除 flask*/gevent/eventlet，引入 fastapi/uvicorn/asyncpg
- [x] settings 单例（pydantic-settings）
- [x] async DB（package/database.py）
- [x] Alembic async env
- [x] Redis/Weaviate/日志 bootstrap
- [x] Celery 独立化
- [x] FastAPI pilot（/healthz + /docs）

## Plan 2（未开始）：服务层 async 化（internal/service + internal/model + container.py）
## Plan 3（未开始）：Schema/Handler/Web 翻转（P3+P4+P2）
## Plan 4（未开始）：SSE/Celery 任务体/部署（P6+P7）
## Plan 5（未开始）：回归与切换（P8）
```

- [ ] **Step 4: 提交**

```bash
git add docs/migration/progress.md
git commit -m "docs(migration): Plan 1 完成记录，定义后续计划入口"
```

---

## Self-Review 备注

- **Spec 覆盖**：本计划覆盖 spec 的 P0（路由清单、认证分流表、响应契约、测试评估→路由清单+黄金样例）与 P1 中与业务解耦的部分（settings/async DB/Alembic/redis/weaviate/日志/celery/pilot）。spec P1 中"response 垫片、153 路由登记、零 Flask 依赖空应用"依赖服务层形态，因"无兼容垫片"约束移至 Plan 3（Web 翻转）——已在 Global Constraints 与 Task 9 接口注明。
- **占位符扫描**：全部步骤含真实代码/命令，无 TBD。
- **类型一致性**：`get_db()` 无参默认经 `set_default_session_factory` 注入；`build_engine(url=None)` 与测试注入 sqlite 的用法一致；`_async_url` 在 Task 5/6 复用，签名一致。
