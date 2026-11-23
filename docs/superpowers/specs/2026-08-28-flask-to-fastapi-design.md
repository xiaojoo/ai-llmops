# Flask → FastAPI 深度现代化迁移设计（全量 async）

- 日期：2026-08-28
- 分支：`release_fastApi`（从 `release_20260830` 切出）
- 状态：已获用户批准（决策点已确认），待用户复核本文档后进入实施计划（writing-plans）

## 1. 背景与目标

将当前 Flask 3.1 单体后端迁移到 FastAPI。**已确认的决策**：

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 迁移策略 | 深度现代化重构：**服务层 DB 本次就全量 async**（async SQLAlchemy 2.0 + asyncpg），同步库用 `run_in_threadpool` 桥接 |
| 2 | 切换方式 | 一次性替换（不做双服务灰度）；分阶段 P0→P8 提交，每期独立可验证 |
| 3 | DI 容器 | **injector 彻底移除**，改用 FastAPI `Depends` + 手工组合根 |
| 4 | 代码提交 | 全部提交到 `release_fastApi` 分支 |
| 5 | 版本策略 | **一律使用最新稳定版本依赖 + 最新语法重构**（如 SQLAlchemy 2.x `Mapped[]`/`mapped_column`/`select()`、Pydantic v2 惯用法、FastAPI 最新版），**不写兼容旧 API 的垫片/兼容版本** |

目标：153 条 API 路由的 **URL、请求/响应结构（code/message/data）、SSE 事件协议完全不变**，前端零改动；同时获得 FastAPI 的自动 OpenAPI 文档、类型校验、异步能力，并清理掉全部 Flask 技术债（Flask-SQLAlchemy / Flask-Migrate / Flask-Login / Flask-WTF / flask_cors / flask_weaviate / gevent）。

## 2. 现状盘点（Flask 面）

- 规模：314 个业务 Python 文件（排除 venv），约 26,348 行；28 个 handler；**153 条路由**（`internal/router/router.py`，llmops 蓝图 ~145 条 + openapi 蓝图 ~8 条）。
- Flask 依赖面（grep 统计）：
  - `flask_login`：28 个 handler 的 `current_user`/`login_required` + `internal/middleware/middleware.py` + `internal/model/account.py` 的 `UserMixin`。
  - `flask.request`：10 个 service + 14 个 handler。
  - `flask.current_app`：15+ 处（service/agent/workflow/memory 深层代码），`app_context()` 推入/弹出 20+ 处（后台线程、Celery、memory provider）。
  - `flask_wtf.FlaskForm`：24 个 schema 文件。
  - `package/sqlalchemy`：Flask-SQLAlchemy 子类，`db.session`/`db.auto_commit` 合计 **248 处**调用。
  - `flask_weaviate`：2 个 service + extension；`flask_migrate`：migrations；`flask_cors`；gevent monkey patch（生产）。
- 运行时：Dockerfile + `jenkins/entrypoint.sh`（`flask run` / gunicorn gthread / `celery -A app.http.app.celery`），端口 5001。

## 3. 目标架构

```
uvicorn (workers=N)                        Celery worker
└── FastAPI app (app.http.app)             └── internal.task.celery_app（独立模块）
    ├── lifespan:                          ├── 任务体: asyncio.run(async_worker(...))
    │   ├─ 异步 engine (asyncpg) + AsyncSessionLocal
    │   ├─ Redis / Weaviate / 日志 / DB 配置注入(SystemConfigService.apply_to_env) / create_all
    │   └─ 单例服务（无 session 依赖）构造并放入 app.state
    ├── CORSMiddleware（配置与现状一致）
    ├── APIRouter llmops: ~145 路由，Depends(get_current_user)
    ├── APIRouter openapi: ~8 路由，Depends(get_api_key_account)
    ├── 异常处理器: CustomException / ValidationError / SQLAlchemyError / Exception
    ├── StreamingResponse（SSE，async generator）
    └── 依赖注入: FastAPI Depends（internal/container.py 手工组合根）
业务层（本次要改造）:
    internal/handler × 28  → async def + Depends(get_current_user) + Pydantic 参数
    internal/service × 50+ → async def + AsyncSession + run_in_threadpool(同步库)
    internal/model × 15    → DeclarativeBase 纯 ORM（移除 db.session 直接调用 ~20 处）
    internal/core（agent/workflow）→ 同步执行体 + 线程适配（asyncio.run 包一层）
    internal/schema × 24   → Pydantic v2
```

## 4. 组件映射表

| 现有组件 | 迁移后 | 说明 |
|---|---|---|
| `app/http/app.py` | FastAPI 实例 + `uvicorn.run`（`if __name__`） | 保留 `app:app` 入口路径 |
| `internal/server/http.py` | `create_app()` 工厂 + lifespan | 扩展初始化、CORS、异常、路由 |
| `internal/router/router.py` | 两个 `APIRouter`，`add_api_route` × 153 | 机械转换，脚本生成；`<uuid:x>`→`{x}` |
| `internal/middleware/middleware.py` | `get_current_user` / `get_api_key_account` 依赖 | 蓝图分流 → 路由器级 Depends |
| `flask_login` | `HTTPBearer` 依赖 + JWT 解析（复用 `JwtService`） | `current_user`→`user: Account = Depends(...)`；删除 UserMixin |
| `internal/schema/*`（FlaskForm+wtforms+marshmallow） | Pydantic v2 模型 | 校验 message 文案保留；文件上传→`UploadFile = File(...)` |
| `flask.request` | `Request` 参数 / 请求级 contextvar（service 内） | 尽量 contextvar，减少方法签名改动 |
| `flask.current_app` | `internal/config/settings.py` 单例 + `app.state` | `current_app.config.get(...)` → `settings.X` |
| `app.app_context()`（线程/Celery） | 线程内 `asyncio.run(_async_worker(...))`，内部用 `AsyncSessionLocal()` | 见 §5.2 |
| `package/sqlalchemy`（Flask-SQLAlchemy） | **删除**；新增 `package/database.py`（async engine、async_sessionmaker、`Base=DeclarativeBase`） | 248 处调用点全部 async 化 |
| `internal/extension/database_extension.py` | 删除；模型改继承 `package/database.Base` | model 直接 `db.session` 调用改为 session 注入 |
| Flask-Migrate `internal/migrations` | 独立 Alembic（async env.py，去掉 current_app） | 迁移版本文件复用 |
| `flask_weaviate` | weaviate-client v4 直接实例化（lifespan 注入） | 同步客户端，调用处 `run_in_threadpool` |
| `package/response`（jsonify + stream_with_context） | JSONResponse + StreamingResponse | code/message/data 契约不变 |
| Celery `FlaskTask` | 独立 `celery_app.py` + async 任务体 | `celery -A internal.task.celery_app.celery_app` |
| gevent monkey patch + gunicorn | uvicorn 多 worker；同步长任务声明 `def` 端点走线程池 | 移除 gevent/eventlet |
| `flask_cors` | CORSMiddleware | 配置一致 |
| injector（`app/http/module.py`） | **删除**；`internal/container.py` 手工组合根 | 见 §5.5 |

## 5. 关键设计点

### 5.1 异步 DB 会话生命周期（本次核心改造）

```python
# package/database.py
engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, pool_size=..., pool_recycle=...)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
class Base(DeclarativeBase): pass
```

- **请求作用域**：`get_db` 异步依赖——`async with AsyncSessionLocal() as session:` 或 yield 后统一 `commit()`（成功）/`rollback()`（异常），替代 `auto_commit`。
- **服务层改写规则**（248 处）：
  1. `self.db: SQLAlchemy` → `self.db: AsyncSession`（构造注入）；
  2. `self.db.session.execute(...)` → `await self.db.execute(...)`；
  3. `with self.db.auto_commit():` → 删除包装，改为 `await self.db.flush()`（同请求内后续查询在 flush 后即可见，语义与 commit 等价；最终提交由 get_db 收口）；
  4. 模型内显式 `db.session.commit()` → `await session.commit()` 或删除（依赖 get_db）。
- **模型层**：约 20 处模型方法内的 `db.session` 直接调用（`dataset.py`、`conversation.py`、`app.py`、`account.py`、`api_key.py` 等）→ 改为接收 `AsyncSession` 参数的类方法，或上移为 service 方法。模型退化为纯 ORM 类。
- **后台线程（agent 执行、memory provider）**：线程体统一为
  ```python
  def _thread_worker(...):
      async def _run():
          async with AsyncSessionLocal() as session:
              await service.method(session, ...)
      asyncio.run(_run())
  ```
  保持服务层 100% async、统一形态；线程只是循环引导器。
- **Celery 任务**：任务体内同样 `asyncio.run(...)`；task 基类不再需要 Flask app_context。
- 注意：**同一进程内不得混用"线程内 asyncio.run 的 loop"与"uvicorn 主 loop"**——线程内一律用 `asyncio.run` 自建 loop，不要引用主 loop 的 engine 会话；async engine 的连接池跨 loop 使用由 SQLAlchemy 自身管理（连接归还按 loop 绑定），实测确认即可。

### 5.2 同步库桥接（run_in_threadpool）

torch / langchain / ltp / sentence-transformers / browser-use / weaviate 同步客户端 / chromadb / OCR 等全部为同步阻塞调用。规则：
- service 方法为 `async def`，同步重活统一 `await run_in_threadpool(sync_fn, ...)`（`starlette.concurrency`）；
- agent 推理主链路（langchain/langgraph 编排）保持同步函数形态，由线程适配器承载，不强行 async 化；
- SSE 生成器为 async generator：`item = await run_in_threadpool(queue.get, timeout=1)`（AgentQueueManager 读取循环）。

### 5.3 认证（两种凭证，语义不变）

- `get_current_user`（llmops 路由）：`HTTPBearer` 提取 token → `JwtService.parse_token` → `AccountService.get_account(access_id)`；失败抛 `UnauthorizedException`（现异常类复用）。
- `get_api_key_account`（openapi 路由）：api_key → `ApiKeyService.get_api_by_by_credential` → 校验 active → 返回 account。
- 行为与现 `request_loader` 按 `request.blueprint` 分流完全等价；前端无感知。

### 5.4 SSE 流式

`compact_generate_response` 对外契约不变，内部改为返回 `StreamingResponse(async_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`。ping/keep-alive 与停止事件逻辑（AgentQueueManager）原样保留。涉及端点：debug_chat、web_app_chat、assistant_agent_chat、openapi/chat。

### 5.5 DI：移除 injector → 手工组合根

- 删除 `app/http/module.py` 与所有 `@inject` 装饰器、`injector.get(...)`（`agent_queue_manager.py` 等 3 处）。
- 新增 `internal/container.py`：为每个 service 提供 `Depends` 工厂函数（请求作用域，session 注入；FastAPI 同请求内缓存保证单例）：
  ```python
  def get_account_service(session: AsyncSession = Depends(get_db)) -> AccountService:
      return AccountService(db=session)
  def get_app_service(session=Depends(get_db), account=Depends(get_account_service), ...) -> AppService: ...
  ```
- 无 session 依赖的服务（JwtService、CosService、MiniIoService、LanguageModelManager、FeishuService 等）在 lifespan 构造一次放入 `app.state`。
- 后台线程/Celery 不使用 FastAPI Depends，直接用 `AsyncSessionLocal()` 构造所需服务（构造器是普通 dataclass，无魔法）。

### 5.6 settings 单例替换 current_app

- 新增 `internal/config/settings.py`：从 `config/Config` 提取为 dataclass/简单单例，读取 .env（`python-dotenv`），覆盖 `current_app.config.get(...)` 的全部 15+ 处；
- `current_app.root_path`（builtin_tool_service / language_model_service）→ 显式项目根路径常量；
- `app.extensions["celery"]` / `app.extensions["redis"]` / `app.extensions.get("default_llm")` → 模块级单例或 app.state。

### 5.7 异常处理（契约不变）

`CustomException` → JSONResponse{code,message,data}；Pydantic `ValidationError` → 现有 code/message 格式（首个错误 message + errors dict）；`SQLAlchemyError` → "数据库操作失败"；开发环境重抛 / 生产包装 —— 与 `internal/server/http.py` 现逻辑逐条对应。`favicon.ico`、`/default-app-icon` 两个零散路由保留为普通 GET 端点。

## 6. 测试与回归策略（一次性替换的生命线）

| 层级 | 内容 |
|---|---|
| P0 契约基线 | 从 router.py 生成 153 路由清单（method/path/依赖类型）；认证分流表；现有响应格式样例；`test/` 现有用例评估 |
| 契约测试 | pytest + `httpx.AsyncClient` + ASGITransport：每条路由至少验证"未认证→401 且 code/message/data 格式一致"；核心路由验证成功路径 |
| 黄金测试 | 代表性流程新旧对照：登录→建应用→草稿配置→调试对话（SSE）→上传文件→openapi chat |
| 前端联调 | `ai-code-llmops-web` 逐模块冒烟（153 路由） |
| 性能对比 | uvicorn vs gunicorn 吞吐/延迟基线；SSE 首包延迟；DB 连接池水位 |

## 7. 分阶段实施计划（P0–P8，预计 35–45 人日，因全量 async 上调）

| 阶段 | 内容 | 交付物/验收 | 估时 |
|---|---|---|---|
| **P0 契约基线** | 153 路由清单；认证分流表；响应契约；现有测试评估 | `docs/migration/route-inventory.md`；契约测试骨架 | 2–3 天 |
| **P1 基础设施** | requirements 替换（-flask*/gevent/eventlet/flask_weaviate；+fastapi/uvicorn/httpx/asyncpg/greenlet…）；`settings` 单例；`package/database.py`（async engine+sessionmaker+Base）；Alembic 独立 async env.py；redis/weaviate/日志 bootstrap；`internal/task/celery_app.py`；lifespan | 无 Flask 依赖可启动的空 FastAPI 应用；`python -c "import app.http.app"` 通过；alembic upgrade 空跑通过 | 4–6 天 |
| **P2 Web 层** | `create_app` 工厂；153 路由登记（脚本生成）；认证依赖；异常处理器；response 垫片（JSONResponse/StreamingResponse）；CORS；favicon/icon | 全部路由注册无冲突；/docs 可访问；契约测试（401 面）通过 | 3–5 天 |
| **P3 Schema 层** | 24 个 FlaskForm→Pydantic v2（含文件上传、校验文案、`GetAppsWithPageReq(request.args)`→Query 参数） | 契约测试（参数校验面）通过 | 3–4 天 |
| **P4 Handler 层** | 28 个 handler：`async def`；`login_required`/`current_user`/`request` 替换为 Depends/参数 | 核心路由成功路径契约测试通过 | 3–5 天 |
| **P5 服务/核心层（async 化主战场）** | 50+ service 全部 async：248 处 `db.session` 改写；`auto_commit`→flush；`current_app`→settings；`request`→contextvar；模型层 20 处 session 调用清理；agent/workflow/memory 后台线程适配（asyncio.run）；同步库 run_in_threadpool 桥接 | 全量 service 无 `db.session` 同步调用；单元/集成测试（agent 并发、SSE 并发）通过 | 10–14 天 |
| **P6 流式与任务** | SSE 全链路（debug/web_app/assistant/openapi chat）；Celery worker 独立跑通（async 任务体） | SSE 事件流与旧版逐事件对比一致；celery 任务落库正确 | 3–4 天 |
| **P7 部署** | uvicorn + entrypoint.sh + Dockerfile + Jenkinsfile；环境变量迁移；移除 gevent；端口 5001 不变 | 容器内启动、健康检查通过；gRPC/weaviate/chromadb 冒烟 | 2–3 天 |
| **P8 回归** | 全量测试 + 153 路由冒烟 + 前端联调 + 性能对比；release_fastApi 分支合入验证 | 全部验收项通过；切换窗口低峰执行 | 5–7 天 |

依赖关系：P1→P2→P4；P3 与 P4 可并行（P3 先行小步验证）；P5 依赖 P3/P4 的接口定型；P6 依赖 P5；P7/P8 殿后。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 全量 async 重写 248 处调用引入行为偏差（事务边界、同请求可见性） | 高 | P0 契约测试 + 黄金测试新旧对照；`auto_commit`→flush 的语义等价说明写进 PR 模板 |
| async engine 连接池跨线程/跨 loop 语义（后台线程 asyncio.run） | 高 | P5 专门做并发冒烟（agent 并发、SSE 并发、Celery 并发）；必要时线程内独立 engine |
| 移除 gevent 后 gRPC（weaviate/dashscope）与 uvicorn 线程行为差异 | 高 | P1 冒烟验证；保留独立 grpc 初始化路径 |
| 一次性替换回归面（153 路由） | 高 | P0 基线 + P8 全量冒烟；切换放低峰 |
| FlaskForm→Pydantic 校验信息/行为差异 | 中 | 逐 schema 保留 message 文案；契约测试覆盖校验面 |
| 同步长任务（agent 推理）阻塞事件循环 | 中 | handler 统一 `async def`，重活一律 `run_in_threadpool`；SSE 端点 async generator 内 `run_in_threadpool`，事件循环不被同步调用占死 |
| 模型层 session 调用清理遗漏导致运行期报错 | 中 | P5 期间 grep 断言"internal/model 无 `db.session`"为 CI 检查项 |
| injector 移除后组合根遗漏依赖 | 中 | container.py 每个工厂函数带类型标注；启动时全量构造一次自检 |

## 9. 明确不做（Out of Scope）

- 不改 153 条路由的 URL/方法/响应契约；不改 SSE 事件协议；
- 不引入消息队列/事件总线等新组件（Celery 保持）；
- 不做双服务灰度、不做 nginx 分流；
- 不迁移 `ai-code-llmops-web` 前端；
- 数据库表结构不变（迁移版本文件复用）；
- 不引入 ruff/类型检查器配置变更（沿用现有规范）。

## 10. 验收标准（Done 定义）

1. `requirements.txt` 无任何 `flask*`/`gevent`/`eventlet` 依赖；`grep -ri "flask" internal package app`（注释除外）为 0；
2. 153 条路由在 FastAPI /docs 下全部可见，URL 与旧版一致；
3. 契约测试 + 黄金测试全绿；前端逐模块冒烟通过；
4. SSE 事件流与旧版逐事件一致；Celery 任务正常执行并落库；
5. uvicorn 生产部署跑通，性能不低于旧版基线；
6. 全部提交落在 `release_fastApi` 分支。
