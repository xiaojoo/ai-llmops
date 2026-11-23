# Plan 2: 服务层 async 化（P5 主战场）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 50+ 个 service、15 个 model 与 agent/workflow/记忆核心从"同步 Flask + Flask-SQLAlchemy + injector"全面转换为"async SQLAlchemy 2.0 + FastAPI DI（手工组合根）+ settings"，使 `internal/` 全部代码**零 flask 导入**、零 injector，为 Plan 3 的 Web 翻转铺平地基。

**Architecture:** 服务层统一 `async def`，`db: AsyncSession` 请求作用域注入（`get_db` 收口 commit/rollback）；`auto_commit` 上下文删除、写后同请求可见性用 `await flush()`；同步重活（torch/langchain/weaviate/chromadb/OCR）用 `run_in_threadpool` 桥接；后台线程（agent 执行、Celery）用 `asyncio.run` + 独立会话适配器；`flask.request`/`current_app` 替换为 request-context contextvar 与 settings 单例；injector 彻底移除，`internal/container.py` 手工组合根；模型迁移到 `package.database.Base`（列定义已是 `Mapped[]/mapped_column` 最新语法，只换基类）。

**Tech Stack:** async SQLAlchemy 2.0（AsyncSession/select()/Mapped[]）、pydantic-settings（已有）、FastAPI Depends（Plan 3 才挂路由，本计划只建组合根）、starlette `run_in_threadpool`、contextvars。

**Spec:** `docs/superpowers/specs/2026-08-28-flask-to-fastapi-design.md`
**Plan 1（已完成）:** `docs/superpowers/plans/2026-08-28-flask-to-fastapi-plan-1-foundation.md`（settings/package.database/extensions/celery_app 已就绪）
**进度记录:** `docs/migration/progress.md`

## Global Constraints

- 所有提交必须落在 `release_fastApi` 分支。
- **最新稳定版本 + 最新语法，不写兼容垫片**：`query()` 一律转 `select()`；模型保持 `Mapped[]/mapped_column`；AsyncSession 用 `execute/scalars/scalar/get`。
- **冻结面（本计划禁止修改）**：`internal/handler/*`、`internal/router/*`、`package/response/*`、`app/http/*`、`internal/schema/*`（FlaskForm 保持到 Plan 3）。handler 仍以 Flask 风格调用服务——**服务方法签名保持兼容**：接收的 `req`（FlaskForm）参数类型不变、方法名不变、返回类型不变，只把 `def` 改 `async def` 与内部 DB/IO 异步化。Plan 3 换 Pydantic 时再对齐签名（已记入账本地雷）。
- 数据库表结构不变；`internal/migrations/versions/*` 不动。
- 移除 `internal/` 下全部 `from flask`/`from flask_login`/`from flask_wtf`/`from flask_weaviate`/`from werkzeug` 导入（CI grep 门禁：`grep -rn "flask\|werkzeug" internal/ package/` 除注释外必须为 0）。
- 移除 injector：删除 `app/http/module.py`、全部 `@inject` 装饰器、`injector.get(...)`（3 处：app_task.py/demo_task.py/dataset_task.py/document_task.py 内、agent_queue_manager.py:37、app/http/app.py 已冻结——任务文件里的 `from app.http.module import injector` 由 Plan 4 重写，本计划先移除 `internal/core` 内的 `injector.get(Redis)` 一处，任务模块保留到 Plan 4）。
- 248 处 `db.session` 调用点全部 async 化；`auto_commit` 删除（提交由 `get_db` 在请求结束统一 commit；写后同请求读需 `await flush()`）。
- 同步库桥接：凡 torch/langchain/ltp/sentence-transformers/browser-use/weaviate 同步客户端/chromadb/OCR 调用，在 async 方法内用 `await run_in_threadpool(sync_fn, ...)`。
- 后台线程：一律 `asyncio.run` 包一层 + 独立会话（见规则手册 R17）。
- 测试：根 `test/conftest.py` 必须在本计划改造（地雷 #1：它仍导入冻结 Flask app，新 venv/CI 无法收集测试）；现有 `test/internal/service|model|core/*` 随服务 async 化逐个转 async 测试。
- werkzeug 已不在 requirements：`FileStorage` 全部替换（见规则手册 R18）。

## Global Transformation Rulebook（每个任务都必须遵守）

以下为服务层转换的统一规则；任务正文只列"本任务额外内容"，不再重复规则。

### R1 服务类改造
```python
# 前
from injector import inject
from dataclasses import dataclass
from package.sqlalchemy import SQLAlchemy

@inject
@dataclass
class AccountService:
    db: SQLAlchemy
    ...
    def get_account(self, account_id) -> Account:
        return self.db.session.execute(stmt).scalar_one_or_none()
```
```python
# 后
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession

@dataclass
class AccountService:
    db: AsyncSession
    ...
    async def get_account(self, account_id) -> Account:
        return (await self.db.execute(stmt)).scalar_one_or_none()
```
- 删 `from injector import inject` 与 `@inject`；`from package.sqlalchemy import SQLAlchemy` → `from sqlalchemy.ext.asyncio import AsyncSession`；`db: SQLAlchemy` → `db: AsyncSession`；方法 `def` → `async def`。

### R2 db.session 调用点（248 处）机械替换
| 现状 | 改为 |
|---|---|
| `self.db.session.execute(stmt)` | `await self.db.execute(stmt)` |
| `self.db.session.scalars(stmt)` | `await self.db.scalars(stmt)` |
| `self.db.session.scalar(stmt)` | `await self.db.scalar(stmt)` |
| `self.db.session.get(Model, pk)` | `await self.db.get(Model, pk)` |
| `self.db.session.query(Model).filter(...)` | `await self.db.scalars(select(Model).where(...))`（**query() 全转 select()**） |
| `self.db.session.add(x)` | `self.db.add(x)`（AsyncSession.add 是同步方法，不 await） |
| `self.db.session.delete(x)` | `await self.db.delete(x)`（异步） |
| `self.db.session.flush()` | `await self.db.flush()` |
| `self.db.session.commit()` | `await self.db.commit()`（仅限需要请求中途显式提交处） |
| `with self.db.auto_commit():` 块 | 删包装；块内写操作保留 `await flush()`（同请求后续读可见）；最终提交由 get_db |

注意：`stmt` 若为 `sqlalchemy.select(...)` 且无 `.where` 需求保持原样；`execute(stmt).scalars().all()` 可简化为 `await self.db.scalars(stmt)` 语义一致（是否简化以最小 diff 为准，不做顺手重构）。

### R3 current_app → settings
```python
from internal.config.settings import get_settings
settings = get_settings()
# current_app.config.get("ASSISTANT_AGENT_ID") → settings.assistant_agent_id
# current_app.root_path → settings.project_root（T1 新增字段，语义=仓库根绝对路径）
# app.extensions.get("default_llm") → 模块级单例或显式构造（见具体任务）
```

### R4 flask.request → request context
```python
from internal.core.request_context import get_request_context
ctx = get_request_context()
# request.remote_addr → ctx.remote_addr
# request.scheme → ctx.scheme；request.host → ctx.host
```
`request_context.py`（T1 创建）用 `ContextVar` 实现；Plan 3 由 FastAPI 依赖写入，本计划测试里直接 `set_request_context(...)`。

### R5 线程内 app_context → asyncio.run 适配器（package/database 新增，Plan 1 延迟项）
```python
# package/database.py 追加
async def _run_with_session(coro_factory: Callable[[AsyncSession], Awaitable[T]]) -> T:
    factory = get_default_session_factory()
    async with factory() as session:
        return await coro_factory(session)

def async_session_context(coro_factory: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """后台线程/Celery 任务体内调用（线程无运行中 loop，asyncio.run 自建）。"""
    return asyncio.run(_run_with_session(coro_factory))
```

### R6 同步重活桥接
```python
from starlette.concurrency import run_in_threadpool
result = await run_in_threadpool(sync_fn, *args)
```
适用：langchain 工具构造/调用、torch 推理、ltp、sentence-transformers、weaviate 同步客户端、chromadb、OCR、`requests`/`urllib` 网络调用。

### R7 模型基类与属性
```python
# 前
from internal.extension.database_extension import db
class Account(UserMixin, db.Model): ...
# 后
from package.database import Base
class Account(Base): ...   # UserMixin 删除（Plan 3 认证依赖不依赖它）
```
- 列定义（`Mapped[]/mapped_column`）**不动**。
- 模型内直接查库的 `@property`（如 `Account.assistant_agent_conversation`、`Dataset.document_count`、`Conversation.message_count`、`App.*`、`ApiKey.account` 等约 20 处）——属性不能 await，**上移为服务方法**（如 `AccountService.get_assistant_agent_conversation(account)`），或改为接收 `AsyncSession` 的类方法。模型退化为纯 ORM + 纯计算属性。

### R8 构造注入与 container.py
```python
# internal/container.py（T1 骨架，逐任务扩充）
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from package.database import get_db
from internal.service.account_service import AccountService

def get_account_service(session: AsyncSession = Depends(get_db)) -> AccountService:
    return AccountService(db=session)
```
- 请求作用域服务（依赖 session）→ Depends 工厂；无 session 服务（JwtService/CosService/MiniIoService/LanguageModelManager/FeishuService…）→ 模块级单例（构造一次）。
- FastAPI 同请求缓存保证每个 Depends 只构造一次。
- 后台线程/Celery 不用 Depends，直接 `AccountService(db=session)`（session 来自 R5 适配器）。

### R9 测试改造（conftest）
```python
# test/conftest.py（T1 重写，替代导入 Flask app 的旧版）
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from package.database import Base, build_engine, build_sessionmaker
from internal.config.settings import get_settings
from internal.service import JwtService

engine = build_engine()  # 真实 Postgres（沿用现有测试连真实库的约定）

@pytest.fixture
def settings_ctx(monkeypatch):
    ...

@pytest_asyncio.fixture
async def db_session():
    async with session_factory() as session:
        yield session
        await session.rollback()

@pytest.fixture
def access_token(db_session):
    account = (await db_session.execute(select(Account).limit(1))).scalar_one()
    return JwtService.generate_token({"sub": str(account.id), "iss": "llmops", "exp": ...})

@pytest_asyncio.fixture
async def account_service(db_session):
    return AccountService(db=db_session)
```
- 现有测试逐簇改造：`@pytest.mark.asyncio` + `await service.method(...)`；`with app.app_context()` 移除。
- 事务隔离沿用旧约定：真实库 + 每测试 rollback。

## 任务与批量划分

依赖序：T1 → T2 → T3；T4 依赖 T1/T2；T5/T6/T7 依赖 T4 的模式与 T3 的 request/settings 替换；T8 依赖 T5/T6/T7（agent/工作流引用它们）；T9 收尾。

---

### Task 1: 地基——package.database 增强 + request_context + container 骨架 + 示例转换

**Files:**
- Modify: `package/database.py`（加 R5 的 `async_session_context`/`_run_with_session`；`get_db` 已有）
- Create: `internal/core/request_context.py`（R4）
- Modify: `internal/config/settings.py`（加 `project_root: str` 字段——`Path(__file__).resolve().parents[2]` 计算，`model_config` 内 `populate_by_name=True` 以便直接传值；字段默认即仓库根）
- Create: `internal/container.py`（骨架：`get_account_service`、`get_jwt_service` 单例、`get_api_key_service`、`get_db` 转发）
- Modify: `internal/service/base_service.py`（R1/R2 首个转换——`create/delete/update/get` 全 async）
- Modify: `internal/service/jwt_service.py`（无 session，保持 classmethod 或转单例；删 `@inject`）
- Test: `test/package/test_database.py`（+async_session_context 测试）、`test/internal/core/test_request_context.py`、`test/internal/config/test_settings.py`（+project_root）、`test/internal/service/test_base_service.py`（新）

**Interfaces:**
- Produces: `async_session_context(coro_factory) -> T`；`get_request_context()/set_request_context()/reset_request_context()`；`settings.project_root`；`container.get_account_service` 等；`BaseService.create/delete/update/get`（async）。

- [ ] **Step 1: 写失败测试**（每文件）：async_session_context 在内存 sqlite 引擎上跑插入+查询（复用 T5 的 build_engine 注入模式，注意 `get_default_session_factory` 需先 set）；request_context 的 set/get/reset；settings.project_root 为仓库根；base_service async CRUD。
- [ ] **Step 2: 运行确认失败**（`ModuleNotFoundError`/`AttributeError`）。
- [ ] **Step 3: 实现**（R3/R4/R5/R8 代码）。
- [ ] **Step 4: 运行确认通过**：`pytest test/package/test_database.py test/internal/core/test_request_context.py test/internal/config/test_settings.py test/internal/service/test_base_service.py -v`。
- [ ] **Step 5: 提交**：`feat(core): request_context contextvar + async_session_context 线程适配 + settings.project_root + container 骨架 + BaseService async 化`。

---

### Task 2: 模型层迁移（15 个 model 文件）

**Files:**
- Modify（全部 model）：`internal/model/account.py`（含 UserMixin 移除、assistant_agent_conversation 属性上移）、`api_key.py`、`api_tool.py`、`app.py`、`conversation.py`、`dataset.py`、`end_user.py`、`episodic_memory.py`、`procedural_memory.py`、`skill.py`、`sub_task_checkpoint.py`、`system_config.py`、`upload_file.py`、`user_memory.py`、`workflow.py`（R7：`db.Model`→`Base`；`from internal.extension.database_extension import db`→`from package.database import Base`）
- Modify: `internal/model/__init__.py`（无变化或仅注释）
- Test: `test/internal/model/*`（现有模型测试转 async 或适配新结构）

**Interfaces:**
- Consumes: `package.database.Base`
- Produces: 纯 ORM 模型；`internal/extension/database_extension.py` 仅剩 `internal/migrations/env.py` 过渡引用（本计划保留该文件，Plan 3 移除）；属性查库上移点清单（写入 `docs/migration/model-session-callers.md` 供服务任务参考）。

- [ ] **Step 1: grep 基线**：`grep -rn "db.session\|db.auto_commit\|current_app\|UserMixin" internal/model/` → 记录每处调用点（约 20 处属性/方法）。
- [ ] **Step 2: 逐文件转换**：基类替换；属性内查库方法上移为（新）服务方法并在 `docs/migration/model-session-callers.md` 登记"原属性 → 新服务方法"映射（Plan 3 的 handler 不再访问这些属性）。
- [ ] **Step 3: 测试**：现有 `test/internal/model/*` 转 async（继承 `Base` 后实例化/查询测试）；新增断言"internal/model 无 db.session / flask / werkzeug / current_app"（grep 门禁测试）。
- [ ] **Step 4: 运行**：`pytest test/internal/model test/migration -v` 全绿。
- [ ] **Step 5: 提交**：`refactor(model): 迁移到 package.database.Base（async 纯 ORM），属性查库上移服务层`。

---

### Task 3: 服务层 flask 依赖清除（request/current_app/FileStorage/weaviate）

**Files:**
- Modify: `internal/service/account_service.py`（request.remote_addr→ctx）、`oauth_service.py`（同）、`app_service.py`（request.scheme/host→ctx；FileStorage→适配）、`app_config_service.py`（scheme/host→ctx）、`workflow_service.py`（scheme/host→ctx）、`skill_service.py`（send_file→FileResponse 或纯 bytes 返回，Plan 3 handler 决定；本任务改为返回 `(bytes, mimetype)` 或保持 bytes）、`builtin_tool_service.py`（root_path→settings.project_root）、`language_model_service.py`（root_path→project_root）、`assistant_agent_service.py`（ASSISTANT_AGENT_ID→settings）、`retrieval_service.py`（`from flask import Flask`→删/Any）、`vector_database_service.py`、`weaviate_vector_service.py`（FlaskWeaviate→`internal.extensions.weaviate.weaviate_client` 单例 + run_in_threadpool）
- Modify（FileStorage，R18）: `cos_service.py`、`miniio_service.py`、`chroma_file_service.py`、`skill_service.py`、`app_service.py`、`internal/core/tools/builtin_tools/providers/pptx/markdown_to_pptx.py`
- Modify: `internal/schema/weaviate_vector_schema.py`（`werkzeug.datastructures.ImmutableMultiDict`——冻结面冲突！见下）
- Test: `test/internal/service/test_*`（涉及文件的服务测试转 async + 新断言）

**关键裁决（写入本任务）**：`internal/schema/*` 冻结至 Plan 3，但 `weaviate_vector_schema.py:22` 引用了 werkzeug 的 `ImmutableMultiDict`。**本任务以最小改动解除编译依赖**：该 import 改为 `from sqlalchemy import ...` 不需要；实际只需类型标注——改为 `dict`/`Any` 类型并保留行为（该文件其他部分不动）。若改动超出最小范围则上报控制器。

**FileStorage 替换方案（R18 具体化）**：请求文件（handler 传入，Plan 3 前仍是 werkzeug FileStorage 对象——但 werkzeug 包已移出 requirements，**本计划内 handler 冻结，其传入的文件对象来自旧 Flask**——过渡期该类型标注改为 `Any` 或定义 `package/file_storage.py` 最小协议类 `(name, content_type, stream)`，仅作类型标注用，**不实现兼容行为**）；服务内部包装流（`FileStorage(io.BytesIO(...), filename=...)`）→ 定义 `package/file_storage.py` 的轻量数据类 `NamedBytesIO(name, data)` 或直接传 `(bytes, filename)` 元组给 COS SDK。COS SDK 上传只认 file-like + key，包装类只为带 filename。

- [ ] **Step 1: grep 基线**：`grep -rn "flask\|werkzeug\|FlaskWeaviate" internal/service internal/core/tools | grep -v test`。
- [ ] **Step 2: 逐文件替换**（R3/R4/R18）。
- [ ] **Step 3: 测试**：受影响服务现有测试转 async；新增 `test/migration/test_no_flask_imports.py`（grep 断言：`internal/` 下无 `from flask`、`from werkzeug`、`flask_weaviate`、`injector` 导入，`internal/service`、`internal/model`、`internal/core` 三个目录范围；`internal/handler`、`internal/router`、`internal/schema`、`app/http` 豁免）。
- [ ] **Step 4: 运行**：`pytest test/internal/service test/migration -v`（本任务涉及部分）+ 门禁测试。
- [ ] **Step 5: 提交**：`refactor(service): 清除服务层 flask/werkzeug 依赖（request ctx / settings / FileStorage 适配 / weaviate 单例）`。

---

### Task 4: 认证与账号簇 async 化

**Files:**
- Modify: `internal/service/account_service.py`、`api_key_service.py`、`jwt_service.py`、`base_service.py`（T1 已做）、`oauth_service.py`、`system_config_service.py`（apply_to_env 由 lifespan 调用，转 async + 独立会话）
- Modify: `internal/service/__init__.py`（无结构变化）
- Test: `test/internal/service/test_account_service.py`（新，覆盖 get_account/get_by_credential/update_password 等核心方法）、现有相关测试转 async

**Interfaces:**
- Produces: 全部 async 签名（`async def get_account(account_id) -> Account` 等）；`ApiKeyService.get_api_by_by_credential` async。
- Consumes: T1 的 container 骨架、T2 的模型、T3 的 ctx/settings。

- [ ] **Step 1-4**: 按 R1/R2/R4 转换 + 测试（认证服务测试：真实库 + access_token fixture）。
- [ ] **Step 5: 提交**：`refactor(service): 认证/账号簇 async 化`。

---

### Task 5: App 簇 async 化

**Files:**
- Modify: `internal/service/app_service.py`（1130 行，最大；含 FileStorage 已由 T3 处理、debug_chat 相关服务调用链）、`app_config_service.py`、`builtin_app_service.py`、`assistant_agent_service.py`、`language_model_service.py`（root_path 已由 T3 处理；load_language_model 同步 LLM 调用桥接 run_in_threadpool 视需要）
- Test: `test/internal/service/test_app_service_draft_config.py`、`test_app_service_publish_orchestrator.py`、`test_app_logical_delete.py`、`test_app_config_skill_tool.py`、`test_app_config_transformer.py`、`test_ask_user_chat_runner.py` 等转 async

**注意**：`app_service.py` 内 `AgentQueueManager` 相关与 chat 调用链（`debug_chat`）依赖 T6/T8 的 chat/agent 服务——本任务把 app_service 的**非 chat 部分** async 化；chat 相关方法若依赖未转换的服务，标记 `# TODO(plan2-chat): 待 T6/T8 后 async 化` 并在 T8 收口（记录于 `docs/migration/progress.md`）。

- [ ] **Step 1-4**: 转换 + 测试。
- [ ] **Step 5: 提交**：`refactor(service): app 簇 async 化（app/app_config/builtin_app/assistant_agent/language_model）`。

---

### Task 6: 会话/对话簇 async 化

**Files:**
- Modify: `internal/service/conversation_service.py`（app_context 线程块→R5 适配器；`flask_app` 参数删除）、`chat_runner.py`（`flask_app=current_app._get_current_object()` 传参→settings/删；SSE 生成器保持同步生成器形态，由 Plan 3 的 StreamingResponse 承接）、`choice_service.py`、`open_api_service.py`、`web_app_service.py`、`analysis_service.py`、`internal/memory/token_buffer_memory.py`、`internal/core/memory/token_buffer_memory.py`
- Test: `test_chat_runner.py`、`test_chat_runner_orchestrator.py`、`test_ask_user_chat_runner.py`、`test_chat_error_handling.py`、`test_conversation_compact.py`、`test_conversation_delete_checkpoints.py`、`test_conversation_service.py`、`test_choice_service.py`、`test_token_buffer_memory.py` 转 async

**关键设计**：chat_runner 的 `run()` 是 SSE 生成器（同步生成器 + 内部 DB 调用）。async 化方案：`run()` 改为 `async def` 或保持同步生成器但内部 DB 调用改为"同步会话桥"？**裁决**：保持 `run()` 为同步生成器（Plan 3 由 StreamingResponse 在线程池迭代），内部 DB 访问改为经 `async_session_context` 的同步桥或注入的 session 工厂——具体以最小改动力求正确性：若 `run()` 内部 DB 调用点多，改为 `async def run()` 返回 async generator，Plan 3 直接接 StreamingResponse；本任务内先行确定并记录于 progress.md。

- [ ] **Step 1-4**: 转换 + 测试（SSE 生成器行为对比旧逻辑：事件序列一致）。
- [ ] **Step 5: 提交**：`refactor(service): 会话/对话簇 async 化（conversation/chat_runner/open_api/web_app/analysis）`。

---

### Task 7: 知识库簇 async 化

**Files:**
- Modify: `internal/service/dataset_service.py`、`document_service.py`、`indexing_service.py`、`segment_service.py`、`retrieval_service.py`（`flask_app` 参数→settings；langchain 工具构造桥接）、`keyword_table_service.py`、`process_rule_service.py`、`embeddings_service.py`、`ltp_service.py`、`vector_database_service.py`、`weaviate_vector_service.py`（同步 weaviate 客户端→run_in_threadpool）、`chroma_service.py`、`chroma_file_service.py`、`chroma_vector_service.py`、`attachment_service.py`、`upload_file_service.py`、`cos_service.py`、`miniio_service.py`
- Test: `test_retrieval_service_agentic_tool.py`、`test_vector_database_service.py` 等转 async；`test/internal/core/retrievers/*`（bm25/full_text/semantic/rrf/rerank——同步纯逻辑，可不 async，仅确认无 flask 依赖）

**注意**：`internal/core/retrievers/*` 为纯同步逻辑（无 flask），**不转 async**；调用它们的服务（retrieval_service）在 async 方法内 `run_in_threadpool` 桥接。`internal/core/embeddings/*` 同理（torch 同步）。

- [ ] **Step 1-4**: 转换 + 测试。
- [ ] **Step 5: 提交**：`refactor(service): 知识库簇 async 化（dataset/document/indexing/segment/retrieval/vector）`。

---

### Task 8: 工作流/Agent/记忆簇 async 化（含线程适配）

**Files:**
- Modify: `internal/service/workflow_service.py`、`sub_task_service.py`、`user_memory_service.py`、`episodic_memory_service.py`、`procedural_memory_service.py`、`reflection_service.py`、`service/memory_provider/*`（builtin/tencent/base/resolver/tencent_client）、`internal/core/agent/agents/*`（base_agent.py:194、orchestrator_agent.py:306 的 `has_app_context`/app_context 分支→R5）、`internal/core/workflow/*`（workflow.py:111 flask_app 参数）、`internal/core/tools/memory_tools.py`（4 处 app_context→R5）、`internal/core/tools/builtin_tools/providers/browser/browser.py`（`current_app.extensions.get("default_llm")`→settings/单例）
- Test: `test/internal/core/agent/*`、`test/internal/core/workflow/*`、`test/internal/core/tools/test_memory_tools.py`、`test/internal/service/*memory*`、`test/internal/service/memory_provider/*` 转 async 或适配（agent 核心多为同步编排——**保持同步**，只替换 flask 依赖；其内部 DB 访问经注入的 AsyncSession 或 R5 适配器）

**关键裁决**：agent 编排（langchain/langgraph）保持同步函数形态（spec §5.2）；它运行在后台线程（AgentQueueManager 线程），线程内用 `asyncio.run(async_session_context(...))` 提供会话。`base_agent.py`/`orchestrator_agent.py` 的 `flask_app` 变量删除，改为直接使用注入的 `db: AsyncSession`（同线程内可同步调用？——AsyncSession 不能跨线程/跨 loop 使用；**线程内会话必须是该线程 asyncio.run 内创建的**。故 agent 同步代码内的 DB 访问需经"同步代理"：`run_in_threadpool` 不适用（已在线程）；用 `asyncio.run_coroutine_threadsafe`？复杂。**最终方案**：agent 线程改为"同步为主、DB 走 `async_session_context` 内再包同步逻辑"——即把 agent 执行体放进 `async_session_context(lambda session: run_agent_sync(agent, session))`，让 session 在 asyncio.run 的 loop 内可用；agent 内同步代码对 session 的调用经 `await` 不可行 → 改为 agent 内用 `run_sync` 辅助（`sqlalchemy.ext.asyncio` 无此 API）……**若出现此深层矛盾，停止并上报控制器**（可能需将 agent 编排改为 async 或引入 greenlet 桥）。T8 先做 workflow/memory 服务与 memory_tools 的机械替换，agent 线程深水区单列子任务并标注风险。

- [ ] **Step 1-4**: 转换 + 测试；风险点如实上报。
- [ ] **Step 5: 提交**：`refactor(core): workflow/记忆/agent 簇 async 化与线程适配`。

---

### Task 9: 剩余服务 + injector 彻底移除 + 门禁与回归

**Files:**
- Modify: `internal/service/audio_service.py`、`skill_service.py`、`feishu_service.py`、`ai_service.py`、`api_tool_service.py`、`builtin_tool_service.py`（核心已 T3）、`attachment_service.py`（如 T7 未覆盖）
- Modify: `internal/core/agent/agents/agent_queue_manager.py:37`（`injector.get(Redis)`→`internal.extensions.redis.sync_redis_client` 或初始化注入）
- Delete: `app/http/module.py`（injector 容器——确认无引用后删除；`app/http/app.py` 冻结引用它 → app.py 属 Plan 3 替换对象，本任务确认删除不破坏 import 即可，app.py 本身冻结）
- Test: 全量 `test/`（本计划范围）转 async 后跑绿；`test/migration/test_no_flask_imports.py` 扩展为全 `internal/`+`package/` 门禁（豁免清单：`internal/handler`、`internal/router`、`internal/schema`、`app/http`、`internal/task`、`internal/migrations`）

**门禁（CI 或本任务命令）**：
```bash
grep -rn "from flask\|import flask\|from werkzeug\|from injector\|@inject\|injector\." internal/ package/ | grep -v "test" | grep -v "internal/handler" | grep -v "internal/router" | grep -v "internal/schema" | grep -v "app/http" | grep -v "internal/task" | grep -v "internal/migrations"
# 输出必须为空
```

- [ ] **Step 1-4**: 转换 + 门禁 + 全量回归（`pytest test/migration test/package test/internal/config test/internal/extensions test/internal/task test/app test/internal/service test/internal/model test/internal/core test/internal/schema -q`——注意 test/internal/schema 仍依赖 FlaskForm，Plan 3 前保持通过或标记 skip）。
- [ ] **Step 5: 提交**：`refactor(core): 移除 injector 与全部 flask 依赖（服务层 async 化完成）` + 更新 `docs/migration/progress.md`（Plan 2 完成、Plan 3 入口）。

---

## 验收标准（Done 定义）

1. `internal/service|model|core` 下 `grep flask|werkzeug|injector` 为 0（豁免清单见 T9）；`app/http/module.py` 已删除且全仓库无 `injector` 引用（`internal/task` 除外，Plan 4 处理）。
2. 248 处 `db.session` 调用点全部转为 async；`auto_commit` 在 `internal/` 下为 0（`package/` 下无残留）。
3. 全部服务方法为 `async def`（除 agent 编排等明确保持同步的），签名/返回与旧版兼容（handler 冻结可继续调用——handler 仍同步调用会失败！**注意**：handler 冻结 = 同步调用 async 服务会报错。**这是 Plan 2→Plan 3 的已知接缝**：本计划完成时旧 Flask app 已无法运行 handler（可接受，app 已冻结）；`test/internal/handler/*` 与 `test/internal/schema/*` 标记 `@pytest.mark.skip(reason="plan3")` 或暂存，Plan 3 重写）。
4. 全量可运行测试绿（旧 handler/schema 测试 skip 除外）；门禁测试通过。
5. 全部提交落 `release_fastApi`。

## Self-Review 备注

- **Spec 覆盖**：对应 spec P5（服务层 async 化全部内容）+ 移除 injector（§5.5）+ settings/root_path（§5.6）+ 线程适配（§5.1）。
- **占位符**：转换规则 R1-R9 为完整 before/after 代码；任务仅列额外内容；深水区（agent 线程 async/sync 矛盾）已在 T8 明示"上报控制器"，非隐藏占位。
- **接缝声明**：handler 冻结与 async 服务之间的调用接缝、schema 冻结与 werkzeug 引用的最小改动，均为已记录的已知决策（可回滚成本低）。
- **与 Plan 3 的接口**：container.py 的 Depends 工厂即 Plan 3 路由依赖来源；request_context 由 Plan 3 的 FastAPI 依赖写入；FileStorage 适配类型在 Plan 3 换 `UploadFile`。
