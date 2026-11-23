# Plan 2.1: 服务层 async 化（P5 主战场）— 评审修订版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 50+ 个 service、15 个 model 与 agent/workflow/记忆核心从"同步 Flask + Flask-SQLAlchemy + injector"全面转换为"async SQLAlchemy 2.0 + 纯工厂组合根 + settings"，使 `internal/` 全部代码**零 flask/werkzeug/injector 导入**，为 Plan 3 的 Web 翻转铺平地基。

**本计划取代** `docs/superpowers/plans/2026-08-28-flask-to-fastapi-plan-2-service-async.md`（经两份外部评审修订：事务边界显式化、Agent async 化方案确定、container 纯工厂化、handler 测试统一跳过、fixture 修正、FileStorage 简化）。

**Architecture:** 服务层统一 `async def` + `db: AsyncSession`；事务分三类（见"事务模型"）：请求事务（get_db 兜底提交）、独立事务（原 auto_commit 块尾真实 `await commit()`，语义保持）、Worker 事务（后台线程/Celery 的 loop 内会话，`commit_on_success=True` 默认）。agent 编排 **async 化**（方案 A），同步库（langchain/torch/browser）经 `run_in_threadpool` + 并发信号量桥接；后台线程用 `asyncio.run` 起独立事件循环承载 agent/任务，AsyncSession 只在 loop 内创建与使用。`internal/container.py` 为纯 Python 工厂（不依赖 FastAPI），Web 侧 Depends 薄适配层留给 Plan 3。模型迁移到 `package.database.Base`（列定义已是 `Mapped[]/mapped_column`，只换基类），属性查库全部上移服务层。

**Tech Stack:** async SQLAlchemy 2.0（AsyncSession/select()/Mapped[]）、pydantic-settings（已有）、`starlette.concurrency.run_in_threadpool`、`asyncio`/`contextvars`、pytest-asyncio（已有）。

**Spec:** `docs/superpowers/specs/2026-08-28-flask-to-fastapi-design.md`
**Plan 1（已完成）:** `docs/superpowers/plans/2026-08-28-flask-to-fastapi-plan-1-foundation.md`
**进度记录:** `docs/migration/progress.md`（**每个任务结束必须更新**）

## 迁移状态声明（破坏性，必须写进执行者认知）

**Plan 2 完成时，旧 Flask Web 应用不可运行——这是预期迁移状态，不是 Plan 2 的失败。** 原因：handler/router/schema 冻结至 Plan 3，而服务层全部 `async def`；handler 同步调用 async 服务会在运行时失败。Plan 3 必须紧接着完成恢复可用。`test/internal/handler/*` 与 `test/internal/schema/*` 在 T1 统一模块级 skip（见 R9），**skip 计数为 0 是可接受的完成态**。

## Global Constraints

- 所有提交必须落在 `release_fastApi` 分支。
- **最新稳定版本 + 最新语法，不写兼容垫片**：`query()` 一律转 `select()`；模型保持 `Mapped[]/mapped_column`；AsyncSession 用 `execute/scalars/scalar/get`。
- **冻结面（本计划禁止修改）**：`internal/handler/*`、`internal/router/*`、`package/response/*`、`app/http/*`、`internal/schema/*`（FlaskForm 保持到 Plan 3）。服务方法**签名/名称/返回类型保持兼容**（handler 在 Plan 3 前不被调用），只把 `def`→`async def` 与内部 DB/IO 异步化。
- 数据库表结构不变；`internal/migrations/versions/*` 不动。
- **事务规则**（详见"事务模型"）：原 `auto_commit` 块尾保留真实 `await commit()`（独立事务边界，语义保持）；除此之外服务不得随意 commit；get_db 请求尾提交为兜底；flush 只在需要 DB 生成值/FK/约束验证/当前事务内立即读取时使用。
- 248 处 `db.session` 调用点全部 async 化；`auto_commit` 在 `internal/` 下归零。
- 同步重活（torch/langchain/ltp/sentence-transformers/browser-use/weaviate 同步客户端/chromadb/OCR/网络 IO）在 async 方法内 `await run_in_threadpool(...)`；**模型/推理类调用必须配并发限制器**（`anyio.CapacityLimiter`，默认并发 2，跨事件循环安全），禁止无保护并发进模型。**推理设备可配置（cpu | cuda | mps，由 settings 驱动——`embedding_device` 已有，T1 新增 `rerank_device` 等）**；GPU 路径经 CapacityLimiter 序列化保护（模型线程安全）。不引入独立推理进程/Executor——设备切换与限流已覆盖 CPU/GPU；仅当 GPU 规模化需要排队/批处理时再评估。
- 后台线程/Celery：`worker_run()`（R5）——`asyncio.run` 独立 loop + loop 内 AsyncSession + 默认 `commit_on_success=True`；AsyncSession 不逃逸 loop。
- 移除 injector：删 `@inject`、`app/http/module.py`、`injector.get(...)`（`internal/core/agent/agents/agent_queue_manager.py:37` 本计划处理；`internal/task/*` 与冻结的 `app/http/app.py` 引用由 Plan 4 处理）。
- 测试：根 `test/conftest.py` 在 T1 重写（不再导入 Flask app）；handler/schema 测试统一 skip；门禁测试 `test_no_flask_imports.py` 仅在 T9 启用（`@pytest.mark.slow`）。
- werkzeug 已不在 requirements：FileStorage 全部替换（R11）。

## 事务模型（三分类，T1 起生效）

| 类型 | 生命周期 | commit 归属 | 适用 |
|---|---|---|---|
| **Request Transaction** | FastAPI 请求（Plan 3）→ `get_db()` yield 的 AsyncSession；本计划内为测试/后台入口直接使用 | 兜底：get_db 成功时 `await session.commit()`；失败 rollback | 普通读写请求；服务内**不** commit（除非显式边界） |
| **Independent Transaction** | 原 `auto_commit` 块范围 | **块尾 `await self.db.commit()`**（真实提交，位置与旧代码一致）；异常由外层（get_db/worker_run）rollback | 长任务进度落库、请求→后台可见性（agent 线程读请求已写数据）、旧代码每个 auto_commit 块 |
| **Worker Transaction** | 后台线程/Celery → `worker_run(coro_factory, commit_on_success=True)` 的 loop 内会话 | 默认成功后 commit；异常 rollback；内部可再显式 commit | agent 线程、Celery 任务、内存服务后台写 |

**硬规则**：
1. `await self.db.commit()` 出现的位置 = 已声明的事务边界；T2 起每处 commit 必须在 `docs/migration/transaction-boundaries.md` 登记（文件+行+理由），审查时逐处核对，禁止新增无登记 commit。
2. flush 只在需要 DB 生成值/FK/约束验证/当前事务内立即读取时使用（`add()` 后无依赖时不 flush）。
3. AsyncSession **禁止**跨线程、跨事件循环使用；线程内会话只能由该线程的 `worker_run` 创建。

## Global Transformation Rulebook（每个任务都必须遵守）

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
删 `@inject`；`package.sqlalchemy.SQLAlchemy` → `sqlalchemy.ext.asyncio.AsyncSession`；方法 `def` → `async def`。返回类型不变（调用方 await）。

### R2 db.session 调用点（248 处）机械替换
| 现状 | 改为 |
|---|---|
| `self.db.session.execute(stmt)` | `await self.db.execute(stmt)` |
| `self.db.session.scalars(stmt)` | `await self.db.scalars(stmt)` |
| `self.db.session.scalar(stmt)` | `await self.db.scalar(stmt)` |
| `self.db.session.get(Model, pk)` | `await self.db.get(Model, pk)` |
| `self.db.session.query(Model).filter(...)` | `await self.db.scalars(select(Model).where(...))`（query() 全转 select()） |
| `self.db.session.add(x)` | `self.db.add(x)`（**AsyncSession.add 是同步方法，不 await**——await 是运行时静默 bug） |
| `self.db.session.delete(x)` | `await self.db.delete(x)`（异步，必须 await） |
| `self.db.session.flush()` | `await self.db.flush()`（仅按事务模型规则 2 保留） |
| `self.db.session.commit()`（模型内/显式） | `await self.db.commit()`（= 独立事务边界，登记） |
| `with self.db.auto_commit():` 块 | **块内写操作保留 + 块尾 `await self.db.commit()`**（独立事务边界，登记）；异常回滚由外层兜底 |

> **P2.1.1-1 注记**：本表以当前安装的 SQLAlchemy 版本（2.0.52）实际 API 为准。T1 时用 `inspect.signature(AsyncSession.add/delete/flush/... )` 核验一遍并记录结论；若配置类型检查器（pyright/mypy），`await` 同步方法 与 未 `await` 协程 均为类型错误，作为兜底验证。表格保留以便实现者速查。

`auto_commit` 块转换示例（**语义保持**）：
```python
# 前
with self.db.auto_commit():
    self.db.session.add(app)
    self.db.session.flush()
# 后
self.db.add(app)
await self.db.flush()      # 原块内 flush 保留
await self.db.commit()     # 独立事务边界（登记）
```
大文件（T5 app_service 等）**允许按方法拆分转换**，每个方法一个 commit（progress.md 记录"重构不改变行为"的方法清单），便于逐项审查。

### R3 current_app → settings
```python
from internal.config.settings import get_settings
settings = get_settings()
# current_app.config.get("ASSISTANT_AGENT_ID") → settings.assistant_agent_id
# current_app.root_path → settings.project_root（T1 新增；实现：Path(__file__).resolve().parents[2]，
#   加注释：pyinstaller/打包环境下失效，需显式环境变量覆盖）
# app.extensions.get("default_llm") → 显式构造/模块级单例（见具体任务）
```

### R4 flask.request → request context（ContextVar）
```python
from internal.core.request_context import get_request_context
ctx = get_request_context()
# request.remote_addr → ctx.remote_addr
# request.scheme → ctx.scheme；request.host → ctx.host
```
`request_context.py`（T1）用 `ContextVar`；Plan 3 由 FastAPI 依赖写入；本计划测试直接 `set_request_context(...)`。

### R5 后台线程 / Worker 事务适配器（重写 package/database 的延迟项）
```python
# package/database.py 追加（T1 实现）
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

async def _run_worker(coro_factory: Callable[[AsyncSession], Awaitable[T]], *, commit_on_success: bool = True) -> T:
    factory = get_default_session_factory()
    async with factory() as session:
        try:
            result = await coro_factory(session)
            if commit_on_success:
                await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise

def worker_run(coro_factory: Callable[[AsyncSession], Awaitable[T]], *, commit_on_success: bool = True) -> T:
    """后台线程/Celery 任务体内调用（同步入口）：asyncio.run 独立事件循环 + 循环内 AsyncSession。

    P2.1.1-3：禁止从运行中的事件循环调用（asyncio.run 会抛难懂的错误）——显式守卫：
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # 无运行中 loop（线程/同步入口）——预期路径
    else:
        raise RuntimeError(
            "worker_run 只能从同步入口（线程/Celery）调用；当前处于运行中的事件循环，请直接 await 协程"
        )
    return asyncio.run(_run_worker(coro_factory, commit_on_success=commit_on_success))
```

**Agent 线程机制（方案 A，T8 落地）：**
```
Worker Thread (AgentQueueManager worker)
   └─ worker_run(agent_main)                  # asyncio.run → 独立 loop
        └─ async def agent_main(session):
             └─ await orchestrator.run(session, ...)   # agent 编排全 async
                  ├─ await service.method(session, ...) # 会话在本 loop 内，合法
                  └─ await run_in_threadpool(llm.invoke, ...)  # 同步库桥
```
线程内 Redis 队列监听/发布（AgentQueueManager.listen/publish）保持同步原样。

### R6 同步重活桥接（含并发控制，P2.1.1-2 修订版）
```python
from anyio import CapacityLimiter, to_thread

# 模型/推理并发限制：基于线程的 CapacityLimiter，跨事件循环安全。
# 禁止用模块级 asyncio.Semaphore——它绑定事件循环，请求 loop 与 agent worker loop
# 双 loop 共享会抛 "bound to a different event loop"；loop-local 方案又无法全局限流。
_MODEL_LIMITER = CapacityLimiter(2)  # 进程级，限线程池并发

async def _infer(sync_fn, *args):
    return await to_thread.run_sync(sync_fn, *args, limiter=_MODEL_LIMITER)
```
适用：langchain/LLM 调用、torch/ltp/sentence-transformers、weaviate 同步客户端、chromadb、OCR、`requests`/`urllib`。纯 IO/轻量同步调用可不用限制器。

**设备可配置（用户需求，settings 驱动）**：推理设备（cpu | cuda | mps）由 settings 字段控制——`embedding_device`（已有）、`rerank_device`（T1 新增，默认 "cpu"）；ltp 等按需补。模型加载/推理处按 `settings.<x>_device` 做 torch 设备放置；GPU 路径先 `torch.cuda.is_available()` 校验，经 `_MODEL_LIMITER` 序列化（模型线程安全）。**服务读取设备统一走 settings**：如 `internal/core/embeddings/embedding_provider.py:113` 现为 `os.getenv("EMBEDDING_DEVICE", "cpu")` → 改为 `get_settings().embedding_device`（T3 处理；DB 侧 system_config 注入的 `EMBEDDING_DEVICE` 经 `apply_to_env` 进 os.environ 仍生效，但读取点统一收口 settings）。

### R7 模型基类与属性上移
```python
# 前
from internal.extension.database_extension import db
class Account(UserMixin, db.Model): ...
# 后
from package.database import Base
class Account(Base): ...   # UserMixin 删除（Plan 3 认证依赖不依赖它）
```
- 列定义（`Mapped[]/mapped_column`）不动；`__table_args__` 不动。
- 模型内查库的 `@property`（约 20 处：`Account.assistant_agent_conversation`、`Dataset.document_count`、`Conversation.message_count`、`App.*`、`ApiKey.account` 等）——属性不能 await（async ORM 下 lazy loading 会 MissingGreenlet）——**全部上移为服务方法**（如 `AccountService.get_assistant_agent_conversation(account)`），登记到 `docs/migration/model-session-callers.md`（原属性 → 新服务方法映射，Plan 3 handler 不再访问这些属性）。
- 确认：`package.database.Base` 是**单一 DeclarativeBase 实例**，metadata 全局唯一；T2 模型迁移后 `internal/migrations/env.py` 的 `target_metadata` 切换到 `Base.metadata`（原 `db.metadata` 过渡引用随之消除）。

### R8 组合根：纯工厂（不依赖 FastAPI）
```python
# internal/container.py（T1 骨架，逐任务扩充；禁止 import fastapi）
from sqlalchemy.ext.asyncio import AsyncSession
from internal.service.account_service import AccountService

def create_account_service(session: AsyncSession) -> AccountService:
    return AccountService(db=session)

# 无 session 服务 → 模块级单例
jwt_service = JwtService()   # 或 create_jwt_service()（构造一次）

# Web 侧 Depends 薄适配层（Plan 3 的 internal/server/ 实现，本计划不建）：
# async def get_account_service(session: AsyncSession = Depends(get_db)):
#     return create_account_service(session)
```
后台线程/Celery 直接 `create_account_service(session)`（session 来自 worker_run）。

### R9 测试改造
```python
# test/conftest.py（T1 重写——不再导入 app.http.app；真实 Postgres）
# P2.1.1：engine/sessionmaker 模块级创建一次（避免每测试重建引擎），
# db_session 用 connection+begin+rollback 隔离模式（沿用旧 conftest 语义）。
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from package.database import build_engine, build_sessionmaker
from internal.model import Account
from internal.service import JwtService

_engine = build_engine()
_factory = build_sessionmaker(_engine)

@pytest_asyncio.fixture
async def db_session():
    conn = await _engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()

@pytest_asyncio.fixture
async def access_token(db_session):
    account = (await db_session.execute(select(Account).limit(1))).scalar_one()
    return JwtService.generate_token({"sub": str(account.id), "iss": "llmops", "exp": 4102444800})
```
```python
# test/internal/handler/__init__.py 与 test/internal/schema/__init__.py（T1 加，统一跳过）
import pytest
pytest.skip("Plan2 过渡期：handler/schema 层冻结，待 Plan3 重写", allow_module_level=True)
```
- 现有服务/模型测试逐簇转 `@pytest.mark.asyncio` + `await`；`with app.app_context():` 移除。
- 门禁测试 `test/migration/test_no_flask_imports.py`：本计划**只在 T9 启用**（装饰 `@pytest.mark.slow` 或在 T9 前由 conftest 的 `PLAN2_GATES` 环境变量关闭），避免 CI 全程红。

### R10 Agent async 化细则（方案 A，T8 专用）
- agent 编排（`internal/core/agent/agents/base_agent.py`、`orchestrator_agent.py`、`react_agent.py`、`function_call_agent.py`）入口 `def run` → `async def run`；内部 LLM/工具/langchain 同步调用 → `run_in_threadpool`（LLM 调用走 R6 信号量）。
- 删除全部 `flask_app`/`current_app`/`has_app_context` 分支（base_agent.py:194、orchestrator_agent.py:306、chat_runner.py:89、workflow.py:111、retrieval_service 的 flask_app 参数、memory_provider 的 app_context 块、memory_tools.py 4 处）；改 `session: AsyncSession` 显式注入。
- AgentQueueManager 线程：`worker_run(agent_main)`（R5 机制图）；Redis 同步客户端保持（线程内同步安全）。
- **风险点**：若某 agent 文件内部编排依赖 langgraph 图对象跨 await 复用（langgraph 图 invoke 是同步、线程不安全跨 loop），包整个图调用 `run_in_threadpool` 并序列化（信号量）。转换以"每文件可独立审查"为单位拆分任务。

### R11 FileStorage → BinaryIO（简化）
```python
# 服务层签名（cos/miniio/chroma_file/skill/app_service/markdown_to_pptx）
def upload(self, file: BinaryIO, filename: str, content_type: str | None = None) -> str:
    data = file.read()
    ...
```
- 服务内部包装流（`FileStorage(io.BytesIO(...), filename=...)`）→ 直接传 `(bytes, filename)` 或 `io.BytesIO` + 显式 filename 给 COS SDK。
- handler 侧适配（FileStorage→stream）在 Plan 3；本计划内 `test/internal/handler` 已 skip，无运行期消费者。
- `internal/schema/weaviate_vector_schema.py:22` 的 `werkzeug.datastructures.ImmutableMultiDict`：最小改动——类型标注改 `dict`/`Any`（该文件其余不动；若改动超范围上报控制器）。
- `internal/schema/update_file_schema.py` 等文件上传 schema 的 FileField：**冻结，不动**（Plan 3 换 UploadFile）。

## 任务与批量划分

依赖序：T1 → T2 → T3；T4 依赖 T1/T2；T5/T6/T7 依赖 T4 模式与 T3 替换；T8 依赖 T5/T6/T7；T9 收尾。**每个任务结束必须更新 `docs/migration/progress.md`（勾选 + 本任务事务边界登记 + 属性上移登记）。**

---

### Task 1: 地基——worker_run + request_context + settings.project_root + 纯工厂 container + BaseService + 测试基建

**Files:**
- Modify: `package/database.py`（R5 的 `worker_run`/`_run_worker`）
- Create: `internal/core/request_context.py`（R4）
- Modify: `internal/config/settings.py`（+`project_root` 字段，`Path(__file__).resolve().parents[2]`，注释 pyinstaller 限制；**+`rerank_device: str = "cpu"` 设备字段**，与既有 `embedding_device` 并列；ltp 等按需补）
- Create: `internal/container.py`（R8 纯工厂骨架：create_account_service/create_api_key_service/create_jwt_service 单例）
- Modify: `internal/service/base_service.py`（R1/R2 首个转换；提供标准 async CRUD：`create/delete/update/get`——add 不 await、delete await，供业务服务复用）
- Modify: `internal/service/jwt_service.py`（删 `@inject`；无 session，转单例）
- Modify: `test/conftest.py`（R9 重写）+ `test/internal/handler/__init__.py`、`test/internal/schema/__init__.py`（R9 统一 skip）
- Create: `docs/migration/transaction-boundaries.md`、`docs/migration/model-session-callers.md`（空表，后续任务登记）
- Test: `test/package/test_database.py`（+worker_run：内存 sqlite 引擎验证 commit_on_success/rollback；**P2.1.1-3 防护测试**——运行中 loop 内调用 worker_run 断言抛出清晰 RuntimeError，普通线程调用成功）、`test/internal/core/test_request_context.py`、`test/internal/config/test_settings.py`（+project_root）、`test/internal/service/test_base_service.py`（新，async CRUD + add/delete await 语义）

**Interfaces:**
- Produces: `worker_run(coro_factory, *, commit_on_success=True) -> T`；`get_request_context()/set_request_context()/reset_request_context()`；`settings.project_root`；`container.create_account_service` 等纯工厂；`BaseService.create/delete/update/get`（async）。

- [ ] **Step 1: 写失败测试**（每文件；注意 fixture 全部 `pytest_asyncio.fixture` + `async def`，禁止 `def` 内 await）。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现**（R3/R4/R5/R8/R9 代码）。
- [ ] **Step 4: 运行确认通过**：`pytest test/package/test_database.py test/internal/core/test_request_context.py test/internal/config/test_settings.py test/internal/service/test_base_service.py test/internal/handler test/internal/schema -v`（handler/schema 显示 skip）。
- [ ] **Step 5: 更新 progress.md**（勾选 T1 + 空表建好），提交：`feat(core): worker_run 线程适配 + request_context + project_root + 纯工厂 container + BaseService async 化 + 测试基建（handler/schema 统一 skip）`。

---

### Task 2: 模型层迁移（15 个 model 文件）

**Files:**
- Modify（全部 model）：`account.py`（UserMixin 移除；assistant_agent_conversation 属性上移）、`api_key.py`、`api_tool.py`、`app.py`、`conversation.py`、`dataset.py`、`end_user.py`、`episodic_memory.py`、`procedural_memory.py`、`skill.py`、`sub_task_checkpoint.py`、`system_config.py`、`upload_file.py`、`user_memory.py`、`workflow.py`（R7：`db.Model`→`Base`）
- Modify: `internal/migrations/env.py`（`target_metadata` 切换 `Base.metadata`，删 `db` 过渡引用）
- Create: `docs/migration/model-session-callers.md`（登记全部属性上移映射）
- Test: `test/internal/model/*`（转 async；新增"internal/model 无 db.session/flask/werkzeug/current_app"门禁断言——本文件级门禁 T2 起生效，全量门禁仍留 T9）

**Interfaces:**
- Consumes: `package.database.Base`、`settings.project_root`
- Produces: 纯 ORM 模型；`model-session-callers.md` 上移清单（服务任务据此补服务方法）。

- [ ] **Step 1: grep 基线**：`grep -rn "db.session\|db.auto_commit\|current_app\|UserMixin" internal/model/` → 逐处记录。
- [ ] **Step 2: 逐文件转换**（R7）；每个上移点登记映射。
- [ ] **Step 3: 测试**：现有模型测试转 async；门禁断言通过。
- [ ] **Step 4: 运行**：`pytest test/internal/model test/migration -v`。
- [ ] **Step 5: progress.md 更新，提交**：`refactor(model): 迁移 package.database.Base + 属性查库上移（登记 model-session-callers.md）`。

---

### Task 3: 服务层 flask 依赖清除（request/current_app/FileStorage/weaviate）

**Files:**
- Modify（R3/R4）: `account_service.py`（remote_addr）、`oauth_service.py`（remote_addr）、`app_service.py`（scheme/host）、`app_config_service.py`（scheme/host）、`workflow_service.py`（scheme/host）、`builtin_tool_service.py`（root_path）、`language_model_service.py`（root_path）、`assistant_agent_service.py`（ASSISTANT_AGENT_ID）、`retrieval_service.py`（`from flask import Flask` 删）
- Modify（R11）: `cos_service.py`、`miniio_service.py`、`chroma_file_service.py`、`skill_service.py`、`app_service.py`、`internal/core/tools/builtin_tools/providers/pptx/markdown_to_pptx.py`（FileStorage→BinaryIO+filename+content_type）
- Modify: `vector_database_service.py`、`weaviate_vector_service.py`（FlaskWeaviate→`internal.extensions.weaviate.weaviate_client` 单例；同步调用 run_in_threadpool + R6 信号量）
- Modify: `internal/schema/weaviate_vector_schema.py`（ImmutableMultiDict 类型标注→dict/Any，最小改动；超范围上报）
- Test: 受影响服务现有测试转 async；`test/internal/extensions/test_extensions.py` 补 `init_weaviate` 单例调用测试（monkeypatch connect_to_custom 断言参数，沿用 Plan 1 模式）；新增 `test/migration/test_no_flask_imports.py` 骨架（`@pytest.mark.slow`，T9 前默认不跑）

**门禁范围（本任务后生效，T3 起 CI 可跑）**：
```bash
grep -rn "from flask\|from werkzeug\|flask_weaviate\|injector" internal/service internal/core | grep -v test
# 必须为空
```

- [ ] **Step 1: grep 基线**：`grep -rn "flask\|werkzeug\|FlaskWeaviate" internal/service internal/core/tools | grep -v test`。
- [ ] **Step 2: 逐文件替换**（R3/R4/R11；FileStorage 签名改动会牵连 T5-T9 服务调用方——本任务先改服务签名，调用方在各自簇任务内同步适配；progress.md 记录签名变更清单）。
- [ ] **Step 3: 测试**：受影响服务测试转 async；weaviate 单例测试；门禁脚本通过。
- [ ] **Step 4: 运行**：`pytest test/internal/service test/internal/extensions -v` + 门禁。
- [ ] **Step 5: progress.md 更新，提交**：`refactor(service): 清除服务层 flask/werkzeug/FlaskWeaviate 依赖（ctx/settings/BinaryIO/单例）`。

---

### Task 4: 认证与账号簇 async 化

**Files:**
- Modify: `internal/service/account_service.py`、`api_key_service.py`、`jwt_service.py`、`oauth_service.py`、`system_config_service.py`（apply_to_env 转 async + worker_run 内独立会话——lifespan 调用。**时序约束**：apply_to_env 必须在 `get_settings()` 首次调用前执行（Plan 3 lifespan 落地），否则 system_config 的 DB 配置（含设备项）不生效；T4 保持该方法语义并注明调用时机）
- Test: 现有相关测试转 async + 新增认证服务测试（真实库 + access_token fixture，R9）

**Interfaces:**
- Produces: `async def get_account/get_account_by_email/get_api_by_by_credential/update_password` 等；`apply_to_env` async。
- Consumes: T1 container 工厂、T2 模型、T3 ctx/settings。

- [ ] **Step 1-4**: 按 R1/R2 转换 + 测试（含事务边界登记：本簇 auto_commit 块 → commit 登记）。
- [ ] **Step 5: progress.md 更新，提交**：`refactor(service): 认证/账号簇 async 化`。

---

### Task 5: App 簇 async 化（大文件，按方法拆分）

**Files:**
- Modify: `internal/service/app_service.py`（1130 行——**按方法拆分转换，每方法一个 commit**，progress.md 记录方法清单）、`app_config_service.py`、`builtin_app_service.py`、`assistant_agent_service.py`、`language_model_service.py`
- Test: `test_app_service_draft_config.py`、`test_app_service_publish_orchestrator.py`、`test_app_logical_delete.py`、`test_app_config_skill_tool.py`、`test_app_config_transformer.py`、`test_ask_user_chat_runner.py` 等转 async

**注意**：app_service 内 chat 链（debug_chat→ChatRunner→agent）依赖 T6/T8——本任务先 async 化**非 chat 部分**；chat 相关方法若依赖未转换服务，标记 `# TODO(plan2-chat): T6/T8 后收口` 并登记 progress.md，T8 收口。

- [ ] **Step 1-4**: 转换 + 测试（每批方法独立验证）。
- [ ] **Step 5: progress.md 更新（方法拆分清单 + 事务边界登记），提交**：`refactor(service): app 簇 async 化（按方法拆分）`。

---

### Task 6: 会话/对话簇 async 化

**Files:**
- Modify: `internal/service/conversation_service.py`（app_context 块→worker_run 或显式 session；flask_app 参数删）、`chat_runner.py`（`run()` 改 `async def` 返回 async generator；flask_app→settings）、`choice_service.py`、`open_api_service.py`、`web_app_service.py`、`analysis_service.py`、`internal/memory/token_buffer_memory.py`、`internal/core/memory/token_buffer_memory.py`
- Test: `test_chat_runner.py`、`test_chat_runner_orchestrator.py`、`test_ask_user_chat_runner.py`、`test_chat_error_handling.py`、`test_conversation_compact.py`、`test_conversation_delete_checkpoints.py`、`test_conversation_service.py`、`test_choice_service.py`、`test_token_buffer_memory.py` 转 async

**关键设计（本任务定案）**：`ChatRunner.run()` 改 `async def` + async generator（`async for` 产出 SSE 事件），内部 `await run_in_threadpool(llm 调用)`；Plan 3 的 StreamingResponse 直接消费 async generator（FastAPI 原生支持）。

**P2.1.1-4 SSE 黄金测试（本任务必做）**：新增 `test/internal/service/test_chat_runner_sse_golden.py`（mock LLM，不真实调用）严格校验：
- **成功路径事件序列**：`agent thought`（含 task_id/ping）→ `message` 增量事件 → `done` 事件，顺序与旧逻辑一致（对照 `queue_entity.QueueEvent` 保留的事件类型枚举）；
- **每个事件 payload 字段**：id/task_id/event/type/data 结构与旧版逐字段一致；
- **错误路径**：LLM 抛异常 → `error` 事件 → `done` 事件，且无悬挂（生成器正常结束）；

- [ ] **Step 1-4**: 转换 + 测试（事件序列对照）。
- [ ] **Step 5: progress.md 更新，提交**：`refactor(service): 会话/对话簇 async 化（chat_runner async generator）`。

---

### Task 7: 知识库簇 async 化

**Files:**
- Modify: `dataset_service.py`、`document_service.py`、`indexing_service.py`（多个 auto_commit 块——**独立事务边界，逐块登记**）、`segment_service.py`、`retrieval_service.py`（flask_app 参数→settings；langchain 工具构造 run_in_threadpool）、`keyword_table_service.py`、`process_rule_service.py`、`embeddings_service.py`（torch→R6 信号量）、`ltp_service.py`、`vector_database_service.py`、`weaviate_vector_service.py`（同步 weaviate→R6）、`chroma_service.py`、`chroma_file_service.py`、`chroma_vector_service.py`、`attachment_service.py`、`upload_file_service.py`、`cos_service.py`、`miniio_service.py`
- Test: `test_retrieval_service_agentic_tool.py`、`test_vector_database_service.py` 等转 async

**注意**：`internal/core/retrievers/*`（bm25/full_text/semantic/rrf/rerank）与 `internal/core/embeddings/*` 为纯同步逻辑（无 flask），**不转 async**；调用方在 async 方法内 R6 桥接。

- [ ] **Step 1-4**: 转换 + 测试。
- [ ] **Step 5: progress.md 更新（indexing 事务边界逐块登记），提交**：`refactor(service): 知识库簇 async 化`。

---

### Task 8: 工作流/记忆/Agent 簇 async 化（含 R10 agent async 化子任务）

**Files:**
- Modify（服务）: `workflow_service.py`、`sub_task_service.py`、`user_memory_service.py`、`episodic_memory_service.py`、`procedural_memory_service.py`、`reflection_service.py`、`service/memory_provider/*`（builtin/tencent/base/resolver/tencent_client——app_context 块→worker_run）
- Modify（核心，R10 子任务 A）: `internal/core/workflow/*`（workflow.py:111 flask_app→session 注入）、`internal/core/tools/memory_tools.py`（4 处 app_context→worker_run）、`internal/core/tools/builtin_tools/providers/browser/browser.py`（`current_app.extensions.get("default_llm")`→显式构造/单例）、`internal/core/agent/agents/agent_queue_manager.py:37`（`injector.get(Redis)`→`internal.extensions.redis.sync_redis_client`）
- Modify（R10 子任务 B——独立审查单元）: `internal/core/agent/agents/base_agent.py`、`orchestrator_agent.py`、`react_agent.py`、`function_call_agent.py`（async 化 + run_in_threadpool + session 注入；每个文件一个提交）
- Test: `test/internal/core/agent/*`、`test/internal/core/workflow/*`、`test/internal/core/tools/test_memory_tools.py`、`test/internal/service/*memory*`、`test/internal/service/memory_provider/*` 转 async/适配

**执行约束**：子任务 B（agent async 化）是独立审查单元，每个文件单独提交、单独跑其测试；langgraph 图对象跨 await 复用问题（图 invoke 同步、线程不安全跨 loop）——包 run_in_threadpool + R6 信号量序列化，发现异常立即上报控制器（唯一允许的"停止并上报"场景，其余按 R10 执行）。

- [ ] **Step 1-4**: 转换 + 测试（子任务 A 先、子任务 B 逐文件）。
- [ ] **Step 5: progress.md 更新，提交**：`refactor(core): workflow/记忆/agent 簇 async 化（R10 方案 A）`。

---

### Task 9: 剩余服务 + injector 移除 + 门禁启用 + 全量回归

**Files:**
- Modify: `internal/service/audio_service.py`、`skill_service.py`、`feishu_service.py`、`ai_service.py`、`api_tool_service.py`、`builtin_tool_service.py`、`attachment_service.py`（T7 未覆盖部分）
- Delete: `app/http/module.py`（确认无引用后删除；`app/http/app.py` 冻结引用——确认删除后 import 不再依赖它即可）
- Modify: `test/migration/test_no_flask_imports.py` 启用全量门禁（T9 起跑；豁免清单：`internal/handler`、`internal/router`、`internal/schema`、`app/http`、`internal/task`、`internal/migrations`）
- Modify: `docs/migration/progress.md`（Plan 2 完成 + 事务边界/属性上移登记复核 + Plan 3 入口）

**门禁（T9 起全量执行）**：
```bash
grep -rn "from flask\|import flask\|from werkzeug\|from injector\|@inject\|injector\." internal/ package/ \
  | grep -v "test" | grep -v "internal/handler" | grep -v "internal/router" \
  | grep -v "internal/schema" | grep -v "app/http" | grep -v "internal/task" | grep -v "internal/migrations"
# 输出必须为空
```

- [ ] **Step 1-4**: 转换 + 门禁 + 全量回归（`pytest test/migration test/package test/internal/config test/internal/extensions test/internal/task test/app test/internal/service test/internal/model test/internal/core -q`——handler/schema skip 计数 0 为可接受；`test/internal/task` 与 `test/app` 为 Plan 1 存量）。
- [ ] **Step 5: progress.md 更新，提交**：`refactor(core): 移除 injector 与全部 flask/werkzeug 依赖（服务层 async 化完成）`。

---

## 验收标准（Done 定义）

1. `internal/service|model|core` 下 `grep flask|werkzeug|injector` 为 0（豁免清单见 T9）；`app/http/module.py` 已删除，全仓库无 `injector` 引用（`internal/task`、`app/http/app.py` 冻结项除外，Plan 4 处理）。
2. 248 处 `db.session` 调用点全部 async 化；`auto_commit` 在 `internal/` 下为 0；**每一处 `await commit()` 均已在 `docs/migration/transaction-boundaries.md` 登记**；flush 仅出现在 DB 生成值/FK/约束验证处。
3. **破坏性迁移声明成立**：旧 Flask Web 不可运行是预期状态（handler 同步调 async 服务）；`test/internal/handler/*`、`test/internal/schema/*` 模块级 skip，**skip 计数 0 为可接受完成态**，Plan 3 打开。
4. 全量可运行测试绿（skip 除外）；门禁测试（T9 启用）通过。
5. `internal/core/agent/*` 全部 async 化（R10 方案 A）且其测试绿。
6. 全部提交落 `release_fastApi`；`docs/migration/progress.md` 每任务更新完毕。

## Self-Review 备注

- **评审采纳记录**：事务边界显式化（三分类 + commit 登记制）；agent 方案 A 定案（R10 + 线程机制图）；container 纯工厂化（R8）；handler 测试统一 skip（R9）；fixture 修正（R9）；FileStorage→BinaryIO（R11）；run_in_threadpool 加并发信号量（R6）；大文件按方法拆分（T5）；门禁 T9 才启用；weaviate 单例测试入 T3；project_root 注释；metadata 单例确认（R7）。
- **推回记录**：不采用"Service 禁止 commit + 统一 get_db 提交"（会破坏 auto_commit 语义与请求→后台可见性，见事务模型硬规则 1）；不采用 greenlet run_sync 与同步 session 回退方案（服务层已全 async，二者不可自洽）。GPU/推理进程：不引入独立 Executor，但**推理设备改为 settings 可配置（cpu/cuda/mps，含系统设置页入口，见 Plan 3 协调）**——设备切换 + CapacityLimiter 已覆盖 CPU/GPU，Executor 仅当 GPU 规模化需要排队/批处理时再评估。
- **P2.1.1 微调记录**：R2 加"以实际 API + 类型检查为准"注记；R6 改为 anyio.CapacityLimiter（跨 loop 安全、进程级限流，替代模块级 asyncio.Semaphore）；R5 worker_run 加运行中-loop 守卫 + 防护测试；T6 增加 SSE 黄金测试（成功/错误路径事件序列与 payload）；R9 conftest engine 模块级 + connection/begin/rollback 隔离（避免每测试重建引擎）。
- **接口与 Plan 3**：container 纯工厂即 Plan 3 Depends 适配层的数据源；request_context 由 Plan 3 依赖写入；ChatRunner async generator 直接供 StreamingResponse；handler/schema skip 由 Plan 3 打开并重写；**系统设置页（/settings）新增推理设备配置项（`EMBEDDING_DEVICE`/`RERANK_DEVICE`，cpu|cuda 下拉）**——schema/handler 解冻后实现，后端 `system_config` + `apply_to_env` 机制已支持任意 env 键，无需改服务层。
