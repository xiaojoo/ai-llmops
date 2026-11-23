# 模型属性查库上移登记（model-session-callers.md）

Plan 2.1 R7：模型内查库的 `@property`（async ORM 下 lazy loading → MissingGreenlet，属性不能 await）
**全部上移为服务方法**。本表登记 原属性 → 新服务方法 的映射——**这是 Plan 3 handler 停止访问
这些属性的契约**；本文件级门禁 `test/internal/model/test_model_no_session_gate.py` 断言
`internal/model/` 无 `db.session`/`db.auto_commit`/`current_app`/`UserMixin`/flask/werkzeug。

## 映射表（T2 全部登记）

> 服务方法签名统一为 `async def get_x(self, <model>, db: AsyncSession)`：服务类本体仍在各簇任务
> async 化（`self.db` 尚为同步 SQLAlchemy），故新方法**显式注入 `db: AsyncSession`**；簇任务转换
> 完成后并入 `self.db`（移除该参数）。纯计算属性（无 DB）保留为属性（见下"保留属性"）。

| # | 模型 | 原属性 | 新服务方法（含签名） | 服务类 async 化任务 |
|---|---|---|---|---|
| 1 | `Account` | `assistant_agent_conversation`（查库 + 会话缺失时创建 + auto_commit + current_app.config） | `AccountService.get_assistant_agent_conversation(account, db, assistant_agent_id=None) -> Conversation`（R3：`ASSISTANT_AGENT_ID` → `settings.assistant_agent_id`） | T4 |
| 2 | `ApiKey` | `account` | `ApiKeyService.get_account(api_key, db) -> Account \| None` | T4 |
| 3 | `Conversation` | `is_new`（消息计数 ≤1） | `ConversationService.is_conversation_new(conversation, db) -> bool` | T6 |
| 4 | `Message` | `conversation` | `ConversationService.get_message_conversation(message, db) -> Conversation \| None` | T6 |
| 5 | `App` | `app_config` | `AppService.get_app_config(app, db) -> AppConfig \| None` | T5 |
| 6 | `App` | `draft_app_config`（查库 + 缺失时创建默认草稿 + commit） | `AppService.get_or_create_draft_app_config(app, db) -> AppConfigVersion` | T5 |
| 7 | `App` | `debug_conversation`（只读查询） | `AppService.get_debug_conversation(app, db) -> Conversation \| None` | T5 |
| 8 | `App` | `token_with_default`（按状态清空/生成 token + commit） | `AppService.get_token_with_default(app, db) -> str` | T5 |
| 9 | `AppConfig` | `app_dataset_joins` | `AppService.get_app_dataset_joins(app_config, db) -> list[AppDatasetJoin]` | T5 |
| 10 | `Dataset` | `document_count` | `DatasetService.get_document_count(dataset, db) -> int` | T7 |
| 11 | `Dataset` | `hit_count` | `DatasetService.get_hit_count(dataset, db) -> int` | T7 |
| 12 | `Dataset` | `character_count` | `DatasetService.get_character_count(dataset, db) -> int` | T7 |
| 13 | `Dataset` | `related_app_count` | `DatasetService.get_related_app_count(dataset, db) -> int` | T7 |
| 14 | `Document` | `upload_file` | `DocumentService.get_upload_file(document, db) -> UploadFile \| None` | T7 |
| 15 | `Document` | `process_rule` | `DocumentService.get_process_rule(document, db) -> ProcessRule \| None` | T7 |
| 16 | `Document` | `segment_count` | `DocumentService.get_segment_count(document, db) -> int` | T7 |
| 17 | `Document` | `hit_count` | `DocumentService.get_document_hit_count(document, db) -> int` | T7 |
| 18 | `Segment` | `document` | `SegmentService.get_document(segment, db) -> Document \| None` | T7 |

## 保留的属性（纯计算，无 DB，不迁移）

| 模型 | 属性 | 说明 |
|---|---|---|
| `Account` | `is_password_set` | `bool(self.password)`，无 DB 访问 |

## 仍引用已删除属性的调用方（簇任务/Plan 3 处理，T2 不转换）

> 服务层现有同步调用方会在对应簇任务（T4-T8）async 化时切换到上表新方法；handler/schema 冻结至
> Plan 3（Plan 3 handler 按本表契约改用服务方法，schema 的 `to_dict` 类方法同步改写）。

**服务层（簇任务转换时切新方法）：**
- `internal/service/assistant_agent_service.py:61,201` — `account.assistant_agent_conversation` → T5 切 `AccountService.get_assistant_agent_conversation`（或经 session）
- `internal/service/app_service.py:237,303,317,381,526` — `app.draft_app_config` → T5 切 `AppService.get_or_create_draft_app_config`；`:669` — `app.token_with_default` → T5 切 `AppService.get_token_with_default`
- `internal/service/app_config_service.py:58` — `app.draft_app_config`；`:103` — `app.app_config`；`:119` — `app_config.app_dataset_joins` → T5
- `internal/service/audio_service.py:80` — `message.conversation`（→T6/T9）；`:98,103` — `app.draft_app_config`/`app.app_config`（→T5/T9）
- `internal/service/conversation_service.py:326` — `conversation.is_new` → T6 切 `ConversationService.is_conversation_new`
- `internal/service/dataset_service.py:182` — `document.upload_file` → T7 切 `DocumentService.get_upload_file`
- `internal/service/document_service.py:470` — `document.upload_file` → T7
- `internal/service/indexing_service.py:267,269,305` — `document.upload_file`/`document.process_rule` → T7

**schema 层（冻结，Plan 3 处理）：**
- `internal/schema/dataset_schema.py:56-59,91-93` — `data.document_count/hit_count/related_app_count/character_count`
- `internal/schema/document_schema.py:211-213,266-267` — `data.segment_count/character_count/hit_count`
- `internal/schema/app_schema.py:84` — `data.app_config`/`data.draft_app_config`
- `internal/schema/segment_schema.py:62-64,112-114` — `data.character_count/hit_count`（Segment 自有列，非上移属性，仅列引用）

## 语义保持注记

- `App.token_with_default` 保留旧代码 `self.token is not None or self.token != ""` 判定写法（不修正，语义保持）。
- `App.debug_conversation` 旧属性内"会话不存在则创建"分支已注释（早已失效），上移方法保持只读语义。
- 原 `with db.auto_commit():` 块（#1/#6）与显式 `db.session.commit()`（#8 两处）→ 独立事务边界，
  已在 [transaction-boundaries.md](transaction-boundaries.md) 登记。
