# Schema Mapping: FlaskForm/marshmallow → Pydantic v2

> T2 产出物。T4 handler 转换参照。
> 生成时间: 2026-08-28 (Plan 3 T2)

## Legend

- **请求模型**: FlaskForm → Pydantic BaseModel
- **响应模型**: marshmallow Schema → Pydantic BaseModel (model_validate / model_dump)
- **校验文案**: wtforms message → Pydantic Field(description=...) 或 model_validator message
- **文件上传**: FileField → handler 侧 UploadFile 参数（T4）

---

## 1. package/paginator/paginator.py

| 旧类 | 新类 | 字段 | 校验文案 | 消费 handler |
|---|---|---|---|---|
| `PaginatorReq(FlaskForm)` | `PaginatorReq(BaseModel)` | `current_page: int = 1` (ge=1, le=9999) / `page_size: int = 20` (ge=1, le=50) | "每页数据的条数范围在1-9999" / "每页数据的条数范围在1-50" | 继承于所有分页请求模型 |

---

## 2. internal/schema/schema.py

| 旧类 | 新类 | 说明 |
|---|---|---|
| `ListField(wtforms.Field)` | **删除** — Pydantic 用 `list[...]` 原生类型 | |
| `DictField(wtforms.Field)` | **删除** — Pydantic 用 `dict` 原生类型 | |

---

## 3. internal/schema/__init__.py

| 变更 | 说明 |
|---|---|
| 移除 `DictField, ListField` 导出 | Pydantic 不需要自定义字段 |

---

## 4. internal/schema/account_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `GetCurrentUserResp(Schema)` | `GetCurrentUserResp(BaseModel)` | id/name/email/avatar/last_login_at/last_login_ip/created_at; `@model_validator(mode="before")` for timestamps | account_handler |
| `UpdatePasswordReq(FlaskForm)` | `UpdatePasswordReq(BaseModel)` | password: str (pattern=密码最少包含一个字母，一个数字，并且长度为8-16) | account_handler |
| `UpdateNameReq(FlaskForm)` | `UpdateNameReq(BaseModel)` | name: str (min_length=1, max_length=25, msg="用户名称长度在1-25个字符") | account_handler |
| `UpdateAvatarReq(FlaskForm)` | `UpdateAvatarReq(BaseModel)` | avatar: str (AnyHttpUrl, msg="用户头像必须是uri地址") | account_handler |

---

## 5. internal/schema/auth_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `PasswordLoginReq(FlaskForm)` | `PasswordLoginReq(BaseModel)` | email: str (min=5, max=25); password: str (pattern) | auth_handler |
| `PasswordLoginResp(Schema)` | `PasswordLoginResp(BaseModel)` | access_token: str; expire_at: int | auth_handler |

---

## 6. internal/schema/ai_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `GenerateSuggestedQuestionsReq(FlaskForm)` | `GenerateSuggestedQuestionsReq(BaseModel)` | message_id: UUID (msg="消息id格式必须为uuid") | ai_handler |
| `OptimizePromptReq(FlaskForm)` | `OptimizePromptReq(BaseModel)` | prompt: str (min=1, max=2000, msg="预设prompt不能为空"/"预设prompt的长度不能超过2000个") | ai_handler |

---

## 7. internal/schema/api_key_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `CreateApiKeyReq(FlaskForm)` | `CreateApiKeyReq(BaseModel)` | is_active: bool = False; remark: str = "" (max=100) | api_key_handler |
| `UpdateApiKeyReq(FlaskForm)` | `UpdateApiKeyReq(BaseModel)` | is_active: bool = False; remark: str = "" (max=100) | api_key_handler |
| `UpdateApiKeyIsActiveReq(FlaskForm)` | `UpdateApiKeyIsActiveReq(BaseModel)` | is_active: bool = False | api_key_handler |
| `GetApiKeysWithPageResp(Schema)` | `GetApiKeysWithPageResp(BaseModel)` | id/api_key/is_active/remark/updated_at/created_at + `@model_validator(mode="before")` | api_key_handler |

---

## 8. internal/schema/api_tool_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `ValidateOpenAPISchemaReq(FlaskForm)` | `ValidateOpenAPISchemaReq(BaseModel)` | openapi_schema: str | api_tool_handler |
| `DebugApiToolReq(JsonForm)` | `DebugApiToolReq(BaseModel)` | arguments: dict = {} | api_tool_handler |
| `GetApiToolProvidersWithPageReq(PaginatorReq)` | `GetApiToolProvidersWithPageReq(PaginatorReq)` | search_word: str = "" | api_tool_handler |
| `CreateApiToolReq(FlaskForm)` | `CreateApiToolReq(BaseModel)` | name/icon/openapi_schema/headers: list[dict] | api_tool_handler |
| `UpdateApiToolProviderReq(FlaskForm)` | `UpdateApiToolProviderReq(BaseModel)` | name/icon/openapi_schema/headers | api_tool_handler |
| `GetApiToolProviderResp(Schema)` | `GetApiToolProviderResp(BaseModel)` | + `@model_validator(mode="before")` | api_tool_handler |
| `GetApiToolResp(Schema)` | `GetApiToolResp(BaseModel)` | + `@model_validator(mode="before")` | api_tool_handler |
| `GetApiToolProvidersWithPageResp(Schema)` | `GetApiToolProvidersWithPageResp(BaseModel)` | + `@model_validator(mode="before")` | api_tool_handler |

---

## 9. internal/schema/app_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `CreateAppReq(FlaskForm)` | `CreateAppReq(BaseModel)` | name(icon/description/app_type) | app_handler |
| `UpdateAppReq(FlaskForm)` | `UpdateAppReq(BaseModel)` | name/icon/description | app_handler |
| `GetAppsWithPageReq(PaginatorReq)` | `GetAppsWithPageReq(PaginatorReq)` | search_word: str = "" | app_handler |
| `GetAppsWithPageResp(Schema)` | `GetAppsWithPageResp(BaseModel)` | + `@model_validator(mode="before")` | app_handler |
| `GetAppResp(BaseModel)` | **保持不变** | 已经是 Pydantic | app_handler |
| `GetPublishHistoriesWithPageReq(PaginatorReq)` | **保持不变** | 已继承 PaginatorReq（需改 Pydantic） | app_handler |
| `GetPublishHistoriesWithPageResp(BaseModel)` | **保持不变** | 已经是 Pydantic | app_handler |
| `FallbackHistoryToDraftReq(FlaskForm)` | `FallbackHistoryToDraftReq(BaseModel)` | app_config_version_id: str (UUID format) | app_handler |
| `UpdateDebugConversationSummaryReq(FlaskForm)` | `UpdateDebugConversationSummaryReq(BaseModel)` | summary: str = "" | app_handler |
| `DebugChatReq(FlaskForm)` | `DebugChatReq(BaseModel)` | image_urls/file_ids/query/resume | app_handler |
| `GetDebugConversationMessagesWithPageReq(PaginatorReq)` | (需改 Pydantic PaginatorReq) | created_at: int = 0 (ge=0) | app_handler |
| `GetDebugConversationMessagesWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator(mode="before")` | app_handler |

---

## 10. internal/schema/assistant_agent_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `AssistantAgentChat(FlaskForm)` | `AssistantAgentChat(BaseModel)` | image_urls/file_ids/query | assistant_agent_handler |
| `GetAssistantAgentMessagesWithPageReq(PaginatorReq)` | (需改 Pydantic) | created_at: int = 0 (ge=0) | assistant_agent_handler |
| `GetAssistantAgentMessagesWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator(mode="before")` | assistant_agent_handler |

---

## 11. internal/schema/audio_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `AudioToTextReq(FlaskForm)` | `AudioToTextReq(BaseModel)` | ossUrl: str | audio_handler |
| `MessageToAudioReq(FlaskForm)` | `MessageToAudioReq(BaseModel)` | message_id: UUID | audio_handler |

---

## 12. internal/schema/builtin_app_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `GetBuiltinAppCategoriesResp(Schema)` | `...(BaseModel)` | + `@model_validator(mode="before")` | builtin_app_handler |
| `GetBuiltinAppsResp(Schema)` | `...(BaseModel)` | + `@model_validator(mode="before")` | builtin_app_handler |
| `AddBuiltinAppToSpaceReq(FlaskForm)` | `AddBuiltinAppToSpaceReq(BaseModel)` | builtin_app_id: UUID | builtin_app_handler |

---

## 13. internal/schema/choice_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `ChoiceReq(FlaskForm)` | `ChoiceReq(BaseModel)` | choice/skip/action/keep_orders/custom/event_id + model_validator | app_handler, assistant_agent_handler, web_app_handler |

---

## 14. internal/schema/conversation_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `GetConversationMessagesWithPageReq(PaginatorReq)` | (需改 Pydantic) | created_at: int = 0 (ge=0) | conversation_handler |
| `GetConversationMessagesWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator(mode="before")` | conversation_handler |
| `UpdateConversationNameReq(FlaskForm)` | `...(BaseModel)` | name: str (min=1, max=100) | conversation_handler |
| `UpdateConversationIsPinnedReq(FlaskForm)` | `...(BaseModel)` | is_pinned: bool = False | conversation_handler |
| `UpdateMessageFeedbackReq(FlaskForm)` | `...(BaseModel)` | feedback: str = "" (enum: like/dislike/"") | conversation_handler |

---

## 15. internal/schema/dataset_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `CreateOrUpdateDatasetReq(FlaskForm)` | `...(BaseModel)` | name/icon/description | dataset_handler |
| `GetDatasetResp(Schema)` | `...(BaseModel)` | + `@model_validator` | dataset_handler |
| `GetDatasetsWithPageReq(PaginatorReq)` | (需改 Pydantic) | search_word: str = "" | dataset_handler |
| `GetDatasetsWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator` | dataset_handler |
| `HitReq(FlaskForm)` | `HitReq(BaseModel)` | query/retrieval_strategy/k/score/agentic_enable/max_rounds | dataset_handler |
| `GetDatasetQueriesResp(Schema)` | `...(BaseModel)` | + `@model_validator` | dataset_handler |

---

## 16. internal/schema/document_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `CreateDocumentsReq(FlaskForm)` | `...(BaseModel)` | upload_file_ids/process_type/rule + complex validation | document_handler |
| `CreateDocumentsResp(Schema)` | `...(BaseModel)` | + `@model_validator` | document_handler |
| `GetDocumentResp(Schema)` | `...(BaseModel)` | + `@model_validator` | document_handler |
| `UpdateDocumentNameReq(FlaskForm)` | `...(BaseModel)` | name: str (min=1, max=100) | document_handler |
| `GetDocumentsWithPageReq(PaginatorReq)` | (需改 Pydantic) | search_word: str = "" | document_handler |
| `GetDocumentsWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator` | document_handler |
| `UpdateDocumentEnableReq(FlaskForm)` | `...(BaseModel)` | enabled: bool | document_handler |

---

## 17. internal/schema/oauth_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `AuthorizeReq(FlaskForm)` | `...(BaseModel)` | code: str | oauth_handler |
| `AuthorizeResp(Schema)` | `...(BaseModel)` | access_token/expire_at | oauth_handler |

---

## 18. internal/schema/open_api_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `OpenAIChatReq(FlaskForm)` | `...(BaseModel)` | app_id/end_user_id/conversation_id/query/image_urls/stream | open_api_handler |

---

## 19. internal/schema/segment_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `GetSegmentsWithPageReq(PaginatorReq)` | (需改 Pydantic) | search_word: str = "" | segment_handler |
| `GetSegmentsWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator` | segment_handler |
| `GetSegmentResp(Schema)` | `...(BaseModel)` | + `@model_validator` | segment_handler |
| `UpdateSegmentEnabledReq(FlaskForm)` | `...(BaseModel)` | enabled: bool | segment_handler |
| `CreateSegmentReq(FlaskForm)` | `...(BaseModel)` | content/keywords | segment_handler |

---

## 20. internal/schema/update_file_schema.py

| 旧类 | 新类 | 说明 | 消费 handler |
|---|---|---|---|
| `UploadFileReq(FlaskForm)` | **删除**（文件字段不进 Pydantic body） | handler 用 `file: UploadFile = File(...)` | upload_file_handler |
| `UploadFileResp(Schema)` | `UploadFileResp(BaseModel)` | + `@model_validator` | upload_file_handler |
| `UploadImageReq(FlaskForm)` | **删除**（同上） | handler 用 `file: UploadFile = File(...)` | upload_file_handler |

---

## 21. internal/schema/upload_skill_schema.py

| 旧类 | 新类 | 说明 |
|---|---|---|
| `UploadSkillSchema(BaseModel)` | **保持不变** | 已是 Pydantic |
| `SkillResp(BaseModel)` | **保持不变** | 已是 Pydantic |
| `GetSkillListWithPageReq(PaginatorReq)` | 需改 Pydantic PaginatorReq 继承 | search_word: str = "" |

---

## 22. internal/schema/user_memory_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `TestMemoryConfigReq(FlaskForm)` | `...(BaseModel)` | app_id/team_id/agent_id/user_id (all optional) | app_handler |
| `GetUserMemoryFactsAtReq(FlaskForm)` | `...(BaseModel)` | at: int (ge=0) | app_handler |
| `GetUserMemoryFactsWindowReq(FlaskForm)` | `...(BaseModel)` | start/end: int (ge=0) | app_handler |
| `UserMemoryFactResp(Schema)` | `...(BaseModel)` | + `@model_validator` (status computed) | app_handler |
| `EpisodicMemoryResp(Schema)` | `...(BaseModel)` | + `@model_validator` | app_handler |
| `ProceduralMemoryResp(Schema)` | `...(BaseModel)` | + `@model_validator` | app_handler |

---

## 23. internal/schema/web_app_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `AppConfigSchema(Schema)` | `AppConfigSchema(BaseModel)` | opening_statement/opening_questions/suggested_after_answer | web_app_handler |
| `GetWebAppResp(Schema)` | `...(BaseModel)` | + `@model_validator` | web_app_handler |
| `WebAppChatReq(FlaskForm)` | `...(BaseModel)` | conversation_id/query/image_urls/file_ids/resume | web_app_handler |
| `GetConversationsReq(FlaskForm)` | `...(BaseModel)` | is_pinned: bool = False | web_app_handler |
| `GetConversationsResp(Schema)` | `...(BaseModel)` | + `@model_validator` | web_app_handler |

---

## 24. internal/schema/workflow_schema.py

| 旧类 | 新类 | 字段 & 校验 | 消费 handler |
|---|---|---|---|
| `CreateWorkflowReq(FlaskForm)` | `...(BaseModel)` | name/tool_call_name/icon/description | workflow_handler |
| `UpdateWorkflowReq(FlaskForm)` | `...(BaseModel)` | name/tool_call_name/icon/description | workflow_handler |
| `GetWorkflowResp(Schema)` | `...(BaseModel)` | + `@model_validator` | workflow_handler |
| `GetWorkflowsWithPageReq(PaginatorReq)` | (需改 Pydantic) | status/search_word | workflow_handler |
| `GetWorkflowsWithPageResp(Schema)` | `...(BaseModel)` | + `@model_validator` | workflow_handler |

---

## 25. internal/schema/weaviate_vector_schema.py

| 旧类 | 新类 | 说明 | 消费 handler |
|---|---|---|---|
| `JsonForm(FlaskForm)` | **删除** — Pydantic 原生 JSON body | | |
| `WeaviateRecallReq(JsonForm)` | `WeaviateRecallReq(BaseModel)` | dataset_id/document_id/query/top_k/score_threshold | weaviate_vector_handler |
| `WeaviateDeleteDocumentReq(JsonForm)` | `WeaviateDeleteDocumentReq(BaseModel)` | dataset_id: UUID | weaviate_vector_handler |

---

## 26. internal/schema/agent_schema.py

| 旧类 | 新类 | 说明 | 消费 handler |
|---|---|---|---|
| `ChatCompletionReq` (plain class, uses request.get_json) | `ChatCompletionReq(BaseModel)` | query/user_id/history | agent handler (open_api) |

---

## 27. internal/schema/chroma_file_schema.py

| 旧类 | 新类 | 说明 |
|---|---|---|
| `FileItemSchema(BaseModel)` | **保持不变** | 已是 Pydantic |
| `FileListResp(BaseModel)` | **保持不变** | 已是 Pydantic |

---

## 28. internal/schema/chroma_vector_schema.py

| 旧类 | 新类 | 说明 |
|---|---|---|
| `ListVectorsReq(BaseModel)` | **保持不变** | 已是 Pydantic |
| `AddVectorReq(BaseModel)` | **保持不变** | 已是 Pydantic |
| `UpdateVectorReq(BaseModel)` | **保持不变** | 已是 Pydantic |
| `RecallTestReq(BaseModel)` | **保持不变** | 已是 Pydantic |
