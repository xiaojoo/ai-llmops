# Plan 3: Web 层翻转（P2/P3/P4 Web 部分）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把冻结的 Web 层（27 handler / 153 路由 / 26 schema / package.response / internal.server / internal.middleware）从 Flask 形态翻转为 FastAPI 形态，**使系统从"破坏性中间态"恢复为可运行的 FastAPI Web 服务**：153 条路由的 URL/方法/响应契约（code/message/data）与 SSE 事件协议完全不变，前端零改动。

**本计划取代** 原 spec 的 P2（Web 层）/P3（Schema 层）/P4（Handler 层）三个阶段，合并为一个 Web 翻转计划。完成后 `internal/handler`、`internal/router`、`internal/schema`、`package/response`、`internal/server`、`internal/middleware`、`app/http/app.py` 全部零 flask（豁免仅剩 `internal/task`（Plan 4）与 `internal/migrations`）。

**Architecture:** 两个 `APIRouter`（llmops：~145 路由 `Depends(get_current_user)`；openapi：chat 等 `Depends(get_api_key_account)`；`/webhook` 公开无依赖——与旧 request_loader 按蓝图分流语义完全一致）。handler 改 `async def` + `user: Account = Depends(...)` + Pydantic 参数；schema 全部转 Pydantic v2（请求模型含校验 message 保留、响应模型 marshmallow→Pydantic）；`package/response` 重写为 `JSONResponse`/`StreamingResponse`（**错误契约 = HTTP 200 + code 字段**，黄金样例锁定）；`app/http/app.py` 由 Plan 1 pilot 演进为正式 FastAPI 入口（lifespan 装配 + CORS + 异常处理器 + favicon/icon）。

**Tech Stack:** FastAPI 0.141（已装）、uvicorn、pydantic v2、httpx TestClient、python-multipart（已装）、starlette StreamingResponse。

**Spec:** `docs/superpowers/specs/2026-08-28-flask-to-fastapi-design.md`
**Plan 1（完成）:** 契约基线（`docs/migration/route-inventory.md` 153 路由、`docs/migration/golden/` 黄金样例）
**Plan 2.1（完成）:** 服务层全 async（`internal/container.py` 纯工厂、`package/database`、`request_context`、worker_run）

## 迁移状态声明

本计划是"破坏性中间态"的出口：Plan 2.1 完成后旧 Flask Web 不可运行；**Plan 3 完成后系统恢复可运行**（uvicorn 启动 + /docs + 153 路由可访问 + SSE 流式正常）。`test/internal/handler/*` 与 `test/internal/schema/*` 的模块级 skip 在本计划中**逐个解除**（随各自转换完成），最终全量测试无 skip 残留（除环境性 skip）。

## Global Constraints

- 所有提交必须落在 `release_fastApi` 分支。
- **最新稳定版本 + 最新语法，不写兼容垫片**。
- **API 契约不变（硬约束，前端零改动）**：
  1. 153 条路由的 URL 与方法完全一致（`<uuid:x>` → `/{x}` 路径参数 + `UUID` 类型，URL 形态与旧版一致）；
  2. 响应结构 `{code, message, data}` 不变；**未授权 = HTTP 200 + `{"code":"unauthorized",...}`（黄金样例 401-shape.json 锁定，不得"修正"成 HTTP 401）**；
  3. SSE 事件协议不变（`text/event-stream`、`QueueEvent` 事件类型、ping/keep-alive）；
  4. `/default-app-icon` 返回 200 image/png 二进制。
- **认证语义不变**：llmops 蓝图路由用 `Bearer <JWT>`（`get_current_user`）；openapi 蓝图路由用 api_key（`get_api_key_account`）；`/webhook`（feishu，无 login_required）公开——逐条对照 `internal/middleware/middleware.py` 旧逻辑。
- **契约来源**：`docs/migration/route-inventory.md`（153 条，脚本 `scripts/migration/extract_routes.py` 生成——路由登记用同一脚本产出的骨架）；`docs/migration/golden/`（401-shape/ping/icon）；`docs/migration/model-session-callers.md`（handler 不得再访问已上移的模型属性，改调服务方法）。
- 事务：handler 不 commit（get_db 请求级收口）；服务层事务边界登记制沿用。
- 服务层冻结：本计划**不修改** `internal/service/*`、`internal/model/*`、`internal/core/*`、`package/database.py`、`internal/container.py`（仅可能向 container 增加 Web 侧适配函数，见 R8）。
- 冻结解除顺序：schema（T2）→ router（T3）→ handler（T4）；测试 skip 随各簇解除。

## 契约基线（评审与实现都必须遵守的事实）

| 契约 | 事实（黄金样例/代码锁定） | 引用 |
|---|---|---|
| 未授权响应 | **HTTP 200** + `{"code":"unauthorized","data":{},"message":"该接口需要授权才能访问，请登录后尝试"}` | `docs/migration/golden/401-shape.json` |
| /ping | 同样被认证拦截（llmops 蓝图全量认证） | `golden/ping.json` |
| /default-app-icon | 200 image/png 二进制 | `golden/default-app-icon.json` + 源文件 `internal/core/builtin_apps/default-user-icon.png` |
| 业务异常 | CustomException → 200 + {code,message,data}；code 取异常类 code 字段 | `internal/exception/exception.py` |
| Pydantic 校验失败 | code=HttpCode.VALIDATION_ERROR + 首个错误 message + errors dict | 旧 `internal/server/http.py:_register_error_handler` |
| SSE | text/event-stream；事件经 `package.response.compact_generate_response`（新实现） | `QueueEvent` 枚举 + SSE 黄金测试（Plan 2.1） |

## Global Transformation Rulebook（每个任务都必须遵守）

### R1 package/response 重写（契约不变）
```python
# package/response/response.py（重写，删除 flask import）
from fastapi.responses import JSONResponse, StreamingResponse
from .http_code import HttpCode

@dataclass
class Response:            # 不变
    code: HttpCode = HttpCode.SUCCESS
    message: str = ""
    data: Any = field(default_factory=dict)

def json(data: Response | None = None, status_code: int = 200):   # 错误契约：业务码在 body，HTTP 一律 200
    return JSONResponse(asdict(data or Response()), status_code=status_code)

def success_json(data=None): ...
def fail_json(data=None): ...
def validation_error_json(errors=None): ...
def message_json(code, message=""): ...
# ... 其余助手保持签名

def compact_generate_response(response) -> JSONResponse | StreamingResponse:
    """统一快输出与流式输出：Response→JSONResponse；生成器→StreamingResponse(async 或 sync 均可，media_type="text/event-stream"，headers Cache-Control/X-Accel-Buffering)。"""
```
- 所有 helper 签名与旧版一致（handler 调用点零改动）。
- `HttpCode` 不变；`package/response/__init__.py` 导出不变。

### R2 认证依赖（替代 flask_login request_loader）
```python
# internal/server/deps.py（新增，Web 侧薄适配层）
from fastapi import Depends, Header, HTTPException  # 仅此处可用 fastapi
from internal.service import JwtService, ApiKeyService, AccountService

async def get_current_user(authorization: str = Header(default="")) -> Account:
    """llmops 路由：Bearer <JWT> → Account。语义与旧 request_loader 的 llmops 分支一致。"""
    # 解析 Authorization → JwtService.parse_token → AccountService.get_account(sub)
    # 失败抛 UnauthorizedException（由异常处理器转 200+code）

async def get_api_key_account(authorization: str = Header(default="")) -> Account:
    """openapi 路由：api_key → ApiKey 记录(active) → account。语义与旧 openapi 分支一致。"""
```
- 凭证解析逻辑（Bearer 格式校验、401 message 文案）逐条对照旧 `middleware.py:_validate_credential`，文案必须一致。

### R3 request_context 依赖写入
```python
# internal/server/deps.py
async def request_context(request: Request) -> RequestContext:
    ctx = RequestContext(scheme=request.url.scheme, host=request.url.netloc.split(":")[0] or request.url.hostname or "",
                         remote_addr=request.client.host if request.client else None)
    token = set_request_context(ctx)
    try:
        yield ctx
    finally:
        reset_request_context(token)
```
- 挂为 llmops/openapi 两个 router 的依赖（`dependencies=[Depends(request_context)]`），服务层 `get_request_context()` 生效。

### R4 Schema 转换（FlaskForm → Pydantic v2）
```python
# 前（internal/schema/account_schema.py）
class UpdatePasswordReq(FlaskForm):
    password = StringField('password', validators=[DataRequired("密码不能为空"), ...])

# 后
class UpdatePasswordReq(BaseModel):
    password: str = Field(min_length=..., description="密码最少包含一个字母，一个数字，并且长度为8-16")
    # 校验 message 文案保留为 Field(..., description=...) 或自定义 validator 的 message
```
- 请求模型：字段 + 类型 + 校验（message 文案迁移到 Pydantic 的 error 文案，经 R7 异常处理器输出）；`req.data.get(...)` → `req.model_dump().get(...)` 或属性访问。
- 响应模型：marshmallow `Schema` → Pydantic `BaseModel`；`Schema(many=True).dump(objs)` → `TypeAdapter(list[Resp]).validate_python(objs)` 或 `[Resp.model_validate(o) for o in objs]`；`fields.Method("get_x")` → `@computed_field` 或 `field_validator`；`dump()` 的 key 名必须与旧版一致（前端依赖）。
- 文件上传字段（`FileField`）：不进 Pydantic body 模型——handler 用 `file: UploadFile = File(...)` 参数，转 `file.file`（BinaryIO）后调服务（服务层已是 BinaryIO 契约，R11 完成）。
- `PaginatorReq`（package/paginator）→ Pydantic（page/page_size/默认值/校验保持）。
- `internal/schema/*` 冻结解除（本计划唯一允许修改的冻结面）。

### R5 Router 登记（153 条，脚本骨架 + 手工核对）
- 脚本：扩展 `scripts/migration/extract_routes.py` 或新增 `scripts/migration/gen_routes.py`，读 route-inventory.md 生成 `internal/router/router.py` 骨架（`llmops_router = APIRouter(prefix="", dependencies=[Depends(request_context)], ...)`；每条 `llmops_router.add_api_route(path, getattr(handler, view), methods=[...])`；`<uuid:x>` → `{x}`）。
- 手工核对点：路径参数类型标注（`app_id: UUID`）、同路径多方法（GET/POST 并存）、蓝图归属（bp/openapi_bp）、公开路由（/webhook、/favicon.ico、/default-app-icon——不进认证 router）。
- 断言：生成后 `len(llmops_router.routes) + len(openapi_router.routes) == 153`（或与 route-inventory 计数一致）。
- handler 实例经 container 工厂构造（Depends 链），router 模块不直接 new handler。

### R6 lifespan + 入口（app/http/app.py）
```python
# app/http/app.py（由 Plan 1 pilot app_fastapi.py 演进；删除旧 Flask Http）
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # 1. DB 配置注入必须在 get_settings() 首次调用后、其他单例前——注意 get_settings 已 lru_cache，
    #    若在 settings 构造前注入：worker_run 包 apply_to_env（T4 已 async）并先于 get_settings()
    await worker_run(lambda s: SystemConfigService(db=s).apply_to_env())  # 时序见 T1 裁决
    engine = build_engine(); set_default_session_factory(build_sessionmaker(engine))
    app.state.engine = engine
    init_logging(); init_redis(); init_weaviate()
    if settings.mode not in ("celery", "local"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="llmops", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["GET","POST"], allow_headers=["Content-Type","Authorization"])
# 异常处理器（R7）+ favicon/default-app-icon 路由 + 两个 router include
```
- `app/http/app_fastapi.py`（pilot）删除或更名为 legacy（不再使用）；`internal/server/http.py`（Flask Http 类）、`internal/middleware/middleware.py`（flask_login）删除。
- **时序裁决（T1 定案）**：apply_to_env 与 get_settings 的先后——settings 构造在模块 import 时可能已发生；T1 以"lifespan 内先 apply_to_env 再首次使用 settings 的单例"为准，若 get_settings 已被 import 期调用（如 container 模块级单例），则 apply_to_env 失效——T1 需核查并给出确定时序（可能需 settings 增加 `reload()` 或 apply_to_env 在 settings 构造前由入口脚本先行调用）。

### R7 异常处理器（契约不变）
```python
@app.exception_handler(CustomException)          # → 200 + {code,message,data}（code=异常.code）
@app.exception_handler(ValidationError)          # → code=HttpCode.VALIDATION_ERROR + 首个 message + errors dict
@app.exception_handler(SQLAlchemyError)          # → "数据库操作失败"
@app.exception_handler(Exception)                # 开发重抛；生产 200 + {code,message,data}
```
- 与旧 `internal/server/http.py:_register_error_handler` 逐条对应（先删旧文件后新处理器不得遗漏任何分支）。

### R8 Handler 转换模式
```python
# 前
@login_required
def get_current_user(self):
    resp = GetCurrentUserResp()
    return success_json(resp.dump(current_user))
# 后（async + Depends；注册经 add_api_route 绑定方法时 FastAPI 自动剥离 self）
async def get_current_user(self, user: Account = Depends(get_current_user)):
    resp = GetCurrentUserResp.model_validate(user)
    return success_json(resp.model_dump(mode="json"))
```
- `@login_required` 删除 → `user: Account = Depends(get_current_user)` 参数；`current_user` → `user`。
- `request.get_json(force=True)` → body Pydantic 参数；`request.args` → Query/Pydantic query 模型；`request.files` → `UploadFile`。
- 返回值保持调用 `package/response` 助手（R1 已重写，签名不变）。
- **Web 侧 Depends 适配层**（`internal/server/deps.py`）持有 container 纯工厂：`def get_app_service(session: AsyncSession = Depends(get_db)) -> AppService: return create_app_service(session)`。
- handler 构造：router 内 `Depends(get_xxx_handler)` 或直接在 add_api_route 传实例方法（`app_handler.get_app`——FastAPI 对绑定方法剥离 self）。

### R9 测试基建
- conftest 增加：`client` fixture（`httpx.AsyncClient` + ASGITransport + lifespan 由 `asgi_lifespan` 包或手动进入——见 T1 裁决）、`auth_headers`（access_token 已有 fixture）。
- 契约测试：401-shape 对照 golden；153 路由冒烟（未认证 → 200 + code=unauthorized）；SSE 全链路（ChatRunner async generator → StreamingResponse 事件流断言）。
- 解除 handler/schema 测试 skip：`test/internal/handler/__init__.py`、`test/internal/schema/__init__.py` 的模块级 skip 随 T2/T4 转换逐目录移除；原测试转 async 或按新签名重写。

## 任务与批量划分

依赖序：T1（基建）→ T2（Schema）→ T3（Router）→ T4（Handler 簇）→ T5（契约回归）→ T6（收尾门禁）。T2/T3 可并行（均依赖 T1）；T4 依赖 T2/T3。每任务结束更新 `docs/migration/progress.md`。

---

### Task 1: Web 基建——response/认证依赖/异常/lifespan/旧文件删除

**Files:**
- Rewrite: `package/response/response.py`（R1，删 flask import；helper 签名不变）
- Create: `internal/server/deps.py`（R2 认证依赖 + R3 request_context 依赖 + Web 侧 container 适配函数）
- Rewrite: `app/http/app.py`（R6 lifespan + CORS + 异常处理器 R7 + favicon/icon 路由 + 空 router include 占位）
- Delete: `internal/server/http.py`、`internal/middleware/middleware.py`、`app/http/app_fastapi.py`（pilot）
- Modify: `test/conftest.py`（+client/auth_headers fixture，R9；lifespan 处理裁决后定案）
- Test: `test/package/test_response.py`（新：契约格式）、`test/app/test_app.py`（新：healthz/docs/favicon/icon/异常处理器）、`test/internal/server/test_deps.py`（新：认证依赖两分支 + request_context 写入）

**关键裁决（T1 定案）**: apply_to_env 与 get_settings 时序；lifespan 测试方式（asgi-lifespan 库 vs 手动进入）；CORS 配置与旧 flask_cors 完全一致（origins=*, methods GET/POST, headers Content-Type/Authorization, credentials）。

- [ ] **Step 1-4**: TDD 实现（R1/R2/R3/R6/R7）；旧文件删除前 grep 零消费者（`internal/server/http` 与 `internal/middleware` 的 import 方——router/handler 仍在冻结态，先删后 T3/T4 接上新路径，确认无悬空 import）。
- [ ] **Step 5**: 提交：`feat(web): FastAPI Web 基建（response 重写/认证依赖/异常/lifespan）+ 删除 Flask 旧引擎`。

---

### Task 2: Schema 层 Pydantic 化（26 文件 + PaginatorReq）

**Files:**
- Modify（全部）: `internal/schema/*.py`（R4；请求模型 FlaskForm→Pydantic、响应模型 marshmallow→Pydantic；校验 message 保留）
- Modify: `package/paginator/paginator.py`（PaginatorReq → Pydantic）
- Test: `test/internal/schema/*` 解除 skip、转 async/Pydantic 断言；契约测试（校验失败 message 与旧版一致）

**Interfaces:**
- Produces: 全部 Pydantic 模型（`CreateAppReq.model_dump()` 与旧 `req.data` 键一致；响应 `model_dump(mode="json")` key 与旧 dump 一致）。

- [ ] **Step 1**: grep 每个 FlaskForm/marshmallow Schema 的字段与校验文案 → 登记 `docs/migration/schema-mapping.md`（旧类→新模型→校验文案映射，供 T4 handler 转换参照）。
- [ ] **Step 2-4**: 逐文件转换（TDD：先写失败测试断言校验行为与响应结构，再实现）。
- [ ] **Step 5**: 提交：`refactor(schema): FlaskForm/marshmallow → Pydantic v2（校验文案保留）`。

---

### Task 3: Router 153 条登记 + 蓝图依赖挂载

**Files:**
- Rewrite: `internal/router/router.py`（R5；脚本生成骨架 + 手工核对；llmops/openapi 两个 APIRouter + 依赖挂载）
- Modify: `scripts/migration/gen_routes.py`（新，从 route-inventory 生成骨架）
- Modify: `app/http/app.py`（include_router × 2 + favicon/icon 路由落位）
- Test: `test/migration/test_route_inventory.py`（153 条与清单一致）、`test/app/test_routes_registered.py`（新：/openapi.json 含全部 153 路径）

- [ ] **Step 1**: 脚本生成骨架 → 核对（路径参数类型/同路径多方法/蓝图归属/公开路由）。
- [ ] **Step 2-4**: 登记 + 断言计数 + 测试。
- [ ] **Step 5**: 提交：`feat(router): 153 路由 FastAPI 登记（llmops/openapi + 蓝图依赖挂载）`。

---

### Task 4: Handler 簇转换（27 handler，按簇）

**Files:**
- Modify（全部）: `internal/handler/*.py`（R8；按簇批量：认证账号簇 → app 簇 → dataset 簇 → 其余）
- Test: `test/internal/handler/*` 解除 skip、转 async（TestClient 全链路：认证/CRUD/分页/上传）；`test/internal/schema/*` 联动

**注意**：handler 转换后 `@login_required` 删除、`current_user`→`user` 参数；`request.get_json`→body 参数；`request.args`→Query；`request.files`→UploadFile（转 `file.file` 给服务）。逐簇提交 + 逐簇契约测试。

- [ ] **Step 1-4**: 按簇转换（每簇一个提交 + 其 handler 测试转 async + 契约断言）。
- [ ] **Step 5**: 提交（每簇）：`refactor(handler): <簇名> 簇 FastAPI 化（Depends + Pydantic 参数）`。

---

### Task 5: 契约回归——153 冒烟 / 黄金对照 / SSE 全链路

**Files:**
- Create: `test/app/test_contract_401.py`（153 路由未认证 → 200 + code=unauthorized，对照 golden 401-shape 的 code/message/data 结构）
- Create: `test/app/test_sse_stream.py`（debug_chat/web_app_chat/assistant_agent_chat/openapi chat：SSE 事件序列 + payload + error/done，对照 Plan 2.1 SSE 黄金测试）
- Modify: `test/app/test_app.py`（/ping 认证拦截对照 golden；/default-app-icon 二进制对照）
- Create: `docs/migration/contract-report.md`（153 路由逐条：URL/方法/认证面/响应结构核对表）

- [ ] **Step 1-4**: 全链路回归 + 对照表。
- [ ] **Step 5**: 提交：`test(web): 153 路由契约回归 + SSE 全链路 + 黄金对照`。

---

### Task 6: 收尾——flask 清零（豁免外）+ 全量回归 + 进度登记

**Files:**
- Modify: `test/migration/test_no_flask_imports.py`（豁免清单收缩：移除 handler/router/schema/response/server/middleware/app-http；仅剩 internal/task、internal/migrations、package/paginator（若 PaginatorReq 仍引 flask_wtf——T2 已转 Pydantic 则移除））
- Modify: `docs/migration/progress.md`（Plan 3 完成 + Plan 4 入口）
- Test: 全量 `pytest -q`（handler/schema skip 必须已清零；预期全绿）

**门禁（最终）**：`grep -rn "from flask\|from werkzeug\|flask_weaviate\|injector" internal/ package/ app/`（豁免：internal/task、internal/migrations）输出为空。

- [ ] **Step 1-4**: 门禁收缩 + 全量回归 + 记录。
- [ ] **Step 5**: 提交：`refactor(web): Web 层 flask 清零 + 全量回归（Plan 3 完成）`。

---

## 验收标准（Done 定义）

1. **系统可运行**：`uvicorn app.http.app:app` 启动成功；`/docs` 可访问；`/healthz`（或等价的存活检查）200。
2. **153 条路由**全部登记且 URL/方法与 route-inventory 完全一致；`/openapi.json` 含全部路径；未认证访问 → **HTTP 200 + `code:"unauthorized"`**（黄金契约，非 401）。
3. **SSE 全链路**：debug_chat/web_app/assistant_agent/openapi chat 事件序列与 payload 与旧版一致（对照 SSE 黄金测试）；ping/keep-alive 保留。
4. **前端零改动**：请求/响应结构与旧版一致（code/message/data、Pydantic 校验文案、分页结构、文件上传/下载行为）。
5. **零 flask**：豁免清单外 `internal/`+`package/`+`app/` 无 flask/werkzeug/injector 导入；`internal/handler`、`internal/schema` 测试 skip 全部解除。
6. 全量测试绿；全部提交落 `release_fastApi`；`docs/migration/progress.md` 每任务更新。

## Self-Review 备注

- **契约保守主义**：本计划最大风险是把"黄金契约"改"好"（如把未授权从 200+code 改成 401、SSE 事件格式微调）——Rulebook R1/R7 与验收 #2/#3 明确禁止；实现者/审查者必须对照 golden 样例，任何"改进"都是违约。
- **与 Plan 4 接口**：`internal/task/*`（Celery 任务体仍引用旧 injector/module）与部署（entrypoint.sh 改 uvicorn、Dockerfile）留 Plan 4；`app/http/app.py` 的 `celery` 导出（旧 app 有 `celery = app.extensions["celery"]`）需在 T1 明确：Celery 独立后（Plan 1 已建 `internal/task/celery_app.py`），新 app 不再导出 celery——entrypoint 在 Plan 4 改 `celery -A internal.task.celery_app`。
- **时序深水区（T1 定案）**：apply_to_env（DB 配置注入）与 get_settings 单例的先后；若 container 模块级单例在 import 期构造了 settings，DB 注入失效——T1 必须核查所有 import 期 get_settings() 调用点并给出确定时序（可能需入口先行注入或 settings.reload）。
- **评审采纳记录**：沿用前两个计划的 SDD 流程（每任务实现+审查+修复轮）；本计划文档发布后同样欢迎外部评审（Plan 2/2.1 的外部评审抓到了真实缺陷）。
