# 事务边界登记（transaction-boundaries.md）

Plan 2.1 硬规则 1：**`await self.db.commit()` 出现的位置 = 已声明的事务边界**。
T2 起每处 commit 必须在此登记（文件 + 行 + 理由），审查时逐处核对，禁止新增无登记 commit。

事务模型三分类（详见计划「事务模型」）：

| 类型 | 生命周期 | commit 归属 |
|---|---|---|
| Request Transaction | FastAPI 请求（Plan 3）→ `get_db()` yield 的 AsyncSession | 兜底：get_db 成功时 `await session.commit()`；失败 rollback |
| Independent Transaction | 原 `auto_commit` 块范围 | 块尾 `await self.db.commit()`（真实提交，位置与旧代码一致） |
| Worker Transaction | 后台线程/Celery → `worker_run(coro_factory, commit_on_success=True)` | 默认成功后 commit；异常 rollback |

## 登记表（T2 起逐处填写）

| # | 文件 | 行 | commit 类型 | 理由 | 任务 |
|---|---|---|---|---|---|
| 1 | `internal/service/base_service.py` | create 块尾 `await self.db.commit()` | Independent | 与旧 `auto_commit` 块尾提交语义一致：add 后立即提交，保证 DB 生成主键回填、立即持久化与请求→后台可见性；异常回滚由外层（get_db/worker_run）兜底 | T1 |
| 2 | `internal/service/base_service.py` | update 块尾 `await self.db.commit()` | Independent | 同 #1：setattr 落库后立即提交（未知字段抛 FailedException 时不执行 commit，由外层回滚） | T1 |
| 3 | `internal/service/base_service.py` | delete 块尾 `await self.db.commit()` | Independent | 同 #1：`await db.delete()` 后立即提交，删除即刻生效 | T1 |
| 4 | `internal/service/account_service.py` | `get_assistant_agent_conversation` 块尾 `await self.db.commit()` | Independent | 原 `Account.assistant_agent_conversation` 属性内 `with db.auto_commit():` 块（add+flush 后提交）：会话 id 落库 + 账号 `assistant_agent_conversation_id` 回填立即可见 | T2（T4 并入 self.db） |
| 5 | `internal/service/app_service.py` | `get_or_create_draft_app_config` 块尾 `await self.db.commit()`（T5 后约 L148） | Independent | 原 `App.draft_app_config` 属性内 `db.session.add(...); db.session.commit()`：默认草稿创建即持久化 | T2（T5 并入 self.db + scalar_one_or_none） |
| 6 | `internal/service/app_service.py` | `get_token_with_default` 内第一处 `await self.db.commit()`（T5 后约 L181） | Independent | 原 `App.token_with_default` 属性内非发布状态清空 token 后的 commit | T2（T5 并入 self.db） |
| 7 | `internal/service/app_service.py` | `get_token_with_default` 内第二处 `await self.db.commit()`（T5 后约 L186） | Independent | 原 `App.token_with_default` 属性内发布状态生成 token 后的 commit | T2（T5 并入 self.db） |
| 8 | `internal/service/app_service.py` | `auto_create_app` 块尾 `await self.db.commit()`（L270） | Independent | 原 `with db.auto_commit():` 块（add+flush 后提交）：AI 生成的应用+草稿创建即持久化 | T5 |
| 9 | `internal/service/app_service.py` | `create_app` 块尾 `await self.db.commit()`（L298） | Independent | 原 auto_commit 块：应用+默认草稿创建即持久化 | T5 |
| 10 | `internal/service/app_service.py` | `copy_app` 块尾 `await self.db.commit()`（L365） | Independent | 原 auto_commit 块：拷贝应用+草稿创建即持久化 | T5 |
| 11 | `internal/service/app_service.py` | `publish_draft_app_config` 删除 AppDatasetJoin 后 `await self.db.commit()`（L462） | Independent | 原 auto_commit 块：发布时清空旧知识库关联，提交保证请求→后台可见性 | T5 |
| 12 | `internal/service/app_service.py` | `cancel_publish_app_config` 删除 AppDatasetJoin 后 `await self.db.commit()`（L516） | Independent | 原 auto_commit 块：取消发布清空知识库关联 | T5 |
| 13 | `internal/service/app_service.py` | `get_or_create_debug_conversation` 块尾 `await self.db.commit()`（L773） | Independent | 原 auto_commit 块：调试会话创建即持久化（按账号隔离） | T5 |
| 14 | `internal/service/app_config_service.py` | `_query_draft_app_config` 创建默认草稿后 `await self.db.commit()`（L76） | Independent | 原 `App.draft_app_config` 属性 add+commit 语义（本服务无 AppService 依赖，内联实现）：默认草稿创建即持久化 | T5 |
| 15 | `internal/service/app_config_service.py` | `get_app_config` 逐条删除 AppDatasetJoin 后 `await self.db.commit()`（L159，for 循环内） | Independent | 原 `for dataset_id in missing: with auto_commit(): delete(...)`——每缺失 dataset 一个块，语义保持逐条提交 | T5 |
| 16 | `internal/service/builtin_app_service.py` | `add_builtin_app_to_space` 块尾 `await self.db.commit()`（L65） | Independent | 原 auto_commit 块：内置应用+草稿创建即持久化 | T5 |
| 17 | `internal/service/assistant_agent_service.py` | `_get_or_create_assistant_agent_conversation` 块尾 `await self.db.commit()`（L220） | Independent | 原 `Account.assistant_agent_conversation` 属性 auto_commit 块语义：会话创建+账号回填即持久化 | T5 |

## T8 说明（工作流/记忆/Agent 簇 async 化，新增登记 #27-#28）

| # | 文件 | 位置/方法 | commit 类型 | 理由 | 任务 |
|---|---|---|---|---|---|
| 27 | `internal/service/sub_task_service.py` | `save_checkpoint` upsert 后 `await self.db.commit()` | Independent | 原 `with self.db.auto_commit():` 块——断点保存/更新即持久化 | T8 |
| 28 | `internal/service/sub_task_service.py` | `clear_checkpoints` 批量删除后 `await self.db.commit()` | Independent | 原 `with self.db.auto_commit():` 块——断点清理即持久化 | T8 |

### 其余服务无新增 commit 边界

- `workflow_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `user_memory_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `episodic_memory_service.py`：Postgres 写入经 BaseService，无直接 commit。
- `procedural_memory_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `reflection_service.py`：全部写操作经 procedural_memory_service（BaseService），无直接 commit。
- `memory_provider/*`（builtin/tencent/base/resolver/tencent_client）：无 session 依赖或委托子服务。
- `agent_queue_manager.py`：Redis 操作（同步客户端），无 DB commit。
- `base_agent.py` / `orchestrator_agent.py` / `react_agent.py` / `function_call_agent.py`：无直接 DB 操作。
- `workflow.py` / `dataset_retrieval_node.py` / `llm_node.py` / `browser.py` / `memory_tools.py`：无 session 依赖或委托子服务。

> 行号随代码变动漂移：commit 出现的位置即边界（硬规则 1），T2 起逐处核对。
> BaseService 是 35 个服务 / ~170 调用点的基础（无人覆写），恢复块尾 commit 为计划明确要求
> （Global Constraints + R2 + 事务模型；推回记录明确拒绝"Service 禁止 commit + 统一 get_db 提交"）。

## T1 说明（已登记 3 个独立事务边界，见上表）

- `internal/service/base_service.py` 原 `with self.db.auto_commit():` 三个块（create/delete/update）
  按 R1/R2 async 化：**块尾保留真实 `await self.db.commit()`**（独立事务边界，位置与旧代码一致，已登记 #1-#3）。
- `package/database.py` 的 `_run_worker` 内 `await session.commit()`（commit_on_success=True 时）与
  `await session.rollback()` 为 **Worker Transaction 兜底**（计划 R5 原文实现），不属于服务层显式边界，不逐处登记。
- `package/database.py` 的 `get_db` 内 commit/rollback 为 **Request Transaction 兜底**（Plan 1 已有），不登记。

## T2 说明（已登记 4 个独立事务边界，见上表 #4-#7）

- T2（模型层迁移）把模型内查库属性上移为服务方法（登记 model-session-callers.md）；其中
  3 个方法携带原属性内的写操作，按事务模型转为独立事务边界：
  - #4 `AccountService.get_assistant_agent_conversation`（原 `Account.assistant_agent_conversation` 的 auto_commit 块）；
  - #5 `AppService.get_or_create_draft_app_config`（原 `App.draft_app_config` 的 add+commit）；
  - #6/#7 `AppService.get_token_with_default` 两处 commit（原 `App.token_with_default` 的清空/生成提交）。
- 位置与旧代码一致（块尾/原 commit 处），语义保持；异常回滚由外层（get_db/worker_run）兜底。

## T4 说明（认证/账号簇 async 化，无新增 commit 边界）

- 本簇 5 个服务（account/api_key/jwt/oauth/system_config）转换后**未新增任何 `await self.db.commit()` 位置**：
  - `api_key_service` / `oauth_service` / `system_config_service` 的全部写操作（create/update/delete）
    经 `BaseService` 执行——边界即 #1-#3（独立事务，块尾 commit 语义保持）；
  - `account_service` 仅保留 #4（`get_assistant_agent_conversation`，T2 已登记；T4 由显式 db 参数
    并入 `self.db`，commit 位置/语义不变）；
  - `password_login` / `oauth_login` / `save_configs` 内的写操作各自经 BaseService 提交（独立事务），
    不产生新的服务级显式 commit。
- `jwt_service` 无 db 依赖，无事务边界。

## T5 说明（App 簇 async 化，新增登记 #8-#17）

- app_service 5 个 auto_commit 块（#8 auto_create_app / #9 create_app / #10 copy_app / #11 publish 删除关联 /
  #12 cancel 删除关联 / #13 get_or_create_debug_conversation）按 R2 转为块尾 `await self.db.commit()`
  （位置与旧代码一致，语义保持——异常回滚由外层 get_db/worker_run 兜底）。
- app_config_service：#14 `_query_draft_app_config`（原 `App.draft_app_config` 属性 add+commit，本服务内联）；
  #15 `get_app_config` 的删除循环（原每缺失 dataset 一个 auto_commit 块 → 逐条提交）。
- builtin_app_service：#16 `add_builtin_app_to_space`（原 auto_commit 块）。
- assistant_agent_service：#17 `_get_or_create_assistant_agent_conversation`（原 `Account.assistant_agent_conversation`
  属性 auto_commit 块语义，本服务内联；AccountService 侧已有 #4 同一语义）。
- 其余写操作（update/create/delete）经 BaseService 执行，边界即 #1-#3，不产生新的服务级显式 commit。
- 本簇无 Request/Worker Transaction 兜底之外的 commit；`package/paginator` 为只读分页，无 commit。

## T6 说明（会话/对话簇 async 化，无新增 commit 边界）

- 本簇 8 个文件（conversation_service / chat_runner / choice_service / open_api_service /
  web_app_service / analysis_service + 两份 token_buffer_memory）转换后**未新增任何
  `await self.db.commit()` 位置**（grep 复核，见下）：
  - `conversation_service`：compact_if_needed 的归档/摘要更新、save_agent_thoughts 的
    MessageAgentThought/Message 写入、delete_conversation/delete_message 的软删，全部经
    `BaseService.create/update/delete`（独立事务边界 #1-#3）；本服务无直接 commit。
  - `chat_runner` / `open_api_service` / `web_app_service`：写操作（会话/消息/终端用户创建、
    推理过程落库）经 BaseService；chat 链自身只读 + 流式产出。
  - `choice_service`：Redis 写（AgentQueueManager.submit_choice），无 DB 事务。
  - `analysis_service` / `token_buffer_memory`（两份）：只读查询，无 commit。
- 后台线程语义：conversation_service 的 `_generate_summary_and_update` /
  `_generate_conversation_name_and_update` / `_trigger_reflection` 由原 `flask_app.app_context()`
  块改为 **R5 `worker_run(coro_factory, commit_on_success=True)`**——Worker Transaction 兜底
  （成功后 commit / 异常 rollback，`package/database.py` 内实现，非服务层显式边界，不逐处登记）。
- grep 复核：`internal/service/{conversation_service,chat_runner,choice_service,open_api_service,web_app_service,analysis_service}.py`
  与 `internal/{memory,core/memory}/token_buffer_memory.py` 内 `commit(` / `auto_commit` 均为 0。

## T7 说明（知识库簇 async 化，新增登记 #18-#26）

### indexing_service.py（6 处独立事务边界，原 auto_commit 块逐块登记）

| # | 文件 | 位置/方法 | commit 类型 | 理由 | 任务 |
|---|---|---|---|---|---|
| 18 | `indexing_service.py` | `update_document_enabled` 循环内 segment 错误状态更新后 commit | Independent | 原 `with self.db.auto_commit():` 块——weaviate 更新失败时记录 segment 错误状态并立即提交 | T7 |
| 19 | `indexing_service.py` | `delete_document` segment 批量删除后 commit | Independent | 原 `with self.db.auto_commit():` 块——删除文档关联 segment 记录并立即提交 | T7 |
| 20 | `indexing_service.py` | `delete_dataset` 多表批量删除后 commit | Independent | 原 `with self.db.auto_commit():` 块——删除知识库关联的 Document/Segment/DatasetQuery/KeywordTable 记录并立即提交 | T7 |
| 21 | `indexing_service.py` | `_update_segment_fields` 更新 segment 字段后 commit | Independent | 原 `with self.db.auto_commit():` 块——层级化索引更新 segment summary/content_type/parent_segment_id 字段并立即提交 | T7 |
| 22 | `indexing_service.py` | `_indexing` 循环内 segment 关键词/状态更新后 commit | Independent | 原 `with self.db.auto_commit():` 块——逐片段更新关键词+状态为 INDEXING 并立即提交 | T7 |
| 23 | `indexing_service.py` | `_completed` segment 状态批量更新为 COMPLETED 后 commit | Independent | 原 `with self.db.auto_commit():` 块——向量库写入成功后统一更新 segment 状态并立即提交 | T7 |
| 24 | `indexing_service.py` | `_completed` 异常回滚 segment 状态更新为 ERROR 后 commit | Independent | 原 `with self.db.auto_commit():` 块——向量库写入失败时回滚 segment 状态为 ERROR 并立即提交 | T7 |

### retrieval_service.py（1 处独立事务边界）

| # | 文件 | 位置/方法 | commit 类型 | 理由 | 任务 |
|---|---|---|---|---|---|
| 25 | `retrieval_service.py` | `search_in_datasets` segment hit_count 批量更新后 commit | Independent | 原 `with self.db.auto_commit():` 块——检索命中后批量更新片段命中次数并立即提交 | T7 |

### dataset_service.py（1 处独立事务边界）

| # | 文件 | 位置/方法 | commit 类型 | 理由 | 任务 |
|---|---|---|---|---|---|
| 26 | `dataset_service.py` | `delete_dataset` AppDatasetJoin 删除后 commit | Independent | 原 `with self.db.auto_commit():` 块——删除知识库关联的应用-知识库关联记录并立即提交 | T7 |

### 其余服务无新增 commit 边界

- `document_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `segment_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `keyword_table_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `upload_file_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `attachment_service.py`：只读查询，无 commit。
- `weaviate_vector_service.py`：weaviate 调用经 run_in_threadpool 桥接，无 DB commit。
- `vector_database_service.py`：weaviate 属性/方法，无 DB commit。
- `embeddings_service.py`、`ltp_service.py`、`process_rule_service.py`：无 session 依赖，无事务。
- `cos_service.py`、`miniio_service.py`、`chroma_service.py`、`chroma_file_service.py`、`chroma_vector_service.py`：无 session 依赖或只读查询，无事务。

> T7 grep 复核：`internal/service/{dataset_service,document_service,indexing_service,segment_service,retrieval_service,keyword_table_service,upload_file_service,attachment_service,weaviate_vector_service,vector_database_service}.py`
  内 `auto_commit` 已归零（全部转为显式 commit）。`process_rule_service/embeddings_service/ltp_service/cos_service/miniio_service/chroma_service/chroma_file_service/chroma_vector_service` 无 session/commit。

## T9 说明（剩余服务 async 化，新增登记 #29-#30）

| # | 文件 | 位置/方法 | commit 类型 | 理由 | 任务 |
|---|---|---|---|---|---|
| 29 | `api_tool_service.py` | `update_api_tool_provider` 删除旧工具后 `await self.db.commit()` | Independent | 原 `with self.db.auto_commit():` 块——删除旧工具后立即提交，再创建新工具覆盖更新 | T9 |
| 30 | `api_tool_service.py` | `delete_api_tool_provider` 删除工具+提供者后 `await self.db.commit()` | Independent | 原 `with self.db.auto_commit():` 块——删除工具提供者及关联工具后立即提交 | T9 |

### 其余服务无新增 commit 边界

- `audio_service.py`：只读查询（message/app_config），无直接 commit。
- `skill_service.py`：全部写操作经 BaseService（#1-#3 独立事务），无直接 commit。
- `feishu_service.py`：无 DB 依赖，无事务。
- `ai_service.py`：只读查询 + 委托 conversation_service，无直接 commit。
- `builtin_tool_service.py`：无 session 依赖，无事务。
- `attachment_service.py`（T7 已 async）：只读查询，无 commit。

### 全量 auto_commit 归零确认

T9 完成后 `internal/service/` 下 `auto_commit` 引用归零（grep 确认仅剩注释/文档）。

## 全量门禁最终豁免清单

| 豁免目录 | 原因 | 处理计划 |
|---|---|---|
| `internal/handler/*` | 冻结，同步调用 async 服务（预期破坏性迁移状态） | Plan 3 重写 |
| `internal/router/*` | 冻结，Flask 路由注册 | Plan 3 重写 |
| `internal/schema/*` | 冻结，FlaskForm 继承 | Plan 3 换 Pydantic |
| `app/http/*` | 冻结，旧 Flask Web 应用 | Plan 4 处理 |
| `internal/task/*` | 冻结，Celery 任务体仍用 injector | Plan 4 重写 |
| `internal/migrations/*` | Alembic 迁移脚本，不改 | 不改 |
| `package/response/*` | 冻结，jsonify/stream_with_context | Plan 3 重写 |
| `internal/middleware/*` | 冻结，旧 Web 中间件 | Plan 4 重写 |
