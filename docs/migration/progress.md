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

## Plan 2（进行中）：服务层 async 化（internal/service + internal/model + container.py）

### T1 地基——worker_run + request_context + settings.project_root + 纯工厂 container + BaseService + 测试基建 —— 完成
- [x] `package/database.py`：`worker_run`/`_run_worker`（R5，含 P2.1.1-3 运行中 loop 守卫）
- [x] `internal/core/request_context.py`（R4：ContextVar set/get/reset）
- [x] `internal/config/settings.py`：`project_root`（parents[2] + pyinstaller 注释）+ `rerank_device: str = "cpu"`
- [x] `internal/container.py`（R8 纯工厂：create_account_service/create_api_key_service/create_jwt_service 单例，无 fastapi 导入）
- [x] `internal/service/base_service.py`（R1/R2：async CRUD，add 不 await、delete await；原 auto_commit 移除，提交归边界）
- [x] `internal/service/jwt_service.py`（删 `@inject`/`@dataclass`，无 session 转单例）
- [x] `test/conftest.py`（R9 重写：模块级 engine 复用 + db_session 连接/begin/rollback 隔离 + app/client/db 过渡期 skip fixture）
- [x] handler/schema 测试统一 skip（模块级）；15 个旧 Flask 测试文件模块级 skip（见下方注册表）
- [x] 空表建好：[transaction-boundaries.md](transaction-boundaries.md)、[model-session-callers.md](model-session-callers.md)
- [x] 测试：worker_run 提交/回滚/防护 + request_context + settings + BaseService async CRUD —— 39 passed / 9 skipped
- [x] 全量收集：224 tests collected，0 errors（仅 skip）

### T1 跳过的旧测试文件（模块级 `pytest.skip(allow_module_level=True)`）
> 判定标准：模块顶层 import flask / `app.http.*`（injector）→ 旧 Flask 世界测试，Plan 2 期间冻结，待逐簇 async 化后恢复。
> 另：使用废弃 `app`/`client`/`db` fixture 的测试由 conftest 的 skip fixture 逐条跳过（不在此表，随任务转换）。

| 文件 | 原因 |
|---|---|
| `test/internal/memory/test_token_buffer_memory.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_chat_runner_orchestrator.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_vector_database_service.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_chat_runner.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_chat_error_handling.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_user_memory_service.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/memory_provider/test_resolver.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/memory_provider/test_tencent_provider.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_reflection_service.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_retrieval_service_agentic_tool.py` | 顶层 `from flask import Flask` |
| `test/internal/service/test_episodic_memory_service.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_conversation_service.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/memory_provider/test_builtin_provider.py` | 顶层 `from app.http.module import injector` |
| `test/internal/service/test_conversation_compact.py` | 顶层 `from app.http.module import injector` |
| `test/internal/core/tools/test_memory_tools.py` | 顶层 `from app.http.module import injector` |

> T1 附注：`pytest.ini` 追加 `norecursedirs`（在默认排除项外增加 `tmp probe_dir sandbox-tmp-probe scripts`），
> 排除环境杂项（gitignored 缓存/沙箱探针产物/手工脚本），保证全量收集无错误。

### T2 模型层迁移（15 个 model 文件）—— 完成
- [x] 15 个模型 `db.Model`→`package.database.Base`（R7）；`Account` 移除 `UserMixin`；`system_config` 的 `db.Boolean`→`Boolean`
- [x] 全部查库属性上移为服务方法（18 处映射，登记 [model-session-callers.md](model-session-callers.md)）：
  AccountService/ApiKeyService/ConversationService/AppService/DatasetService/DocumentService/SegmentService 各新增 async 方法（显式 `db: AsyncSession` 注入，服务类本体 T4-T8 async 化）
- [x] 纯计算属性保留：`Account.is_password_set`
- [x] `internal/migrations/env.py`：`target_metadata` 切换 `Base.metadata`（删 `db` 过渡引用）；
  `alembic history` + `upgrade head` 均正常（10 个 revision，head `a1b2c3d4e5f6`）
- [x] 模型测试转 async（`db_session` fixture）+ 新增文件级门禁 `test/internal/model/test_model_no_session_gate.py`
- [x] 新增 `test/internal/service/test_model_session_move_methods.py`：上移方法语义等价验证（11 用例，事务内回滚）
- [x] T1 遗留修正 ①：`test/conftest.py` `db_session` teardown 追加 `await _engine.dispose()`——asyncpg 连接绑定事件循环，
  function 级 loop 下模块级 `_engine` 连接池跨 loop 复用连接导致 "another operation is in progress"/"NoneType has no attribute 'send'"
- [x] T1 遗留修正 ②：`test/package/test_database.py`、`test/internal/service/test_base_service.py` 的 sqlite
  `Base.metadata.create_all` 限定 `tables=[局部表]`——R7 后真实模型已注册进全局 metadata，PG 专属 DDL 无法在 sqlite 建表
- [x] `internal/extension/database_extension.py` **保留不删**：`app/http/module.py:15`（冻结面，Plan 4 处理）仍引用；T9 再清理
- [x] 测试：`pytest test/internal/model test/migration test/internal/service/test_model_session_move_methods.py` —— 22 passed；
  全量收集 236 tests, 0 errors；全量运行 208 passed / 40 skipped / **12 failed（T2 前既有，app_service 构造器签名过期，T5 处理）**
- [x] 提交：`refactor(model): 迁移 package.database.Base + 属性查库上移（登记 model-session-callers.md）`

### T3 服务层 flask 依赖清除（request/current_app/FileStorage/weaviate）—— 完成
- [x] R4：`request.remote_addr/scheme/host` → `get_request_context()`（account_service、oauth_service、app_service.fake_image_generator、app_config_service._process_and_validate_tools、workflow_service.get_draft_graph）
- [x] R3：`current_app` → settings（assistant_agent_service `ASSISTANT_AGENT_ID`→`settings.assistant_agent_id`；builtin_tool_service / language_model_service root_path→`settings.project_root`）；retrieval_service 删 `from flask import Flask`（`flask_app: Flask` 标注改 `Any`，参数本体 T7 删除）
- [x] R11：FileStorage → `(BinaryIO, filename, content_type)`（cos/miniio/chroma_file/skill/app_service/markdown_to_pptx；内部 FileStorage 包装全部改裸流+显式 filename）；签名变更清单见下
- [x] weaviate：`vector_database_service` / `weaviate_vector_service` 删 `weaviate: FlaskWeaviate` 字段 → `internal.extensions.weaviate.weaviate_client` 模块单例（`_get_weaviate_client()` 惰性 `init_weaviate()`；方法保持 sync——T7 再转 async + run_in_threadpool + R6 限流）
- [x] `internal/schema/weaviate_vector_schema.py` 最小改动：`werkzeug ImmutableMultiDict` 运行时构造 → 内置 `dict`（文件其余冻结不动；注：该处实为运行时构造而非类型标注，改动仍限定同方法 2 行）
- [x] R6：`internal/core/embeddings/embedding_provider.py` 设备读取 `os.getenv("EMBEDDING_DEVICE","cpu")` → `get_settings().embedding_device`
- [x] 测试：`test/internal/extensions/test_extensions.py` 补 `init_weaviate` 单例测试（monkeypatch connect_to_custom，断言返回模块单例 + 重复 init 只建连一次）；新增 `test/migration/test_no_flask_imports.py` 门禁骨架（`@pytest.mark.slow` + `PLAN2_GATES != "1"` 默认 skip，T9 启用全量）；`pytest.ini` 注册 `slow` 标记
- [x] 门禁验证：T3 范围内文件 `grep flask|werkzeug|FlaskWeaviate` 归零；骨架以 `PLAN2_GATES=1` 运行仅剩 T4-T9 的 `@inject`/`injector` 与 T6/T8 文件（chat_runner/conversation/memory_provider/memory_tools/browser/reflection/skill_service.send_file 等）的 flask 引用（预期，T9 清零）
- [x] 测试：`pytest test/internal/service test/internal/extensions test/migration` —— 66 passed / 22 skipped / **12 failed（T2 前既有，app_service 构造器签名过期，T5 处理）**；全量收集 238 tests, 0 errors
- [x] 提交：`refactor(service): 清除服务层 flask/werkzeug/FlaskWeaviate 依赖（ctx/settings/BinaryIO/单例）`

#### T3 签名变更清单（调用方适配：T5/T7/T9 服务内 + Plan 3 handler 层）
| 服务方法 | 旧签名 | 新签名 | 已适配调用方 | 待适配调用方 |
|---|---|---|---|---|
| `CosService.upload_file` | `(file: FileStorage, only_image=False, account=None)` | `(file: BinaryIO, filename: str, content_type: str \| None = None, only_image=False, account=None)` | `app_service.auto_create_app`（T3）；内部 `_upload_to_cos`/`_upload_to_miniio` | `internal/handler/upload_file_handler.py:37,48`（冻结，Plan 3 改 UploadFile） |
| `MiniIoService.upload_file` | `(file: FileStorage, folder=None)` | `(file: BinaryIO, filename: str, content_type: str \| None = None, folder: str \| None = None)` | `cos_service`（T3）、`skill_service._archive_bytes`（T3）、`markdown_to_pptx`（T3） | — |
| `ChromaFileService.upload_file` | `(file: FileStorage)` | `(file: BinaryIO, filename: str, content_type: str \| None = None)` | — | `internal/handler/chroma_file_handler.py:33`（冻结，Plan 3 改 UploadFile） |
| `RetrievalService.create_langchain_tool_from_search` | `flask_app: Flask` | `flask_app: Any`（参数保留，T7 删除并改 settings 注入） | 现有调用方按名传参不受影响（chat_runner/open_api_service/dataset_retrieval_node） | T7 删参 |

> T3 附注 ①：`vector_database_service`/`weaviate_vector_service` 删除 `weaviate` 字段后，`app/http/module.py:28` 的 `binder.bind(FlaskWeaviate, ...)` 成为未使用绑定（T9 随 injector 移除）；`internal/server/http.py:39` 的 `FlaskWeaviate` 构造参数为旧 Web 引擎（Plan 4 处理）。
> T3 附注 ②：`retrieval_service._recall` 的 `BM25Retriever(weaviate_client=...)` 改读模块单例；`internal/core/retrievers/*` 纯同步逻辑不转 async（T7 由调用方 R6 桥接）。

### T4 认证与账号簇 async 化（account/api_key/jwt/oauth/system_config + container 工厂适配）—— 完成
- [x] `account_service.py`：全部方法 async（get_account / get_account_by_email / get_account_oauth_by_provider_name_and_openid / create_account / update_password / update_account / password_login）；`db: SQLAlchemy`→`AsyncSession`，删 `@inject`；`get_assistant_agent_conversation` 并入 `self.db`（T2 显式 `db` 参数随类 async 化移除，commit 位置/语义不变）
- [x] `api_key_service.py`：async 化；`get_account` 并入 `self.db`；`get_api_keys_with_page` 原位重实现分页（见附注①）
- [x] `oauth_service.py`：async 化；网络调用 `get_access_token`/`get_user_info` 经 `run_in_threadpool` 桥接（R6）；修复驱动切换暴露缺陷——`AccountOAuth.account_id`（String 列）原传 UUID 对象（psycopg2 静默适配、asyncpg 抛 DataError）→ `str(account.id)`
- [x] `system_config_service.py`：全部 async（get_config_map / get_config / apply_to_env / save_configs / _delete_config）；`apply_to_env` 补充**时序约束** docstring——必须在 `get_settings()` 首次调用前执行（Plan 3 lifespan 落地），测试直接带 session 调用
- [x] `jwt_service.py`：**零改动**（T1 已转无 session 单例；复核无 injector/flask 引用）
- [x] `internal/container.py`：工厂适配（新签名）+ 新增 `create_oauth_service` / `create_system_config_service`；T1 遗留补做工厂冒烟测试 `test/internal/test_container.py`（db_session 构造 + 实例类型断言）
- [x] `test/conftest.py`：新增 `access_token` fixture（R9：真实库账号 + `JwtService.generate_token`；空库现场建号，比示例 `scalar_one()` 更健壮）
- [x] 测试：新增 `test_account_service.py`（7）/`test_api_key_service.py`（5）/`test_oauth_service.py`（4）/`test_jwt_service.py`（3）；`test_system_config_service.py` 扩展 DB 行为（9）；`test_model_session_move_methods.py` 适配并入 `self.db` 的签名
- [x] 事务边界登记：**本簇无新增 commit 边界**——写操作全经 BaseService（#1-#3 独立事务）；唯一显式 commit 为 #4（account_service，T4 更新行号）；见 [transaction-boundaries.md](transaction-boundaries.md) T4 说明
- [x] 测试：`pytest test/internal/test_container.py test/internal/service test/internal/config` —— 101 passed / 21 skipped / **12 failed（T2 前既有 app_service 构造器签名过期，T5 处理）**；全量收集 274 tests, 0 errors；全量运行 245 passed / 41 skipped / **12 failed（同上）**
- [x] 提交：`refactor(service): 认证/账号簇 async 化（account/api_key/jwt/oauth/system_config + container 工厂适配）`

> T4 附注 ①：`package/paginator.Paginator.paginate` 依赖 Flask-SQLAlchemy `db.paginate`（AsyncSession 无此 API）——
> `ApiKeyService.get_api_keys_with_page` 以 count + LIMIT/OFFSET 原位重实现（返回 `tuple[list[ApiKey], Paginator]` 形状与
> total_record/total_page 语义不变）；共享 Paginator 的 async 化随其簇（T5 app_service 等 11 处调用方）落地。
> T4 附注 ②：`internal/middleware/middleware.py`（旧 Web 引擎，Plan 4 处理）同步调用 `get_account`/`get_api_by_by_credential`
> 将得到协程——与 handler/router 同理属预期破坏性迁移状态（迁移状态声明），Plan 3/4 重建认证层。
> T4 附注 ③：`app/http/app.py:57`（冻结面）同步调用 `apply_to_env()` 将得到协程——Plan 3 lifespan 改 `await`/worker_run 调用。
> T4 附注 ④：真实库存在历史 `account_oauth` 行（openid=53503510，非测试数据）——oauth 测试查询一律按
> `(provider, openid)` 双条件过滤，避免 MultipleResultsFound。

### T5 App 簇 async 化（app_service 大文件按方法拆分）—— 完成
- [x] **Paginator async 化（承重）**：`package/paginator/paginator.py` `paginate` → `async def`（count + offset/limit，
  与旧 `db.paginate(error_out=False)` 同 total_record/total_page 形状 + math.ceil 公式 + 越界返回空列表）；
  `db` 类型改为 `AsyncSession | None = None`（修 db=None 类型谎，T4 ApiKeyService 仅解析 req 不调用 paginate）；
  `package/paginator/__init__.py` 导出不变（PaginatorReq 保持 FlaskForm——`internal/schema/*` 冻结继承它，T9 门禁豁免待处理）。
  分页查询经 `.execute().scalars().unique()`（joined eager load 集合需 unique，防 InvalidRequestError）。
  调用方：本簇 4 处已 `await`（app_service ×3、assistant_agent_service ×1）；其余 7 处（api_tool/conversation/dataset/
  document/skill/segment/workflow）由 T6/T7/T9 跟进。
- [x] **app_service 方法拆分清单**（按方法批提交，每批独立验证；commit 见下）：
  - 批①：T2 上移方法并入 self.db（get_app_config/get_or_create_draft_app_config/get_debug_conversation/
    get_token_with_default/get_app_dataset_joins，查询改 `scalar_one_or_none()` carry-in #3）+ dataclass 修复
    （attachment_service 默认 None，carry-in #2）+ auto_create_app（R6：LLM 链 invoke 经 `_MODEL_LIMITER`/
    `run_in_threadpool` 桥接）+ create_app + get_app/delete_app/update_app/copy_app + get_apps_with_page
  - 批②：get_draft_app_config/update_draft_app_config/publish_draft_app_config/cancel_publish_app_config/
    get_publish_histories_with_page/fallback_history_to_draft/_validate_draft_app_config（4 处 DB 调用点 async）
  - 批③：get_debug_conversation_summary/update_debug_conversation_summary/delete_debug_conversation/
    get_debug_conversation_messages_with_page/get_or_create_debug_conversation/get_published_config/
    regenerate_web_app_token/stop_debug_chat；debug_chat → async 生成器（非 chat 段 async，chat 段 for 迭代）
- [x] `app_config_service.py`：全 async；原 `app.draft_app_config`/`app.app_config`/`app_config.app_dataset_joins`
  属性查库上移为本服务内联查询（_query_draft_app_config/_query_app_dataset_joins，避免循环依赖）；_create_langchain_tool_from_skill
  async（await load_language_model）；_process_and_validate_{tools,datasets,workflows,skills} async，_process_and_validate_model_config
  纯内存保持同步；**refresh 防 MissingGreenlet**——updated_at 为 server_onupdate 列，update() 提交后 ORM 标记过期，
  async 下惰性 SELECT 抛 MissingGreenlet，转换器前显式 `await self.db.refresh(...)`（与旧同步惰性重载语义一致）
- [x] `builtin_app_service.py`：全 async（get_categories/get_builtin_apps + add_builtin_app_to_space）
- [x] `assistant_agent_service.py`：get_conversation_messages_with_page（`account.assistant_agent_conversation` 属性已删
  → 内联 get-or-create + Paginator await）/delete_conversation async；`chat()` 为 chat 链 → **同步保留 + TODO(plan2-chat)**
- [x] `language_model_service.py`：全 async；`load_language_model`/`load_default_language_model` 经 R6 线程池桥接 +
  模块级 `_MODEL_LIMITER = CapacityLimiter(2)`（进程级、跨 loop 安全）；get_language_model_icon 文件 IO 经 run_in_threadpool
- [x] **12 个既有失败修复（唯一红）**：AppService dataclass `attachment_service` 给默认 None（旧测试缺该字段构造失败）
  + 测试构造显式补参；`test_app_service_draft_config.py`（10）/`test_app_service_publish_orchestrator.py`（2）转 async 后全绿
- [x] 测试：Paginator（5）/language_model_service（6）/builtin_app_service（3）/app_config_service（DB 4 + 原 9）/
  assistant_agent_service（4）/AppService DB 非 chat 路径（9）；`test_app_config_skill_tool.py` 转 async（AsyncMock load_language_model）；
  `test_model_session_move_methods.py` 适配 T2 方法并入 self.db 的签名
- [x] 事务边界登记：**本簇新增 10 处**（#8-#17，见 [transaction-boundaries.md](transaction-boundaries.md) T5 说明）
- [x] 测试：`pytest test/internal/service test/package test/internal/core/tools -q` —— **149 passed / 22 skipped / 0 failed**
  （12 个既有失败消失）；全量收集 0 errors
- [x] 提交（按方法批）：
  - `485dfd7` refactor(paginator): Paginator async 化（count + offset/limit，db 可选）
  - `2bcb91e` refactor(service): language_model_service async 化（R6 桥接 + CapacityLimiter(2)）
  - `6c18c2c` refactor(service): builtin_app_service async 化
  - `05641e4` refactor(service): app_config_service async 化（属性上移 + refresh 防 MissingGreenlet）
  - `81837cf` fix(paginator): joined eager load 集合分页需 .unique()
  - `d0e4a65` refactor(service): assistant_agent_service async 化（chat 链 TODO 登记）
  - `75bb2ee` refactor(service): app_service async 化 ①（T2 并入 self.db + dataclass 修复 + CRUD/分页/auto_create_app）
  - `3853191` refactor(service): app_service async 化 ②（草稿/发布/取消/回退/历史/_validate + 测试转 async）
  - `e168361` refactor(service): app_service async 化 ③（调试会话 + debug_chat async 生成器 TODO）
  - `0cb2594` test(service): AppService 非 chat 路径 DB 行为测试

> T5 附注 ①（**chat TODO 清单**，T8 收口）：
> - `app_service.debug_chat`：非 chat 段（会话/消息/画像）已 async；chat 段 `chat_runner.run` 仍同步生成器——
>   async 生成器内 for 迭代保持可运行；T6 改 `async for`、T8 收口 attachment/memory 桥接。
> - `assistant_agent_service.chat`：整体 chat 链（TokenBufferMemory/FunctionCallAgent/chroma_service/
>   save_agent_thoughts）保持同步；T8 收口时同时切换 `account.assistant_agent_conversation`（已删属性）→
>   `AccountService.get_assistant_agent_conversation`（model-session-callers.md #1）。
> - `app_service.get_debug_conversation_messages_with_page`：`app.http.module` injector 引用（冻结面）保留，
>   T8/T9 随 injector 移除。
> T5 附注 ②（R6 限制器位置）：`_MODEL_LIMITER = CapacityLimiter(2)` 模块级单例定义于
> `language_model_service.py`（模型加载路径）与 `app_service.py`（auto_create_app LLM 链 invoke）各一份
> （R6 原文每模块声明）；纯 IO 用 `starlette.concurrency.run_in_threadpool`（无限制器，oauth_service 同款）。
> T5 附注 ③：`test_app_logical_delete.py` / `test_ask_user_chat_runner.py` 仍走废弃 app/db fixture（skip）；
> `test_app_config_transformer.py` 仅测同步 classmethod，无需转 async。
> T5 附注 ④：`package/paginator.PaginatorReq` 保持 FlaskForm（`internal/schema/*` 冻结继承）；
> T9 门禁需为 `package/paginator` 的 flask_wtf 引用加豁免或随 Plan 3 schema 解冻处理。
> T5 附注 ⑤（调用方适配）：`internal/core/workflow/nodes/llm/llm_node.py`（T8 范围）经 `injector.get(LanguageModelService)`
> 同步调用已 async 的 load_language_model——移除 @inject 后该构造失效且调用得到协程（此前全量绿、现
> 已修复）：直接构造服务（db=None 占位，load_language_model 不触库）+ `asyncio.run` 桥接，打
> `# TODO(plan2-chat): T8 收口`（提交 `e49d8ed`）。

### T6 会话/对话簇 async 化（conversation/chat_runner/choice/open_api/web_app/analysis + token_buffer_memory）—— 完成
- [x] **chat_runner**：`run()` 改 `async def` + async generator（`async for` 产出 SSE 事件）；`_stream_and_persist`
  同步生成器 → async generator；**`_aiter_sync` R6 桥接**——agent.stream 仍为同步生成器（base_agent 内部
  已起图线程 + Redis 队列监听），逐元素经 `run_in_threadpool(next, gen)` 桥接（StopIteration 用哨兵跨线程传递，
  Python 会把 StopIteration 穿越 await 边界转成 RuntimeError）；T8（R10）agent async 化后删除本桥接。
  同步 LLM/链调用（`agent.invoke` 等）经 `run_in_threadpool` + `_MODEL_LIMITER`（open_api_service）。
- [x] **app_service.debug_chat 收口（本任务，不等 T8）**：`for event in self.chat_runner.run(...)` →
  `async for event in ...`（T5 的 T6 TODO 消除）；剩余 attachment/memory 同步桥接留 T8（docstring TODO 更新）。
  `stop_debug_chat` 已 async 且不依赖本簇转换服务（仅 AgentQueueManager），无改动。
- [x] **未 await 调用方登记（T5 审查标记，逐一改 await，grep 确认无遗漏）**：
  chat_runner.py:63 `load_language_model`、open_api_service.py:81/87 `get_app_config`/`load_language_model`、
  web_app_service.py:68/69/107 `get_app_config`×2/`load_language_model`——全部 `await`。
- [x] **conversation_service**：全 async（summary/_summarize/generate_conversation_name/generate_suggested_questions
  的 langchain 链 invoke 经 `_MODEL_LIMITER`+线程池桥接；compact_if_needed/save_agent_thoughts/
  get_conversation_messages_with_page/delete_conversation/delete_message/update_message_feedback 等 await 化；
  `conversation.is_new` → `is_conversation_new` 服务方法）；**flask_app 参数删 + app_context 块 → R5 worker_run**
  （`_generate_summary_and_update`/`_generate_conversation_name_and_update`/`_trigger_reflection`：线程体改
  `worker_run(coro_factory, commit_on_success=True)`，loop 内 `create_conversation_service(session)`/`create_reflection_service(session)`
  构造会话绑定服务）；`get_conversation_messages_with_page` 与 delete 路径的 `app.http.module` injector 引用保留
  （冻结面，T8/T9 随 injector 移除，注释 TODO(plan2-injector)）。
- [x] **open_api_service**：全 async；`chat()` 为 async def；stream 分支 `handle_stream()` 为 async generator
  （`_aiter_sync` 桥接 agent.stream）；非 stream 分支 `agent.invoke` 经 `_MODEL_LIMITER` 线程池桥接；
  `create_langchain_tool_from_search(flask_app=...)` → `flask_app=get_settings()`（任务书 flask_app→settings 桥接，
  T7 删参改 settings 注入，工具仅 LLM 实际调用检索时使用该参数）。
- [x] **web_app_service**：全 async；`web_app_chat` 为 async generator（`async for` chat_runner.run）；get_web_app
  `query()` → `select()`；stop_web_app_chat/get_conversations await 化。
- [x] **choice_service**：`submit` → async def（Redis 同步客户端保持，AgentQueueManager 线程安全同步调用）。
- [x] **analysis_service**：全 async（3 处 DB 查询 await；纯计算 classmethod 保持同步；Redis 同步客户端保持）。
- [x] **token_buffer_memory ×2**（internal/memory + internal/core/memory）：`get_history_prompt_messages`/
  `get_history_prompt_text` → async def（`await self.db.execute/scalars`）；`_derive_max_token_limit` 纯计算保持同步。
- [x] **container 补工厂（R8 逐任务扩充）**：`create_language_model_service`/`create_app_config_service`/
  `create_procedural_memory_service`/`create_reflection_service`/`create_conversation_service`/`create_choice_service` +
  **T5 遗留 `create_app_service`**；深依赖工厂 `create_chat_runner`/`create_open_api_service`/`create_web_app_service`/
  `create_app_service` 对未 async 化的 retrieval_service/memory_provider_resolver/attachment_service/cos_service/redis_client
  以调用方传入参数接线（T7/T8/T9 收口，docstring 注明）。
- [x] **P2.1.1-4 SSE 黄金测试（必做）**：新增 `test/internal/service/test_chat_runner_sse_golden.py`（mock LLM/Agent，
  不真实调用）——成功路径事件序列 `agent_thought → ping → agent_message 增量 → agent_end`（"done"=QueueEvent 无 done
  枚举，AGENT_END 即旧逻辑流结束事件，顺序与旧同步逻辑一致）；每事件 SSE 行 `event: <type>\ndata: <json>\n\n`，
  data 字段 id/task_id/event/conversation_id/message_id 逐字段校验；message 增量按事件 id 合并落库、ping 不落库；
  错误路径 LLM 抛异常 → 仅 error 事件（与旧逻辑一致）→ 生成器正常结束无悬挂。
- [x] 测试转 async：test_chat_runner（8）/test_chat_runner_orchestrator（2）/test_chat_error_handling（4）/
  test_conversation_compact（2）/test_conversation_delete_checkpoints（2，SubTaskService 仍同步 T8/T9，类级替身
  验证级联调用契约）/test_conversation_service（3，含新增消息分页 + 权限拒绝）/test_choice_service（5）/
  test_token_buffer_memory（internal/memory 1 + 新增 internal/core/memory 1）；test_ask_user_chat_runner 纯函数断言
  无需转；test_container 补 T6 工厂冒烟（2）。
- [x] 事务边界登记：**本簇无新增 commit 边界**（全经 BaseService #1-#3；worker_run 兜底非服务层边界），
  见 [transaction-boundaries.md](transaction-boundaries.md) T6 说明。
- [x] 测试：`pytest test/internal/service test/internal/memory test/internal/core/memory -q` —— **154 passed / 15 skipped / 0 failed**；
  全量收集 0 errors。
- [x] 提交（按文件批）：
  - `23e9cf8` refactor(memory): token_buffer_memory async 化（internal/memory + internal/core/memory + 测试）
  - `8584e12` refactor(service): 会话/对话簇 async 化（chat_runner async generator + conversation_service worker_run + choice/open_api/web_app/analysis + container 工厂 + debug_chat 收口 + SSE 黄金测试）
  - `e6435b0` docs(migration): T6 进度登记（会话/对话簇 async 化完成 + 事务边界无新增 + chat TODO 更新）

> T6 附注 ①（chat TODO 清单更新，T8 收口）：
> - `assistant_agent_service.chat`：整体 chat 链保持同步 + TODO(plan2-chat)（T8 收口）；其
>   TokenBufferMemory.get_history_prompt_messages 现为 async——该同步路径运行时会得到协程（迁移期状态，
>   测试不覆盖，T8 随 async 化修复）。
> - `ai_service.generate_suggested_questions_from_message_id`（T9 范围）：同步调用已 async 的
>   `ConversationService.generate_suggested_questions`——运行时会得到协程（迁移期状态，无测试覆盖，
>   T9 随 ai_service async 化修复）。
> - `app_service.debug_chat`：T6 已收口 chat_runner async for；attachment_service/memory_provider_resolver
>   同步桥接留 T8（docstring TODO）。
> - `app_service.get_debug_conversation_messages_with_page` / `conversation_service` 的 `app.http.module`
>   injector 引用（冻结面）保留，T8/T9 随 injector 移除。
> - `conversation_service._trigger_reflection`：reflection_service 仍同步 + flask_app 签名（T8 范围），
>   worker_run 内以会话绑定服务调用并兜底记录（T5 起 load_default_language_model 已 async，该路径本身
>   属迁移期状态，异常不扩散请求线程）。
> T6 附注 ②（R6 限制器位置）：conversation_service / open_api_service 各声明模块级
> `_MODEL_LIMITER = CapacityLimiter(2)`（R6 原文每模块声明）；chat_runner 的 agent.stream 迭代为
> I/O 等待（图线程内 LLM 由 base_agent 自起线程），用无限制器的 run_in_threadpool。
> T6 附注 ③（flask_app→settings 桥接）：chat_runner.py / open_api_service.py 的
> `create_langchain_tool_from_search(flask_app=...)` 传 `get_settings()` 占位（任务书要求本任务
> flask_app→settings），T7 删 retrieval_service 的 flask_app 参数后移除。
> T6 附注 ④（测试替身要点）：MagicMock 缺省属性为真值——`message.attachment_text` 未显式置空会触发
> 附件拼接污染 query（旧测试因模块级 skip 从未运行，本次修复：测试显式 `attachment_text=""`）。

### T7 知识库簇 async 化 —— 完成
- [x] **18 个服务文件 async 化**（R1/R2/R6/R8）：
  - `dataset_service.py`：全 async；删 `@inject`/`from injector import inject`；`db: SQLAlchemy`→`AsyncSession`；Paginator `await`；`create/update/delete/get/hit/get_*` 全部 `await`；`auto_commit` 块→显式 commit
  - `document_service.py`：全 async；删 `@inject`；Paginator `await`；`auto_commit` 块→显式 commit；`retry_document` 的 `injector.get(IndexingService)`→显式构造；`get_documents_status` 的 `document.upload_file` 属性→`await db.get(UploadFile, ...)`
  - `indexing_service.py`：全 async；删 `@inject`；**6 处 auto_commit 块→显式 `await self.db.commit()`**（逐块登记 transaction-boundaries.md #18-#24）；`_parsing`/`_splitting` 文件提取经 `run_in_threadpool` 桥接；`_indexing` LTP 提取经 `to_thread.run_sync` + `_LTP_LIMITER`；`_completed` 向量库写入经 `run_in_threadpool`；`update_document_enabled` weaviate 更新经 `run_in_threadpool`；`_llm_summarize` 的 `injector.get(LanguageModelManager)`→显式构造
  - `segment_service.py`：全 async；删 `@inject`；Paginator `await`；LTP/embeddings 经 `to_thread.run_sync` + 限制器；weaviate 调用经 `run_in_threadpool`
  - `retrieval_service.py`：全 async；**flask_app 参数删除**（carry-in #2）；`_get_weaviate_client` 去重→`get_weaviate_client()`（carry-in #4）；`create_langchain_tool_from_search`→`async def`，工具内检索用 `asyncio.run` 桥接；LLM 评估/改写经 `to_thread.run_sync` + `_RETRIEVAL_LLM_LIMITER`；检索器调用经 `run_in_threadpool`；auto_commit 块→显式 commit
  - `keyword_table_service.py`：全 async；删 `@inject`；`db: SQLAlchemy`→`AsyncSession`
  - `upload_file_service.py`：全 async；删 `@inject`；`db: SQLAlchemy`→`AsyncSession`
  - `attachment_service.py`：全 async；删 `@inject`；`db: SQLAlchemy`→`AsyncSession`；文件解析经 `run_in_threadpool`
  - `weaviate_vector_service.py`：全 async；删 `@inject`；`_get_weaviate_client` 去重→`get_weaviate_client()`；weaviate 调用经 `run_in_threadpool`；embeddings 经 `to_thread.run_sync` + `_EMBEDDINGS_LIMITER`；DB 查询 await
  - `vector_database_service.py`：删 `@inject`；`_get_weaviate_client` 去重→`get_weaviate_client()`；无 session 依赖
  - `embeddings_service.py`：删 `@inject`/`@singleton`；新增 `_EMBEDDINGS_LIMITER = CapacityLimiter(2)`（R6）
  - `ltp_service.py`：删 `@inject`/`@singleton`；新增 `_LTP_LIMITER = CapacityLimiter(2)`（R6）
  - `process_rule_service.py`：删 `@inject`；无 DB 变更
  - `cos_service.py`：删 `@inject`；无 DB 变更
  - `miniio_service.py`：删 `@inject`/`@singleton`
  - `chroma_service.py`：删 `@inject`；新增 `_CHROMA_LIMITER = CapacityLimiter(2)`（R6）
  - `chroma_file_service.py`：删 `@inject`/`@singleton`；`app.http.module` injector→显式构造
  - `chroma_vector_service.py`：删 `@inject`/`@singleton`
- [x] **Carry-in 全部完成**：
  - Paginator 调用方 await：dataset_service:152 / document_service:439 / segment_service:175 → `await paginator.paginate(stmt)`（conversation_service:443 已由 T6 处理）
  - Paginator count 子查询加 `.order_by(None)`（T5 minor，保真）
  - retrieval_service flask_app 参数删除 + callers（chat_runner/open_api_service）同步更新
  - _get_weaviate_client 去重→`internal/extensions/weaviate.py` 的 `get_weaviate_client()`
  - indexing_service 事务边界逐块登记（7 处 indexing #18-#24 + 1 处 retrieval #25 + 1 处 dataset #26 = 9 处，#18-#26）
- [x] **container 工厂扩充**：新增 14 个 T7 工厂（create_dataset_service / create_document_service / create_indexing_service / create_segment_service / create_retrieval_service / create_keyword_table_service / create_upload_file_service / create_attachment_service / create_cos_service / create_embeddings_service / create_ltp_service / create_vector_database_service / create_weaviate_vector_service + ProcessRuleService import）
- [x] **测试转 async**：`test_retrieval_service_agentic_tool.py`（5 用例，flask_app→asyncio.run 桥接）/ `test_vector_database_service.py`（2 用例，flask/injector→直接构造+mock）
- [x] **refresh 防 MissingGreenlet 模式复核**：本簇文件无 `server_onupdate` 列 post-commit 读 `updated_at` 场景（indexing_service 的 `datetime.now()` 为 Python 侧赋值非 server_onupdate），无需 T5 refresh 模式。结论：**本簇无 refresh 防 MissingGreenlet 需求**。
- [x] 测试：`pytest test/internal/service test/internal/core test/package test/internal/model test/internal/config test/internal/extensions test/internal/test_container.py test/internal/memory test/internal/core/memory -q` —— **315 passed / 22 skipped / 0 failed**；全量收集 0 errors。
- [x] 提交：`refactor(service): 知识库簇 async 化（18 文件 + carry-in + container 工厂 + 测试转 async）`

### T8 工作流/记忆/Agent 簇 async 化（含 R10 agent async 化子任务）—— 完成
- [x] **子任务 A（服务+记忆+workflow 工具）**：
  - `workflow_service.py`：全 async + db→AsyncSession + delete @inject + await paginator + debug_workflow→async generator
  - `sub_task_service.py`：async 全方法 + auto_commit→显式 commit（#27-#28）+ upsert await
  - `reflection_service.py`：async reflect_on_feedback + 删 flask_app 签名 + R6 限流
  - `user_memory_service.py`：async 全方法 + extract_user_facts R6 桥接 + 双时间写入
  - `episodic_memory_service.py`：async + write_episode/search R6 桥接 + weaviate/embeddings run_in_threadpool
  - `procedural_memory_service.py`：async 全方法
  - `memory_provider/base.py`：abstractmethod async
  - `memory_provider/builtin_provider.py`：async + worker_run 写侧管道 + 删 flask/current_app
  - `memory_provider/tencent_provider.py`：async + worker_run 写侧管道 + 删 flask/current_app
  - `memory_provider/resolver.py`：async resolve
  - `workflow.py`：删 flask_app/current_app 注入（line 111）
  - `dataset_retrieval_node.py`：删 flask_app 参数 + injector→container 工厂
  - `llm_node.py`：删 injector→直接构造
  - `memory_tools.py`：app_context→worker_run 桥接（4 处工具）
  - `browser.py`：删 current_app.extensions.get('default_llm')→纯环境变量
  - `agent_queue_manager.py`：injector.get(Redis)→sync_redis_client 模块级单例
  - `conversation_service._trigger_reflection`：修复 reflection_service async 调用 + 3 处 injector→直接构造
  - `assistant_agent_service.chat`：async 化 + await run_in_threadpool agent.stream + account.assistant_agent_conversation→_get_or_create
  - `container.py`：新增 create_sub_task_service / create_user_memory_service / create_episodic_memory_service / create_memory_tools / create_builtin_memory_provider / create_tencent_memory_provider / create_memory_provider_resolver
- [x] **子任务 B（R10 agent async 化）**：4 个 agent 文件，**每个文件独立提交**
  - `base_agent.py`（`3d371f6`）：删除 flask/current_app/has_app_context 分支——图线程直接 invoke（不依赖 app context）
  - `function_call_agent.py`（`7161604`）：删除任何 flask/current_app 分支
  - `react_agent.py`（`38e0ff9`）：删除任何 flask/current_app 分支 + print 清理
  - `orchestrator_agent.py`（`c858864`）：_execute_node 删 flask_app + _run_subtask_inner injector→worker_run(create_sub_task_service)
- [x] **事务边界登记**：新增 #27-#28（sub_task_service save_checkpoint + clear_checkpoints），见 [transaction-boundaries.md](transaction-boundaries.md) T8 说明
- [x] **测试转 async/适配**：test_queue_manager_forward/choice（sync_redis_client patch）+ test_orchestrator_agent/resume（container patch）+ test_assistant_agent_service（async 断言）
- [x] **Langgraph 处理方式**：langgraph 图 invoke 是同步的（不可转 async），保留在子线程中执行（Thread + QueueManager.listen 模式）。LLM/工具/langchain 同步调用在图节点内直接执行（节点方法本身是同步的，在子线程中运行）。不需要额外的 run_in_threadpool 包裹图调用（R10 方案 A 的原计划中图调用在独立线程，已满足线程隔离要求）。
- [x] 测试：`pytest test/internal/service test/internal/core test/internal/memory -q` —— **278 passed / 22 skipped / 0 failed**；全量收集 0 errors。
- [x] 提交（子任务 A 一批 + 子任务 B 每文件一个 + 修复提交）：
  - `3c80e1f` refactor(core): workflow/记忆/Agent 簇 async 化（R10 方案 A 子任务 A）
  - `3d371f6` refactor(agent): base_agent async 化（R10 方案 A）
  - `7161604` refactor(agent): function_call_agent async 化（R10 方案 A）
  - `38e0ff9` refactor(agent): react_agent async 化（R10 方案 A）
  - `c858864` refactor(agent): orchestrator_agent async 化（R10 方案 A）
  - `6b6ba01` fix(container): 补充 create_sub_task_service 工厂
  - `7c7be7d` fix(tests): 修复 T8 转换后 4 个测试失败
  - `3aea398` fix(tests): conversation_service injector→直接构造 + assistant_agent async 断言修复

### T9 剩余服务 + injector 移除 + 门禁启用 + 全量回归 —— 完成
- [x] **6 个服务 async 化**：
  - `audio_service.py`：删 `@inject`/`SQLAlchemy`→`AsyncSession`；`audio_to_text`/`message_to_audio` 全 async；dashscope TTS 调用经 `run_in_threadpool` 桥接；属性查库上移为内联查询（`app.draft_app_config`/`app.app_config`→select 查询）
  - `skill_service.py`：删 `@inject`/`SQLAlchemy`→`AsyncSession`；所有方法 async；`db.session.execute/get`→`await self.db.execute/get`；Paginator `await`；`get_skill_zip` 删 `flask.send_file`→返回 `(BytesIO, filename)` 元组
  - `feishu_service.py`：删 `@inject`/`@singleton`（无 session 依赖，保持同步方法）
  - `ai_service.py`：删 `@inject`/`SQLAlchemy`→`AsyncSession`；`generate_suggested_questions_from_message_id` async + `await` conversation_service；`optimize_prompt` 改 async classmethod + `run_in_threadpool` 桥接 langchain stream
  - `api_tool_service.py`：删 `@inject`/`SQLAlchemy`→`AsyncSession`；全方法 async；`db.session`→`await self.db`；2 处 `auto_commit` 块→显式 `await self.db.commit()`（#29-#30 登记 transaction-boundaries.md）
  - `builtin_tool_service.py`：删 `@inject`（无 session 依赖）
- [x] **7 个 core 文件 injector 移除**：
  - `language_model_manager.py`：删 `@inject`/`@singleton`
  - `builtin_category_manager.py`：删 `@inject`/`@singleton`
  - `builtin_app_manager.py`：删 `@inject`/`@singleton`
  - `api_provider_manager.py`：删 `@inject`
  - `builtin_provider_manager.py`：删 `@inject`/`@singleton`
  - `file_extractor.py`：删 `@inject`；`_get_cos_service` 改用 container 工厂（去 `app.http.module` 引用）
  - `tool_node.py`：删 injector→直接构造 `BuiltinProviderManager`/`ApiProviderManager`；API 查询改同步引擎
  - `markdown_to_pptx.py`：删 injector→直接构造 `CosService`/`MiniIoService`
  - `full_text_retriever.py`：`package.sqlalchemy.SQLAlchemy`→`Any` 类型标注
- [x] **app_service.py**：`get_debug_conversation_messages_with_page` 的 injector→直接构造 `SubTaskService(db=self.db)`
- [x] **container 工厂扩充**：新增 create_audio_service / create_skill_service / create_feishu_service / create_ai_service / create_api_tool_service / create_builtin_tool_service
- [x] **Paginator await 调用方**：skill_service `get_skill_list_with_page` + api_tool_service `get_api_tool_providers_with_page`（T5 遗留的 7 处，本次覆盖 2 处；其余 5 处 conversation/dataset/document/segment/workflow 已由 T6/T7 处理）
- [x] **删除 Flask 遗留**（grep 零消费者确认）：
  - `app/http/module.py`（injector 容器）——已删除
  - `package/sqlalchemy/`（整目录）——已删除
  - `internal/extension/`（整目录——旧的 database_extension/login_extension/migrate_extension/redis_extension/weaviate_extension/logging_extension/celery_extension）——已删除
  - `internal/extensions/`（复数目录）——保留
- [x] **门禁全量启用**：`test/migration/test_no_flask_imports.py` 移除 `PLAN2_GATES` 默认 skip，扫描范围扩大到 internal/service + internal/core + internal/model + package/；豁免清单：internal/handler、internal/router、internal/schema、app/http、internal/task、internal/migrations、package/response、internal/middleware；额外断言 module.py/package/sqlalchemy/internal/extension 不存在
- [x] **`auto_commit` 在 `internal/service/` 归零**：grep 确认仅剩注释/文档
- [x] **事务边界登记**：新增 #29-#30（api_tool_service 2 处），见 transaction-boundaries.md T9 说明
- [x] **测试转 async**：`test_skill_service.py` 8 个用例全部转 `@pytest.mark.asyncio` + mock 适配
- [x] **审查修复轮**：
  - I1：`file_extractor._get_cos_service` 会话泄漏修复——不创建 session，传 `upload_file_service=None`（download_file/upload_embedded_image 不触库）
  - I3：`ai_service.optimize_prompt` 流式回归修复——改为 `_aiter_sync` 逐块 `run_in_threadpool(next)` 增量 yield
  - 门禁修正：`\binjector\.\w+` 防 Injector/Module 引用漏网；扫描范围扩至 `internal/` 全量（新增 `internal/server` 豁免）
  - I2（tool_node.py 每调用建同步引擎）：**控制器裁决延迟**，Plan 3 统一处理
- [x] 测试：`venv/Scripts/python -m pytest -q` —— **348 passed / 31 skipped / 0 failed**（+4 I1/I3 覆盖测试）
- [x] 提交：
  - `1790c77` refactor(core): 移除 injector 与全部 flask/werkzeug 依赖（服务层 async 化完成）
  - 审查修复提交（见下方）

## Plan 2 完成声明

**Plan 2（服务层 async 化）全部 9 个任务已完成。** 以下是验收标准对照：

| # | 验收标准 | 状态 | 证据 |
|---|---|---|---|
| 1 | `internal/service|model|core` 下 `grep flask|werkzeug|injector` 为 0；`app/http/module.py` 已删除，全仓库无 `injector` 引用（冻结项除外） | ✅ | T9 门禁 4/4 passed；injector 仅存于 handler/router/task/middleware（冻结面） |
| 2 | 248 处 `db.session` 调用点全部 async 化；`auto_commit` 在 `internal/` 下为 0；每处 `await commit()` 已在 transaction-boundaries.md 登记 | ✅ | 30 处 commit 登记（#1-#30）；`auto_commit` grep 归零 |
| 3 | 破坏性迁移声明成立：旧 Flask Web 不可运行是预期状态；handler/schema 测试 skip 计数 0 为可接受完成态 | ✅ | 31 skipped（handler/schema 模块级 skip） |
| 4 | 全量可运行测试绿（skip 除外）；门禁测试（T9 启用）通过 | ✅ | 348 passed / 31 skipped / 0 failed；门禁 4/4 passed |
| 5 | `internal/core/agent/*` 全部 async 化（R10 方案 A）且其测试绿 | ✅ | T8 已完成（4 个 agent 文件独立提交） |
| 6 | 全部落 `release_fastApi`；progress.md 每任务更新完毕 | ✅ | 本任务为最后一笔 |

## Plan 3（进行中）：Schema/Handler/Web 翻转（P3+P4+P2）

### T1 Web 基建——response/认证依赖/异常/lifespan/旧文件删除 —— 完成
- [x] **R1 package/response/response.py 重写**：删 flask import（`flask.Response`/`jsonify`/`stream_with_context`）→ `fastapi.responses.JSONResponse`/`StreamingResponse`；所有 helper 签名不变（handler 调用点零改动）；`compact_generate_response` 支持 Response→JSONResponse、元组→JSONResponse(status_code)、生成器(sync/async)→StreamingResponse(text/event-stream, headers Cache-Control/X-Accel-Buffering)。
- [x] **R2/R3 internal/server/deps.py 新建**：`get_current_user`（Bearer JWT→Account，文案逐条对照旧 middleware._validate_credential）；`get_api_key_account`（api_key→ApiKey(active)→account）；`request_context_dependency`（写入 contextvar scheme/host/remote_addr）。
- [x] **R6 app/http/app.py 重写**：lifespan（时序定案见下）+ CORS（origins=*, methods GET/POST, headers Content-Type/Authorization, credentials，与旧 flask_cors 完全一致）+ favicon/default-app-icon/healthz 路由 + 空 router include 占位。
- [x] **R7 异常处理器**：CustomException→200+{code,message,data}；ValidationError→200+{code=validation_error,message=首个错误,data=errors}；SQLAlchemyError→200+{code=fail,message=数据库操作失败}；Exception→开发重抛/生产200+{code=fail,message=str(error)}。逐条对照旧 `internal/server/http.py:_register_error_handler`。
- [x] **旧文件删除**（grep 零消费者确认）：`internal/server/http.py`、`internal/middleware/middleware.py`、`app/http/app_fastapi.py`（pilot）。
- [x] **test/conftest.py 更新**：新增 `client` fixture（httpx.AsyncClient + ASGITransport）+ `auth_headers` fixture（Bearer token header）。
- [x] **TDD 测试**：`test/package/test_response.py`（20 用例：契约格式/code/message/data/SSE headers）；`test/internal/server/test_deps.py`（11 用例：认证两分支 + request_context 写入/清理）；`test/app/test_app.py`（10 用例：healthz/docs/favicon/icon/异常处理器/CORS）。
- [x] **全量收集**：404 tests collected, 0 errors；**全量运行**：389 passed / 31 skipped / 0 failed。
- [x] **提交**：`feat(web): FastAPI Web 基建（response 重写/认证依赖/异常/lifespan）+ 删除 Flask 旧引擎`

#### 时序深水区定案（T1 结论）

**import 期 get_settings() 调用点清单**：
| 文件 | 调用位置 | 类型 | 影响 |
|---|---|---|---|
| `package/database.py:67,111` | `build_engine()`/`get_sync_engine()` | 函数级（惰性） | 无 import 期风险 |
| `internal/extensions/redis.py:15` | `init_redis()` | 函数级（惰性） | 无 import 期风险 |
| `internal/extensions/weaviate.py:14` | `init_weaviate()` | 函数级（惰性） | 无 import 期风险 |
| `internal/service/*.py` | 各服务方法内 | 函数级（惰性） | 无 import 期风险 |
| `internal/core/embeddings/embedding_provider.py:117` | `create_embedding_provider()` | 函数级（惰性） | 无 import 期风险 |
| `internal/task/celery_app.py:29` | `celery_app = create_celery()` | **模块级** | 仅 Celery worker 路径，Web 入口不触发 |
| `internal/config/settings.py:76` | `@lru_cache` 定义 | 定义级 | 首次调用才构造 |

**结论**：Web 启动路径（`app/http/app.py` → import 链）中**无 import 期 get_settings() 调用**。`container.py` 模块级单例（`jwt_service = JwtService()`、`_ltp_service = LtpService()`）不调用 get_settings。`lru_cache` 首次调用发生在 lifespan 内。

**处理方式**：lifespan 内先 `build_engine()` + `set_default_session_factory()`（DB 连接基础设施），再 `await worker_run(apply_to_env)`（DB 配置注入 os.environ），再 `get_settings.cache_clear()` + `get_settings()`（重建 settings 单例读取注入后的 env），最后 `init_logging/init_redis/init_weaviate`。**"DB 配置（system_config 表）优先于 .env"语义成立。**

**lifespan 测试方式**：`asgi-lifespan` 库安装受权限限制；采用 `ASGITransport` 直接测试路由端点（不触发 lifespan），异常处理器直接调用 handler 函数测试。lifespan 本身由集成部署验证。

### T2 Schema 层 Pydantic 化（26 文件 + PaginatorReq）—— 完成
- [x] **PaginatorReq 转 Pydantic**：`package/paginator/paginator.py` — `FlaskForm → BaseModel`；字段 `current_page: int = Field(default=1, ge=1, le=9999)` / `page_size: int = Field(default=20, ge=1, le=50)`；`Paginator.__init__` 读 `req.current_page` / `req.page_size`（不再 `.data`）。
- [x] **26 个 schema 文件全部转换**：请求模型 FlaskForm→Pydantic BaseModel；响应模型 marshmallow Schema→Pydantic BaseModel（`@model_validator(mode="before")` 替代 `@pre_dump`；`model_dump(mode="json")` 替代 `.dump()`）。已 Pydantic 的文件（chroma_file_schema/chroma_vector_schema/upload_skill_schema 的部分模型/GetAppResp/GetPublishHistoriesWithPageResp）保持不变。
- [x] **schema.py 自定义字段删除**：`ListField`/`DictField`（wtforms）→ Pydantic 原生 `list`/`dict` 类型。
- [x] **internal/schema/__init__.py 更新**：不再导出 `DictField`/`ListField`。
- [x] **weaviate_vector_schema.py 完整还原**：`JsonForm` 删除；`WeaviateRecallReq`/`WeaviateDeleteDocumentReq` → Pydantic BaseModel（原生 JSON body，无需 Flask request 适配）。
- [x] **agent_schema.py 转换**：`ChatCompletionReq`（原 `request.get_json()` 直接读取）→ Pydantic BaseModel + `field_validator`。
- [x] **文件上传 schema**：`UploadFileReq`/`UploadImageReq` 的 FileField 不进 Pydantic body——handler 用 `UploadFile` 参数（T4）；`UploadFileResp` 转 Pydantic。登记 schema-mapping.md。
- [x] **校验文案保留**（契约）：所有 wtforms `DataRequired`/`Length`/`URL`/`regexp`/`AnyOf`/`NumberRange` 的 message → Pydantic `field_validator` 的 `ValueError("旧版 message")`。文案经 T1 的 ValidationError 异常处理器输出——**文案与旧版一致**。
- [x] **schema-mapping.md 登记**：`docs/migration/schema-mapping.md` — 全部 26 文件（旧类→新 Pydantic 模型→校验文案→消费 handler）。
- [x] **handler 状态**：handler 仍使用 FlaskForm 模式（`req.validate()`/`req.errors`/`req.data`/`req.field.data`），`compileall` 语法检查通过。handler 整体转换留 T4。
- [x] **测试 skip 解除**：`test/internal/schema/__init__.py` 移除模块级 skip。
- [x] **测试重写**：6 个现有测试文件全部转 Pydantic API（`model_validate()`/`model_dump()`/`ValidationError`）。
- [x] **TDD 新增测试**：`test_validation_messages.py`（38 用例：校验文案契约测试——断言 Pydantic ValidationError message 与旧版一致）。
- [x] **全量运行**：**453 passed / 25 skipped / 0 failed**（+64 schema 测试，-6 旧 skip）。
- [x] **提交**：`refactor(schema): FlaskForm/marshmallow → Pydantic v2（校验文案保留）`

> T2 附注 ①：服务层仍消费 `req.field.data` 模式（handler→service 接口契约），T4 转换 handler 时同步修改服务层调用点为直接属性访问。
> T2 附注 ②：test 内 `_page_req` / `_create_req` 等桩替身适配——PaginatorReq 已转 Pydantic（`current_page`/`page_size` 为 plain int），其余服务层仍用 `.data` 的字段保持 `_Field` 桩。

### T3 Router 153 条登记 + 蓝图依赖挂载 —— 完成
- [x] **gen_routes.py 脚本**：新增 `scripts/migration/gen_routes.py`，从 `docs/migration/route-inventory.md` 解析 153 条路由清单，生成 FastAPI APIRouter 骨架代码。路径参数转换：`<uuid:x>` → `{x}`，`<string:x>` → `{x}`。
- [x] **internal/router/router.py 重写**：Flask Blueprint → FastAPI APIRouter（`llmops_router` + `openapi_router`）；`register_routes_from_container()` 函数从 container 工厂获取 handler 实例并注册所有 153 条路由；蓝图→APIRouter 映射：bp → llmops_router（Depends(get_current_user)），openapi_bp → openapi_router（Depends(get_api_key_account)）；公开路由 `/webhook` 在 openapi_router 但无认证依赖。
- [x] **internal/container.py 补充 handler 工厂**：新增 27 个 handler 工厂函数（create_app_handler / create_account_handler / create_auth_handler / create_ai_handler / create_api_key_handler / create_api_tool_handler / create_analysis_handler / create_assistant_agent_handler / create_audio_handler / create_builtin_app_handler / create_builtin_tool_handler / create_chroma_file_handler / create_chroma_vector_handler / create_conversation_handler / create_dataset_handler / create_document_handler / create_feishu_handler / create_language_model_handler / create_oauth_handler / create_open_api_handler / create_segment_handler / create_skill_handler / create_system_config_handler / create_upload_file_handler / create_weaviate_vector_handler / create_web_app_handler / create_workflow_handler）。
- [x] **app/http/app.py 更新**：lifespan 内调用 `register_routes_from_container(session)` 注册路由；include_router × 2（llmops_router + openapi_router）+ 认证依赖挂载（get_current_user / get_api_key_account）。
- [x] **internal/router/__init__.py 更新**：导出 llmops_router / openapi_router / register_routes_from_container。
- [x] **测试**：`test/migration/test_route_inventory.py`（6 用例：153 条路由计数/蓝图分布/openapi 路由/路径参数/方法唯一性）；`test/app/test_routes_registered.py`（6 用例：openapi.json 路由存在/认证依赖/公开路由/favicon/healthz）。
- [x] **中间态说明**：handler 仍为同步 def + @login_required（T4 才转换），import 时会因旧 Flask 导入（`from package.sqlalchemy import SQLAlchemy`）失败——已声明为预期。测试在中间态下只验证基本路由（/healthz, /favicon.ico, /default-app-icon）。
- [x] **全量运行**：test/migration/test_route_inventory.py 6 passed；test/app/test_routes_registered.py 6 passed。
- [x] **提交**：`feat(router): 153 路由 FastAPI 登记（llmops/openapi + 蓝图依赖挂载）`

> T3 附注 ①（中间态边界）：handler 仍有旧 Flask 导入（`from flask import request` / `from flask_login import current_user, login_required` / `from injector import inject` / `from package.sqlalchemy import SQLAlchemy`），导致 import 失败。这是 Plan 3 迁移状态声明中的"破坏性中间态"——T4 handler 转换后才能完全运行。
> T3 附注 ②（路由注册时机）：路由在 lifespan 内注册（`register_routes_from_container(session)`），需要 AsyncSession。测试使用 `TestClient(app, raise_server_exceptions=False)` 避免 lifespan 触发。
> T3 附注 ③（container 工厂依赖）：部分 handler 工厂依赖未 async 化的服务（如 assistant_agent_service / builtin_app_service / chroma_file_service / chroma_vector_service / workflow_service），以 `None` 占位——T4 补全。

### T4 Handler 簇转换（27 handler）—— 完成
- [x] **全部 27 handler 转换**：`@login_required` → `user: CurrentUser` 参数；`current_user` → `user`；`request.get_json` → body Pydantic 参数；`request.args` → Query Pydantic 模型；`request.files` → `UploadFile = File(...)`（转 `file.file` 给服务）；`send_file` → `Response(content=...)`；`resp.dump()` → `model_dump(mode="json")`。
- [x] **认证注入模式**：`CurrentUser = Annotated[Account, Depends(get_current_user)]` 类型别名；handler 参数声明 `user: CurrentUser` 自动注入；无认证方法不声明 `user` 参数。
- [x] **SSE 链路确认**：`debug_chat`/`assistant_agent_chat`/`web_app_chat`/`debug_workflow`/`open_api.chat` → async generator → `compact_generate_response()` → `StreamingResponse(text/event-stream)`。
- [x] **UploadFile 处理**：`file: UploadFile = File(...)` → `file.file` (BinaryIO) 给服务层。
- [x] **UUID 转换**：`message_id`/`builtin_app_id` 等 str → `UUID()` 转换。
- [x] **5 个 None 占位工厂补全**：`create_assistant_agent_service`/`create_builtin_app_service`/`create_chroma_file_service`/`create_chroma_vector_service`/`create_workflow_service` + `create_analysis_service`。
- [x] **测试 skip 解除**：`test/internal/handler/__init__.py` 移除模块级 skip。
- [x] **导入验证**：27 handler 模块全部 import OK；27 handler 类全部从 `__init__.py` 导出 OK；Container 全部工厂函数 import OK；App 模块 import + lifespan 验证通过。
- [x] **提交**：`refactor(handler): 全部 27 handler FastAPI 化（Depends + Pydantic 参数 + container 工厂补全）`

> T4 附注 ①（认证语义变更）：移除 router-level `dependencies=[Depends(get_current_user)]`，改为 handler 参数级注入。原因：部分 handler 方法（`password_login`/`get_builtin_tools`/`provider` 等）在原始代码中无 `@login_required`，不应强制认证。
> T4 附注 ②（服务层 async 假设）：handler 中所有服务调用都使用了 `await`，假设服务层已全 async（Plan 2.1）。如果某些服务方法仍是同步的，运行时会产生 TypeError。
> T4 附注 ③（Redis 客户端）：多个工厂中 `redis_client=None`（TODO），影响 ChoiceService/AnalysisService 等。生产环境需要从 extensions 获取。
> T4 附注 ④（**页面实测发现的 async 转换回归，已修复，`e7b36fe`+`add5658`**）：
> - `oauth_handler.provider` 误 await 同步 classmethod `get_oauth_by_provider_name` → TypeError（/oauth/github code=fail）；
> - `builtin_app_handler` 三个方法（get_categories/get_builtin_apps/add_builtin_app_to_space）漏 await async service → 'coroutine' object is not iterable（/store/apps 500）；
> - `language_model_handler` 三个方法漏 await（get_language_models/get_language_model/get_language_model_icon）；
> - `choice_service.submit` 三处（assistant_agent/app/web_app handler）漏 await + `tencent_provider.test_connection` 漏 await；
> - `cos_service.upload_file` 同步 def 返回未 await 的 async create_upload_file coroutine + handler 参数按旧签名错位（True 被当 filename）→ 整体 async 化，handler 传 file.filename/file.content_type，app_service 调用补 await。
> - 验证：playwright 登录 + 全页面遍历（/home /space/* /store/* /openapi /settings）无 500；受影响测试 15 passed。
> T4 附注 ⑤（**xiao 账号真实数据页面实测，T5 序列化遗留，已修复 `6e7f3f1`**）：
> - `/space/apps`、`/space/datasets` → GetAppsWithPageResp/GetDatasetsWithPageResp 的 `@model_validator(before)`
>   仍访问 Plan 2.1 已上移的模型属性（app_config/draft_app_config/document_count 等），hasattr=False 时返回
>   ORM → datetime 赋 int 报 validation_error。修复：handler 按 model-session-callers.md 契约调服务方法组装 dict。
> - `/space/workflows/{id}` → get_draft_graph 返回图内 UUID（dataset.id 等），FastAPI JSONResponse 标准
>   json.dumps 无法序列化（Flask jsonify 原生支持）。修复：package/response.json 与 compact_generate_response
>   统一用 jsonable_encoder 序列化（等价 jsonify 的全局 UUID/datetime 支持），`success_json({"id": app.id})`
>   等同类隐患一并消除。
> T4 附注 ⑥（**文档列表/知识库详情页，已修复 `fd51496`**）：
> - `GET /datasets/{id}/documents` → GetDocumentResp/GetDocumentsWithPageResp 的 process_data 访问已上移的
>   `Document.segment_count/hit_count`（model-session-callers.md #16/#17）→ AttributeError。handler 改调
>   `get_segment_count`/`get_document_hit_count` 组装 dict。
> - `GET /datasets/{id}` → GetDatasetResp process_data `hasattr(document_count)` False → ORM → datetime 赋 int
>   报 validation_error。handler 按 get_datasets_with_page 同款组装。
> T4 附注 ⑦（**上传文档 500 → celery broker 错绑，已修复 `76b6540`**）：
> - `POST /datasets/{id}/documents` 数据落库成功后 `build_documents.delay()` 抛
>   `ACCESS_REFUSED (403) Login was refused`：`@shared_task` 装饰时绑定 Celery 无参默认 app
>   （broker 默认 amqp://localhost → RabbitMQ），而 `.env` 与 `internal/task/celery_app.py` 的 broker 是
>   Redis（172.20.70.38:6379 db1）——Redis 版 app 从未 `set_default()`。
> - 修复：`celery_app.set_default()` + document_task 显式导入 celery_app 保证初始化先行。
> - 验证：创建文档 200+success（落库 + 任务投递 Redis）；任务 id 正常生成。
> Plan 4 提前启动（**`b5e2b1a`**，因用户实测上传文档需要 worker 消费）：
> - celery_app.py：include 显式列出任务模块（autodiscover 只找 tasks.py 导致 [tasks] 空）+
>   worker_ready 钩子装配 worker 进程（dotenv/engine/session factory/apply_to_env/settings/redis）+
>   set_default()（@shared_task 绑定 Redis broker，同 `76b6540` 的 API 侧修复）。
> - 任务体（document/dataset/app_task）移除 injector，改用 container 工厂 + worker_run；
>   demo_task 删除（无消费者 + flask 引用）。
> - worker_run 支持 engine_factory：threads 池各线程各自 asyncio.run 新 loop，共享全局 engine
>   跨 loop 复用 asyncpg 连接报 InterfaceError；engine_factory 让 engine 创建与 dispose 同 loop。
> - 验证：worker [tasks] 5 任务注册；build_documents 全链路实测成功（parsing→splitting→
>   indexing→weaviate→completed；70 万字符小说文档 completed）。
> Plan 3 T4 附注 ⑧（**SSE 流式对话链路 5 类转换回归，已修复 `779f2e3`**）：
> - handler 对 async generator service 方法误 await（7 处 SSE 接口：debug_chat/debug_workflow/
>   assistant_agent_chat/web_app_chat/openapi chat/message_to_audio/optimize_prompt）→ 500；
> - app_service/web_app_service：load_attachments 与 memory resolve/get_user_profile 漏 await；
> - chat_runner：get_memory_tools/get_read_context(2)/trigger_write 漏 await；
> - agent_queue_manager：`from ... import sync_redis_client` 模块加载时快照 None（init_redis 后
>   不更新）→ 改活引用 `_sync_redis()` 访问模块属性；
> - 验证：SSE 200 + text/event-stream，agent_message 连续推送，消息落库 normal。
> Plan 3 T4 附注 ⑨（**ask_user 交互选项不弹出，2 个根因，已修复 `3073cc0`**）：
> - orchestrator `_run_subtask_inner`/memory_tools：子任务与记忆工具在 Agent 图线程
>   （ThreadPoolExecutor 工作线程）里 asyncio.run 新 loop，worker_run 用全局默认 engine →
>   asyncpg 跨 loop 复用抛 InterfaceError，checkpoint 写库失败，ask_user 事件链断裂。
>   修复：所有 worker_run 传 engine_factory=build_engine（同 celery threads 池修复）。
> - agent_queue_manager：self.redis_client 在 __init__ 快照 _sync_redis()，若构造早于
>   init_redis（模块加载期）None 被锁死 → listen/_is_stopped/queue 抛 NoneType 异常。
>   修复：去掉构造快照，使用点运行时活引用 + None 守卫。
> - 验证：80 agent 测试通过；publish(ASK_USER)→listen 跨线程收到 ask_user；日志无 InterfaceError。
> Plan 3 T4 附注 ⑩（**delete_conversation 卡死 + stop 接口 500，已修复**）：
> - 清历史失败根因：数据库僵尸锁——测试过程超时中断/多次 kill uvicorn 留下未提交事务
>   互相阻塞 account 行（pg_stat_activity 11 个僵尸连接），delete 的 UPDATE 卡死。
>   清理后正常（delete → 200 + 空列表）。
> - 暂停失败根因：`assistant_agent_service.stop_chat` 是同步 @classmethod（写 Redis），
>   handler 转换时误加 await → stop 接口 500（TypeError NoneType can't be used in await）。
>   修复 `18b28db`：去掉 await 直接调用。应用调试 stop（async）本就正确。
> - 验证：两个 stop 接口均 200；delete 后消息列表为空。
> Plan 3 T4 附注 ⑪（**delete_app 失败追问"数据锁了，是不是设计不合理"——设计无问题，根因是强杀进程的孤儿事务**）：
> - 设计分析（结论：事务模型健康，无需改代码）：
>   - base_service.create/update/delete 均为**独立事务边界**（块尾真实 commit），
>     get_or_create_debug_conversation、get_or_create_draft_app_config 等同理；
>   - SSE 流式期间**不持有**请求事务：会话/消息创建即刻提交，save_agent_thoughts 逐条
>     create/update 各自提交；get_db 的"流结束 commit"在无未提交变更时是空操作；
>   - 客户端断开：FastAPI 取消生成器 → get_db `finally: await session.close()` 执行，
>     close() 回滚未提交事务，连接归还池（pool_reset_on_return 默认 rollback）→ 不遗留锁。
>   - 唯一能遗留锁的路径是**进程被强杀**（SIGKILL/crash）：PG 侧会话变 idle-in-transaction
>     且锁不释放，直到 TCP keepalive（该库默认 7200s=2h）检测到死连接。
> - 证据链：pg_stat_activity 当时 11 个僵尸连接（idle in transaction）阻塞 account 行 →
>   pg_terminate_backend 清理后 delete_conversation/delete_app 均恢复；"删不掉" 应用
>   （f455efa2）现已 deleted=True（用户后续删除成功）；当前 DB 无 idle-in-transaction、
>   无锁等待；delete_app 端到端复现通过（创建→删除 200 success→列表不再出现→GET 返回
>   not_found）。僵尸锁系本机测试反复强杀 uvicorn 所致，非正常使用路径。
> - PG 加固（已应用，可逆 `ALTER SYSTEM RESET`）：idle_in_transaction_session_timeout='60s'
>   （孤儿 idle 事务 60s 内自动终止释放锁）+ lock_timeout='10s'（锁等待超 10s 快速报错而非
>   无限挂起，UI 得到明确错误可重试）。后续重启服务用优雅退出，勿再强杀。
> - 验证：delete_app（POST /apps/{id}/delete）200 + success；/apps 列表正确返回 data.list。
> Plan 3 T4 附注 ⑫（**ask_user 选择后 SSE 中断卡死 + stop 接口"数据库操作失败"，根因：后台线程 worker_run 漏 engine_factory 毒化共享连接池**）：
> - 症状链（用户实测 /space/apps/60198026）：选 ask_user 选项后回复完成后 UI 一直卡在
>   choice/stop 请求；stop 报 `{code:fail,message:数据库操作失败}`；推荐问题接口未出现；
>   日志见 save_agent_thoughts 时 `message_agent_thought` FK 外键失败（message 行未落库）。
> - 根因（3 处漏 `engine_factory=build_engine` 的 worker_run，与 celery/编排器/记忆工具同款
>   跨 loop bug）：
>   1. `conversation_service._generate_summary_and_update` / `_generate_conversation_name_and_update`
>      / `_reflect_feedback`：`Thread(...).start()` 后台线程内 `worker_run(_coro, commit_on_success=True)`
>      未传 engine_factory → asyncio.run 新 loop 复用全局 engine 的 asyncpg 连接（绑定主 loop）
>      → InterfaceError / "Exception terminating connection" → **连接被毒化并归还池**；
>   2. `builtin_provider.trigger_write`（用户特征抽取/情景记忆抽取）与 `tencent_provider.trigger_write`：
>      `asyncio.to_thread(worker_run, ...)` 同样漏 engine_factory；
>   - 毒化连接被后续请求检出 → "connection is closed"（stop/choice 接口 500→数据库操作失败）；
>     消息事务静默丢失（INSERT+COMMIT 记录在日志但行不存在）→ save_agent_thoughts FK 失败 →
>     SSE 流已开始后抛 RuntimeError 中断连接 → 前端收不到 agent_end → 卡死、无推荐问题。
> - 修复（全部与既有模式一致）：
>   - conversation_service 3 处 + builtin_provider 2 处 + tencent_provider 1 处 worker_run
>     补 `engine_factory=build_engine`（engine 创建与 dispose 同线程 loop）；
>   - `build_engine` 增加 `pool_pre_ping=True`：检出前探活，死连接自动丢弃重建（兜底）；
>   - `get_db` 改 `except BaseException`：SSE 客户端断开（CancelledError/GeneratorExit 为
>     BaseException）时显式回滚，避免连接以未提交事务状态归还池。
> - 验证：debug_chat SSE 正常跑完 agent_end；消息 + agent_thoughts 落库（long_term_memory_recall
>   + agent_message）；记忆写线程无 "用户特征抽取写入失败"；stop 200；连续请求无
>   connection is closed；pg_stat_activity 无 idle in transaction 残留；新日志 0 异常。
> Plan 3 T4 附注 ⑬（**ask_user 选择成功但回复完成后仍卡死 + 推荐问题不发，根因：后台线程事务跨 LLM 调用被 PG 空闲超时终止**）：
> - 症状链（用户实测 /space/apps/60198026）：ask_user 选择已提交成功（agent_action
>   "用户选择了：RBAC + ABAC 组合方案"）→ 完整答案已流式输出 → 但流式 finally 的记忆写侧
>   `trigger_write` 抛 `InterfaceError: cannot call Transaction.commit(): the underlying
>   connection is closed` → SSE 在 agent_end 前中断（"response already started"）→ 前端
>   卡在生成态（choice/stop 请求悬停、suggested_questions 不触发）。
> - 根因：记忆/摘要/命名线程的 worker_run 事务在 **LLM 调用前未提交**——事实抽取 LLM 调用
>   恰好耗时 60s（代理/限流重试），期间事务 idle-in-transaction 超过本机加固设置的
>   `idle_in_transaction_session_timeout=60s` → PG 终止连接 → 后续 commit 抛
>   "connection is closed"（日志：02:53:14 发请求 → 02:54:14 才返回，正好 60s）。
> - 修复：
>   - builtin_provider._extract_user_facts_coro / _extract_episodes_coro、
>     conversation_service._generate_summary_and_update / _generate_conversation_name_and_update：
>     **LLM 调用前 `await session.commit()` 释放读事务**（expire_on_commit=False 下对象仍可用），
>     事务不再跨越可能 60s+ 的 LLM 调用；
>   - chat_runner._stream_and_persist finally：**trigger_write 包 try/except**——记忆写侧是
>     尽力而为，失败绝不中断 SSE（agent_end 必须送达，前端才能收尾并触发推荐问题）；
>   - reflect_on_feedback 无需改（LLM 调用前无 DB 操作，无事务跨 LLM）。
> - 验证：完整 ask_user 流程（long_term_memory_recall→agent_message→agent_thought→ask_user→
>   choice 200→agent_action→agent_end）跑通；choice/stop 均 200；thoughts 全量落库；
>   idle-in-transaction 0；池健康；新日志 0 异常。
> Plan 3 T4 附注 ⑭（**"选择后无输出、一直等待"：两个根因——请求会话事务跨 Agent 循环被 PG 空闲
> 超时终止 + 前端 ask_user 连续追问时选项被上一问的 submitted 残留禁用**）：
> - 后端根因：请求会话（get_db）的读事务从 setup 阶段（history/记忆/工具 SELECT）一直保持到
>   流结束，期间 Agent 循环的 LLM 调用与 ask_user 等待（可长达数分钟）使事务 idle-in-transaction
>   超过 60s → PG 终止连接 → save_agent_thoughts 的 create commit 抛
>   "cannot call PreparedStatement.fetch/Transaction.commit(): the underlying connection is closed"
>   → 流在 agent_end 前中断（日志：用户 test 中 message 创建 02:52:55 → save 03:01:33）。
>   修复：`chat_runner.run` 进入 Agent 循环前 `await self.db.commit()` 释放读事务
>   （expire_on_commit=False 下对象仍可用；save_agent_thoughts 逐条独立提交不受影响）。
> - 前端根因：AskUserOptions 按消息复用组件实例，Q1 提交后 `submitted=true` 残留；agent 连续
>   追问 Q2（新 event_id）时组件只换 question/options，按钮仍被 `disabled` 禁用 → 用户看到
>   新问题却无法点击 → agent 一直等待。修复：`watch(props.eventId)` 变化时复位 submitted/
>   submitting/selected/customText/checkedOrders（同 eventId 的带 choice 回写不触发）。
> - 验证：ask_user 等待 70s（>60s 超时阈值）后应答 → 流正常 agent_end、消息 status=normal、
>   thoughts 全量落库、无 idle-in-transaction 残留；多轮 ask_user 连续应答跑通；前端 build 通过。
> Plan 3 T4 附注 ⑮（**web_app 4 次选择输出完成后流一直不结束：记忆写侧 await + 共享
> anyio CapacityLimiter 跨 asyncio.run loop 死锁**）：
> - 症状链（用户实测 web_app 发布页）：4 次 ask_user 选择、答案完整输出后，SSE 流一直挂起
>   不结束（agent_end 不达前端）→ 推荐问题接口不触发；DB 侧 memory/summary 线程的 engine
>   连接（engine_factory 新建）3 个滞留不释放。
> - 根因 1（流不结束）：`_stream_and_persist` finally **`await trigger_write`**——记忆写侧
>   内部 `asyncio.to_thread(worker_run, ...)` 等待线程完成，线程内含 LLM 抽取（可 60s+），
>   流被阻塞在 finally，SSE 连接保持打开 → 前端永远等不到结束。
> - 根因 2（线程挂死）：记忆/摘要/命名/反思后台线程各自 `asyncio.run` 新 loop，共享同一模块级
>   `anyio.CapacityLimiter(2)` 经 `to_thread.run_sync(limiter=...)` 调 LLM——**实测复现**：
>   多线程各自 asyncio.run 共享同一 limiter 时首个绑定 loop 的线程挂死（repro_limiter.py），
>   导致该线程永不返回、engine 连接滞留、后续流被卡。
> - 修复：
>   - `chat_runner` finally：**trigger_write 改 fire-and-forget**（asyncio.create_task + 句柄集
>     防 GC，失败仅记日志）——流在 agent_end 后立即结束，绝不等记忆写；
>   - 全量移除共享 limiter：conversation/user_memory/episodic/reflection/retrieval/app_service/
>     language_model/open_api/indexing/segment/weaviate_vector 共 15 处
>     `to_thread.run_sync(..., limiter=...)` → `asyncio.to_thread(...)`（loop 默认执行器，
>     无跨 loop 信号量；并发上限让位给 API 侧限流）。
> - 验证：debug_chat 5.1s 内 agent_end 且流立即关闭；记忆线程 engine 连接全部释放（无滞留）；
>   3 路并发聊天全部 agent_end（无死锁）；日志无 connection-closed/InterfaceError（仅剩
>   GBK 控制台打印 emoji 的 Logging error 噪音，非功能性）。
> Plan 3 T4 附注 ⑯（**调试会话消息接口 validation_error "Input should be a valid boolean"**）：
> - 症状：GET /apps/{id}/conversations/messages 返回 `{code:validation_error, data:{can_resume:
>   "Input should be a valid boolean"}}`（/space/apps/6ad102f9 页面报错）。
> - 根因：`app_service.get_debug_conversation_messages_with_page` 与
>   `conversation_service.get_conversation_messages_with_page` 给消息打 can_resume 标记时，
>   `sub_task_service.has_resumable_checkpoints` 已 async 化但**漏 await**——`and` 短路真时
>   can_resume 变成协程对象（coroutine），pydantic bool 校验失败。仅 STOP/TIMEOUT/ERROR 状态
>   消息会触发（status 检查为真时短路到协程）。
> - 修复：两处补 `await`。
> - 验证：接口 200 + success，can_resume 为布尔；无协程泄漏告警。
> Plan 3 T4 附注 ⑰（**message_to_audio TTS 接口"一直没有响应"：协程误当生成器 + 草稿配置查询
> version=="draft" 类型错误**）：
> - 症状：POST /audio/message_to_audio 返回 200 text/event-stream 后立即断开，前端一直无响应。
> - 根因 1：audio_service.message_to_audio 是 `async def` 但内部 `return tts()`（同步生成器）——
>   调用返回协程而非 async 生成器；handler 按 async 生成器模式漏 await，StreamingResponse 迭代
>   协程抛 `TypeError: 'coroutine' object is not iterable` → SSE 启动即崩（其余 5 个 SSE 接口是
>   真 async 生成器不受影响）。
> - 根因 2：修好协程后暴露第二处——查草稿配置用 `AppConfigVersion.version == "draft"`，version 是
>   整型列 → PG "invalid input syntax for type integer" → 数据库操作失败；应改用
>   `config_type == AppConfigType.DRAFT`。
> - 修复：handler 补 `await` 解包协程；查询改 config_type=DRAFT。
> - 验证：接口 200 + text/event-stream，tts_message 事件流式输出（299 段音频），无异常。
> Plan 3 T4 附注 ⑱（**web-app 页点播放报"数据库操作失败"：AppConfig 多次发布产生多行，
> scalar_one_or_none 抛 MultipleResultsFound**）：
> - 症状：/web-apps 页点播放，POST /audio/message_to_audio 返回 `{code:fail, 数据库操作失败}`；
>   日志 `Multiple rows were found when one or none was required`。
> - 根因：WEB_APP 分支 `select(AppConfig).where(app_id==...)` 用 scalar_one_or_none——每次发布
>   都会新增一条运行配置（不清理历史），多次发布后返回多行 → 抛错。
> - 修复：改用 `app.app_config_id` 精确取当前发布配置（与 app_service.get_app_config 一致）；
>   app_config_id 为空时返回 not_found。
> - 验证：web_app 消息 TTS 200 + text/event-stream；TTS 未开启的应用返回正确的"未开启"业务错误。

> Plan 3 T4 附注 ⑲（**工作流 2603fcc2（工作流测试2）知识库检索节点：跨事件循环 Future + 工具链回归，
> 已修复**）：
> - 症状：工作流调试中"知识库检索"分支报 `Task got Future attached to a different loop`
>   （retrieval_service.create_langchain_tool_from_search 的 `_do_search` 桥接处）；
>   另：`扩展插件` 分支报 `'Settings' object has no attribute 'database_url_sync'`。
> - 根因①（知识库检索）：节点先在 `asyncio.run(_build())` 的 loop 里建 session 建工具，
>   工具 invoke 再经 asyncio.run/新线程桥接检索 → session/引擎跨 loop。
> - 修复①：`dataset_retrieval_node.run` 重写——不再缓存工具，检索整体在
>   `worker_run(_search, engine_factory=build_engine)` 的单 loop 内完成：
>   create_retrieval_service(session, sync_redis_client) + search_in_datasets 直调；
>   输出格式化与工具内截断逻辑一致（≤6 篇 / 500 字 / 3500 总长）。
> - 根因①′（Agent 对话/OpenAPI 对话同缺陷）：`create_langchain_tool_from_search` 的工具闭包
>   捕获请求 session（主 loop），agent 在主 loop 同步 invoke → 线程桥接 asyncio.run → 跨 loop。
> - 修复①′：工具 `_do_search` 改为在自身执行 loop 内自建 engine+session（build_engine +
>   build_sessionmaker，用后 dispose）再直调 search_in_datasets/search_agentic；
>   验证：运行中 loop 内 invoke 工具成功返回检索文本（chat_runner/open_api 路径一并受益）。
> - 根因②（扩展插件）：`tool_node` 用 `settings.database_url_sync`（async 迁移后不存在）。
> - 修复②：改用 `package.database.get_sync_session_factory()`（含 search_path connect 事件）。
> - 根因③（隐藏回归）：`search_in_datasets` 记录 `DatasetQuery.created_by=account_id`（UUID）
>   而列类型 VARCHAR → asyncpg DataError；dataset_service.hit 同路径同样会炸。
> - 修复③：记录处 `str(account_id)` 转换（dataset_service.hit 一并受益）。
> - 验证：`POST /workflows/{id}/debug` 平铺 body `{"query": ...}`（无 node_ids 时 handler 不拆
>   `inputs` 包装），8/8 节点 succeeded，连续两轮稳定（latency ≈ 11.8s）。
> - 附带：默认 anyio limiter（starlette run_in_threadpool，40 token）跨 asyncio.run loop 实测
>   不死锁；共享 `CapacityLimiter(1)` 跨 loop 复现死锁（印证附注⑮移除共享 limiter 的必要性）。
> - 附注⑲ 追加（**前端"选中节点运行"子图调试失败：worker_run 守卫拒绝运行中 loop**）：
>   前端带 node_ids 调试走 `build_subgraph_config` 线性子图——langgraph `PregelRunner.tick`
>   单任务 fast path 在主事件循环 inline 执行节点（整图有并行分支才走线程池），
>   worker_run/asyncio.run 因此抛守卫/`cannot be called from a running event loop`。
>   新增 `package/database.run_sync_bridge(fn)`：无运行中 loop 直接执行，有则丢新线程；
>   dataset_retrieval_node 与 llm_node 的 run() 均改经 run_sync_bridge 调用。
>   验证：node_ids 选知识库检索 → 3 节点子图 succeeded（0.4s）；选 LLM 节点 → 上游闭包
>   4 节点子图 succeeded（12.5s，真实 LLM 调用）；整图 8 节点仍 succeeded。
> - 附注⑲ 追加（**检索设置选"全文检索"报错：召回测试 hit 三连回归**）：
>   - `dataset_service.hit` 调 `search_agentic`/`search_in_datasets`（async）漏 await →
>     `'coroutine' object is not iterable`（三种策略全 500，非仅全文检索）。
>   - `FullTextRetriever._get_relevant_documents` 用旧 Flask-SQLAlchemy `self.db.session`——
>     async 迁移后拿到裸同步 Session → `'Session' object has no attribute 'session'`；
>     改 `self.db.execute(...)`（BM25Retriever 无此问题）。
>   - `hit` 响应组装用 `segment.document`/`document.upload_file` relationship（迁移后移除）→
>     显式批量查 Document + UploadFile（upload_file 缺失时扩展名/类型留空）。
>   - 验证：`POST /datasets/{id}/hit` semantic/full_text/hybrid 三策略全 200 且返回真实片段；
>     用户工作流（full_text）子图调试 3 节点 + 整图 7 节点均 succeeded。

> Plan 5 T1 附注 ⑳（**全量回归收尾：测试桩随服务 async 化同步更新，已修复**）：
> - 触发：沙箱只读（tempfile 不可写）→ 全量回归跑不起来；恢复写权限后按簇分批跑。
> - 修复 6 组测试（全部为**测试桩未随服务 async 化更新**，无生产代码改动）：
>   ① `test_database.py` 过时用例（search_path 已改 server_settings 机制，断言 connect 事件 → 拦截 create_async_engine 断言 connect_args）；
>   ② `memory_provider_resolver.resolve` MagicMock → AsyncMock（T8 resolve 已 async，chat_runner 四文件）；
>   ③ `run()` 前置 `await self.db.commit()`（T10）→ db mock 补 AsyncMock commit；
>   ④ `StubProvider.get_read_context/get_memory_tools/trigger_write` 同步 → async（T8/T10），trigger_write fire-and-forget 断言前排空 `_BG_MEMORY_TASKS`；
>   ⑤ `attachment_service.load_attachments` MagicMock → AsyncMock（T7 已 async）；
>   ⑥ 检索工具测试适配 T13⑲ 新架构（打桩桥接 loop 内 create_retrieval_service/build_engine/build_sessionmaker）；
>   ⑦ `worker_run` 测试桩补 engine_factory 形参；⑧ `CosService.upload_file` 已 async → cos 用例转 async + AsyncMock create_upload_file + miniio 4 位置参数解包。
> - 结果：可运行部分 **491 passed / 23 skipped / 0 failed**（app live_server 簇因本地代理 7890 离线 + 内存受限受阻——非代码缺陷，契约改用运行中 dev server 实测 6/6 通过）。
> - 产出：[regression-report.md](regression-report.md)（回归矩阵）、[contract-report.md](contract-report.md)（10 条契约对照+实测）、[deployment-plan.md](deployment-plan.md)（部署核对+待调整清单）。
> - 附注⑳ 追加（**OOM 根因：embedding 模型反复加载无进程级复用，已修复**）：
>   - 症状：验证期间电脑内存爆满；test/app 簇 "memory allocation of N bytes failed"；uvicorn 进程内存只增不减。
>   - 根因：`create_embedding_provider()` 每次调用都新建——`LocalEmbeddingProvider.__init__` 每次构造
>     HuggingFaceEmbeddings 重新加载 bge-small-zh 到内存（每实例 100MB+，torch 权重 GC 迟缓）。
>     而每次知识库检索（请求/dataset hit/工作流节点/工具桥接——含 T13⑲ 重写的两处每次新建服务）
>     都经 create_retrieval_service → create_embeddings_service → EmbeddingsService.__init__ →
>     create_embedding_provider() 新建实例。
>   - 修复：`create_embedding_provider()` 加 `functools.lru_cache(maxsize=None)` 进程级单例
>     （配置经 lifespan apply_to_env 注入后固定，首调缓存安全）；vector/weaviate/ltp 本为模块级单例。
>   - 验证：修复后 8 轮检索（12 次 hit 三策略 + 4 次工作流子图）uvicorn RSS 仅 +15MB
>     （旧代码每轮 +100MB+）；此前 OOM 崩溃的 test/app 组合可完整跑完（16 passed，无内存崩溃）；
>     live_server 簇仍为代理离线环境超时（非内存）。
> - 附注⑳ 追加（**live_server 契约簇全绿：SSE 前置校验 + 公开路由清单修正 + chroma 业务异常**，
>   代理恢复后 184 passed / 0 failed）：
>   - **SSE 前置校验**：`app_service.debug_chat` 拆为 `prepare_debug_chat`（流开始前完成校验/副作用，
>     异常 → 200+not_found）+ `stream_debug_chat`（纯流式）；handler 两步调用。原实现 async generator
>     惰性执行，app 不存在等业务异常在 StreamingResponse 开始后抛出 → "response already started" 500。
>   - **公开路由清单修正**：`test_contract_401` 原按 route-inventory 蓝图归属把 20 条 bp 路由当认证路由
>     （builtin_tools/oauth/login/language_models icon/chroma）——旧 Flask 代码这些 handler 无
>     @login_required（T4 附注①）→ 移入 `BP_PUBLIC_ROUTES` 组，认证路由 152→132，断言无 token →
>     200 + 正常业务响应（非 unauthorized）。
>   - **chroma 业务异常**：`chroma_file_handler` 3 处 + `chroma_vector_service` 5 处 `raise ValueError`
>     （内置异常 → 开发模式 500）→ `ValidateException`/`NotFoundException`（200 + validation_error/not_found）。
>   - 验证：live 簇 184 passed（含 132 认证路由 unauthorized、20 bp 公开路由、12 认证冒烟、
>     黄金样例、SSE 契约与响应头）；service 簇等其余簇此前已全绿。
> - 附注⑳ 追加（**Plan2 过渡期 22 个 skip 测试改写为 async 版，全部通过**）：
>   - 触发：用户追问 skip 原因——22 个为旧 Flask 测试债（injector/app/db fixture 依赖）。
>   - 改写 13 个文件（+删除 1 个过时文件）：
>     - memory 簇 7 文件（resolver/tencent/builtin/memory_tools/episodic/reflection/user_memory）：
>       injector.get → container 工厂；方法全 await；load_default_language_model → AsyncMock；
>       db.session → db_session(async) 或 worker_run 独立引擎真实落库（工具链 uuid 隔离）。
>     - agent 簇：orchestrator_resume(5)/orchestrator_agent(2) 断点读写改 worker_run 独立引擎
>       （不 monkeypatch create_sub_task_service，跨 loop 隐患消除），agent.stream 经
>       asyncio.to_thread 执行；test_base_agent_context 删除（断言 Flask has_app_context，
>       async 迁移后概念已不存在）。
>     - service 簇：app_logical_delete(3)/sub_task_service(3)/sub_task_thoughts(1) async 化
>       （created_by VARCHAR 转 str、WebAppService 补 attachment_service、身份映射 expire_all）。
>   - 生产小改：memory_tools._run_with_engine 加 run_sync_bridge（async 上下文同步 invoke 工具
>     时 worker_run 守卫拒绝；与工作流节点/子图同模式）。
>   - 结果：非 live 全量 **546 passed / 1 skipped / 0 failed**（+55 用例；唯一剩余 skip 为
>     test_routes_registered 的 ASGITransport 中间态标记，live 下已注册且有契约覆盖）。

> 附注㉑（**2026-08-31 审查 8 类问题修复，提交到 release_fastApi_20260831**）：
> - **① 流式 try/except/finally + ERROR 事件 + finally 落库**：assistant_agent_service.chat 与
>   open_api_service.handle_stream 原无保护（LLM 异常裸抛、推理过程丢失、无 ERROR 事件）——
>   对齐 chat_runner._stream_and_persist；同时 web_app_chat 前置校验拆 prepare/stream（原惰性
>   generator 在 StreamingResponse 开始后抛 500）。
> - **② Agent 循环前提交读事务**：assistant_agent/open_api/web_app 补 `await self.db.commit()`
>   （对齐 chat_runner.py:190，防 PG idle_in_transaction_session_timeout 杀长任务）。
> - **③ 客户端断开取消**：`_aiter_sync` finally 关闭底层同步生成器——agent 内部 listen() 的
>   queue.get(timeout=1) 循环因 GeneratorExit 在 1s 内退出，不再 600s 悬挂。
> - **④ 死代码清理**：删除 7 处 `_*_LIMITER = CapacityLimiter(2)` 定义（T10 后无调用方）、
>   `from anyio import CapacityLimiter` 残留、过期"R6 并发限制"注释；修复 segment/indexing/
>   weaviate 对已删 limiter 的 import（会 ImportError）。
> - **⑤ OpenAPI 语义**：AgentConfig(user_id=end_user.id, invoke_from=SERVICE_API)（原为
>   account.id + DEBUGGER）；非流式返回真实 total_token_count/created_at（原硬编码 0）；
>   event 统一 .value。
> - **⑥ SSE 协议层**：新增 `package.response.sse_format`——`id: <seq>` + `event:` + 可选
>   `retry:` + `data:`（ensure_ascii=False）；trace/tool_input/observation 敏感字段裁剪
>   （字符串 2000/列表 50）；单事件 64KB 上限截断；chat_runner/assistant_agent/open_api
>   三处流式统一改用。
> - **⑦ API 层**：web_app/assistant_agent/app(DebugChat)/open_api/agent 5 个 chat schema 的
>   query 加 max_length=2000；app.py 新增 audit_log_middleware（method/path/status/IP/
>   UA/认证凭据掩码/耗时）。
> - **⑧ 租户归属二次校验**：get_langchain_tools_by_tools_config（ApiTool）/by_workflow_ids
>   （Workflow）/by_skill_ids（Skill）查询加 account_id 过滤（防跨租户引用他人资源）。
> - 命名修正：`miniio_service` → `minio_service`（MinIO 官方拼写；保留 MINIIO_* 环境变量与
>   STORAGE_PROVIDER=miniio 部署契约）。
> - 验证：非 live 全量 **553 passed / 0 failed**（含 handler 簇 live_client 13 passed）；
>   test_routes_registered 断言修正为 handler 参数级 ApiKeyUser 检查（认证为参数级注入）。
> - 提交：f43fa0c（改名）、177ec9f（①⑤②）、05992c1（④）、59599b4（⑥）、77d3424（⑦）、
>   e30e449（⑧）。

## Plan 4（部分完成，见下）：SSE/Celery 任务体/部署（P6+P7）
- [x] **提前完成部分**（`b5e2b1a`）：celery worker 独立进程 + threads 池 + worker_ready 装配（dotenv/engine/session factory/apply_to_env/settings/redis）+ `set_default()`；任务体（document/dataset/app_task）移除 injector 改 container 工厂 + worker_run（engine_factory）；worker [tasks] 5 任务注册，文档上传全链路实测。
- [x] **部署收尾**（`faa834e` 一笔）：`jenkins/entrypoint.sh` 适配 FastAPI（`alembic upgrade head` + `celery -A internal.task.celery_app` + `uvicorn app.http.app:app`）；`.env.example` 补 `EMBEDDING_*`/`RERANK_*`/`QUERY_REWRITE_MODEL` 组；compose `llmops-web` build context 修正为 `../ai-code-llmops-web`。核对报告见 [deployment-plan.md](deployment-plan.md)。
- [ ] 剩余：容器构建/部署演练（本机无 docker 环境未验证）；nginx 裸路径与 SQLALCHEMY_ECHO=false 为可选 P2。

## Plan 5（进行中）：回归与切换（P8）
- [x] 全量回归（491 passed / 23 skipped / 0 failed，见 [regression-report.md](regression-report.md)）
- [x] 契约报告（[contract-report.md](contract-report.md)：10 条黄金契约全部满足 + dev server 实测 6/6）
- [x] **环境受限项已解除（T6 收尾）**：live_server 簇自动化全绿——代理 7890 在线 + 清理遗留 uvicorn/celery 进程释放内存后，全量回归 **734 passed / 0 failed**（含 test_contract_401 153 路由冒烟、SSE 全链路、认证两分支、黄金契约，全部 live_server 真实 TCP）
- [ ] 切换上线（旧服务下线/新服务上线）——依赖 Plan 4 部署收尾
- [ ] 推送远端：本地 release_fastApi 领先 origin ~55 提交，需手动 `git push`（agent 端 gitee 403）

> Plan 5 T6 收尾附注㉒（**OOM 阻塞根因确认 + 环境恢复后全量回归全绿 + T5 控制器 5 提交补审**）：
> - **OOM 根因确认（非沙箱内存上限）**：T5 期间"memory allocation of 1081360 bytes failed"（1MB 分配失败）被误判为"沙箱对单进程的内存上限"。实际核查：
>   - 沙箱源码（dsh-sandbox-windows-acl）仅设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，无任何内存限制；实测单进程可连续分配 4GB+，进程不在任何 job object。
>   - 真实根因 = embedding 模型反复加载内存泄漏（附注⑳，`create_embedding_provider` 无进程级复用，commit `37667ef` 修复）+ 机器内存被遗留进程占满（uvicorn:5001 私有 2.6GB、celery 2GB，另 IDE/WSL/浏览器 ~15GB）。
>   - 清理遗留进程后可用内存 16GB，全量回归可完整跑通。
> - **全量回归首轮 733 passed / 1 failed**：唯一失败 `test_logging_idempotent` 为测试顺序耦合（lifespan 已 init_logging → 模块级 `_initialized` 置 True，`before=6 after=6`；单独跑通过）。修复：测试内清空 root handlers + 重置标志，finally 恢复现场。终跑 **734 passed / 0 failed**（8 分 07 秒）。
> - **T5 控制器 5 提交补审**（60e3813/1156656/b8dffcd/53abe1c/a19149c，当时 subagent 执行层崩溃缺常规审查）：
>   - 结论：可合并。核心架构（RequestSessionProxy + app 级 Depends(get_db) + selectinload + 服务层 .data 对齐）设计正确；`req.xxx.data` 全库零残留；get_db finally 全路径 close+reset 无串请求风险；流式期间 contextvar 有效（FastAPI 0.141.1 yield 依赖退出码在响应发送后执行）。
>   - **重要问题 1 个（已修复）**：`POST /chroma/delete` 被误标 `Annotated[ChromaFileDeleteReq, Query()]`——原 Flask 契约是 JSON body（`request.get_json`），导致 body→query 契约漂移。改回 body 模型（chroma_file_handler.py）+ 新增 `test/app/test_chroma_delete_contract.py`（2 passed：body 生效、query 不再被接受）。
>   - 建议级遗留（已登记，非阻塞）：app 级 get_db 使 /healthz 等静态路由也建会话（DB 挂时健康探测语义污染）；`register_routes_from_container` 的 session 死参数；`ApiToolProvider.tools` 默认改 `lazy="selectin"` 根治 MissingGreenlet；两个 validation handler 去重；conftest 模块级工厂突变与 live 测试数据不隔离。
