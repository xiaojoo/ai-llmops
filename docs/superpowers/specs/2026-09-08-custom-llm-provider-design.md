# 自定义 API 模型（Custom LLM Provider）设计

- 日期：2026-09-08
- 状态：已批准（方案 A）
- 范围：设置页新增「自定义 API 模型」管理；支持 OpenAI / Anthropic / Responses 三种协议；按账号隔离；保存到数据库后模型选择器可遍历。

## 1. 背景与目标

当前系统的大语言模型完全由静态 YAML 定义：`LanguageModelManager` 每次从
`internal/core/language_model/providers/<provider>/` 下的 `positions.yaml` + `<model>.yaml`
构建，**没有任何数据库参与**。应用的 `model_config.provider/model` 必须能在该注册表中找到
（`app_service._process_and_validate_model_config` 严格校验，找不到即回退默认模型）。

用户需要一个「通用模板」，方便日后添加兼容 OpenAI / Anthropic / Responses 三种协议的 API 模型：
在设置页添加 → 保存到数据库 → 刷新后在模型选择器里能遍历出来、能在应用里选中使用。

### 目标
- 在设置页新增一个可增删改查的「自定义 API 模型」列表。
- 每条记录含：名称、协议（openai / anthropic / responses）、模型 ID、Base URL、API Key、
  能力标记（tool_call / agent_thought / image_input）、context_window、max_output_tokens、备注、图标。
- 保存到数据库；**刷新后**模型选择器（`/language_models`）能列出这些自定义模型并入 provider 分组。
- 应用可选择自定义模型作为 `model_config.provider/model`，并能通过现有加载路径构造出真实 LLM 实例。

### 非目标
- 不改造采样参数模板（temperature/top_p 等本轮不做，走默认）。
- 不做协议探测/连通性校验（后续可加）。
- 不做模型自动发现（不调 `/v1/models`）。
- 不着手把已有静态 provider 迁移为 DB（本次只新增 custom_api 通道）。

## 2. 决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 可见范围 | 按账号隔离（类似 `api_tool_provider` 属主模式） |
| 在模型选择器的呈现 | 单独一个 provider 分组「自定义API模型」，provider key 用保留值 `custom_api` |
| 每条自定义模型的 model key | 用**记录 UUID**（`custom_api/<uuid>`） |
| 字段 | 名称、协议、模型 ID、Base URL、API Key + 能力标记（tool_call/agent_thought/image_input）+ context_window/max_output_tokens + 备注/图标（不含采样参数） |
| Anthropic 依赖 | 新增 `langchain-anthropic` 到 `requirements.txt` |
| 实现方案 | **方案 A**：自定义模型合并进 `LanguageModelManager` 的动态 provider |

## 3. 架构

### 3.1 总体思路（方案 A）

`LanguageModelManager` 是静态 YAML + 动态「自定义 provider」的合并视图。核心改动：

- 新增一张表 `api_llm_model` 存用户自定义模型（属主 `account_id`）。
- 新增 `custom_api` provider。它不是磁盘上的 YAML provider，而是根据**当前账号**的
  `api_llm_model` 记录动态构建的 provider：
  - `provider_entity`：`name=custom_api`，`label=自定义API模型`；
  - `model_entity_map`：每条自定义模型一条 `ModelEntity`，`model_name=custom_api/<uuid>`；
  - `model_class_map`：按协议分发模型类（见 3.3）。
- `LanguageModelManager` 增加「注入当前账号自定义模型」的入口，使：
  - `get_provider('custom_api')` 能返回该动态 provider；
  - `get_model_entity` 能命中 `custom_api/<uuid>`；
  - `get_language_models()` 遍历时自动列出这些模型；
  - `load_language_model()` 能按 model_config 构造出真实实例。

关键约束：`LanguageModelManager` 目前是无状态、每次新建。各消费方（`language_model_service`、
`app_service`、`app_config_service`、`indexing_service`）各自 `LanguageModelManager()` 新建。
因此对 custom_api 的注入必须**在每个 manager 构建点**（容器工厂）完成，且要拿到当前账号的
自定义模型列表。由于账号信息来自请求上下文（`RequestSessionProxy` / `get_request_context`），
需要一处能按当前请求解析账号 + DB 读取自定义模型的地方。

### 3.2 注入点与数据流

方案：改造 `LanguageModelManager` 构造为「静态 YAML 渲染 + 可选 DB 合并」两步，`merge_account_models`
在 manager 已经用 YAML 构建好静态 provider 之后调用。DB 读取通过传入的 `account_id` 及 session 委托完成。

- `LanguageModelManager.merge_account_custom_models(account_id)`：读取当前账号的
  `api_llm_model` 记录（经 session 代理），构建 `custom_api` provider 并入 `provider_map`。
- 容器工厂（`container.py`）在各 `LanguageModelManager()` 构建点改为：
  先 `LanguageModelManager()`，再视请求上下文有无账号 `await merge_account_custom_models(account_id)`。
  由于工厂是同步函数，DB 读取需经 `asyncio.to_thread`/`run_sync_bridge` 或把合并推迟到
  service/handler 首次访问时（见「延迟合并」备选）。

考虑到工厂同步性，**推荐采用懒加载**：`LanguageModelManager.get_provider('custom_api')` /
`get_model_entity` / `get_language_models` 在 `custom_api` 尚未构建时，通过注入的
`account_model_loader`（一个异步回调）按当前请求账号懒构建并缓存该账号结果。这样：
- 静态 provider 完全不受影响；
- 仅当消费方真的访问 custom_api（或遍历全部模型）时才触发 DB 读取；
- 每个请求的生命周期内缓存一次，避免重复查询。

`account_model_loader` 形如 `Callable[..., Awaitable[list[ApiLlmModel]]]`，由容器注入到
manager。manager 内部懒构建 provider 时调用它。

### 3.3 协议 → 模型类分发

`custom_api` provider 的 `get_model_class(model_type)` / `provider_entity.supported_model_types`
按记录的 `protocol` 返回对应 langchain 聊天类：

| protocol | 值 | langchain 类 | 说明 |
|---|---|---|---|
| openai | `openai` | `langchain_openai.ChatOpenAI` | OpenAI 兼容 `/v1/chat/completions` |
| responses | `responses` | `langchain_openai.ChatOpenAI(use_responses_api=True)` | OpenAI Responses API `/v1/responses` |
| anthropic | `anthropic` | `langchain_anthropic.ChatAnthropic` | Anthropic Messages API |

`use_responses_api` 由 langchain-openai 1.1.9 内置支持（已验证）。

每条自定义模型的 `ModelEntity` 通过 `attributes` 携带：`model`（= 用户的模型 ID）、
`base_url`、`api_key`；`features`/`context_window`/`max_output_tokens` 取自记录本身。
模型类构造走现有 `language_model_service.load_language_model` 的
`model_class(**attributes, **parameters, context_window=..., features=..., metadata=...)` 路径，
因此构造签名需与现有各 provider 的 `chat.py` 兼容（即接受 base_url、api_key、model 关键字）。

### 3.4 数据库

新增表 `api_llm_model`（Postgres）：

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | 主键（= 模型 key 的 UUID 部分） |
| account_id | UUID | 归属账号（按账号隔离） |
| name | String(255) | 展示名（模型选择器里显示） |
| protocol | String(50) | openai / responses / anthropic |
| model_id | String(255) | 请求体 model 字段（如 gpt-4o / claude-3-5-sonnet） |
| base_url | String(500) | 端点地址（可选，空取默认） |
| api_key | Text | 敏感，AES 加密存储（复用系统配置加密） |
| features | JSONB | 能力标记数组：["tool_call","agent_thought","image_input"] |
| context_window | Integer | 上下文窗口长度 |
| max_output_tokens | Integer | 最大输出 tokens |
| remark | Text(可空) | 备注 |
| icon | String(500)(可空) | 图标 URL |
| created_at / created_by / updated_at / updated_by | datetime / str | 审计列 |
| is_deleted | Boolean | 逻辑删除 |

复用 `internal/model/api_tool.py` 的写法；`features` 用 JSONB 存字符串列表。
API Key 加密复用 `system_config_service` 的 AES 逻辑（抽公共工具函数或直接引 `_encrypt_value`/`_decrypt_value`）。

### 3.5 设置页交互

新增一个设置 tab「自定义模型」（或并入现有「大模型配置」页下方独立区块）：
- 列表展示当前账号的自定义模型（名称、协议、模型 ID、Base URL、能力标记、上下文/tokens、备注、图标）。
- 新增/编辑表单：名称（必填）、协议（下拉：openai/responses/anthropic）、模型 ID（必填）、
  Base URL、API Key（敏感、加密存储、编辑不显示明文）、能力标记（多选：tool_call/agent_thought/image_input）、
  context_window、max_output_tokens、备注、图标。
- 删除：逻辑删除。
- 保存到 DB 后刷新，模型选择器（应用模型配置）即可出现「自定义API模型」分组及对应模型选项。

### 3.6 后端接口（REST）

按 `api_tool` 风格注册在 llmops router：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/custom_llm_models` | 当前账号自定义模型列表 |
| POST | `/custom_llm_models` | 新建 |
| GET | `/custom_llm_models/{id}` | 详情 |
| PUT | `/custom_llm_models/{id}` | 更新 |
| DELETE | `/custom_llm_models/{id}` | 逻辑删除 |

依赖注入：`CustomLlmModelService` + `LanguageModelManager`。handler 返回 schema 遵循现有
`GetApiToolProvidersWithPageResp`/`GetApiToolProviderResp` 的 `model_validator(mode="before")` 风格。

## 4. 错误处理

- 新建/更新：名称、模型 ID 非空；protocol 必须在枚举内；features 值必须在枚举内；
  context_window/max_output_tokens 为正整数。
- API Key 保存时 AES 加密；读取接口返回脱敏（同 settings 的 `********` 或 hasValue 语义）。
- 删除采用逻辑删除（`is_deleted=True`）；已存在应用引用 `custom_api/<uuid>` 的仍可读，但模型选择器不再列出。
- custom_api 懒加载失败（DB 不可达 / 无请求上下文）时，custom_api provider 视为不存在，不阻塞静态 provider。

## 5. 测试

- 单元：协议 → 模型类分发（openai / responses / anthropic 各自返回正确类）。
- 单元：来自 DB 记录的 `ModelEntity` 构建（attributes 中 model/base_url/api_key、features、context/max_tokens 正确填充）。
- 单元：`get_language_models()` 在注入账号自定义模型后能列出 custom_api 分组；无自定义记录时不出现该分组。
- 单元：`load_language_model()` 对 `custom_api/<uuid>` 能构造出对应协议实例（mock DB）。
- 集成（可选，gate 门禁）：校验路径 `_process_and_validate_model_config` 对 `custom_api/<uuid>` 放行。
- 前端：`vue-tsc` 类型检查；设置页自定义模型表单增删改查逻辑冒烟。

## 6. 变更文件（预估）

**后端**
- `internal/model/api_llm_model.py`（新增表模型）
- `internal/migrations/versions/xxxx_add_api_llm_model.py`（新增迁移）
- `internal/core/language_model/language_model_manager.py`（新增 custom_api 动态 provider + 懒加载/注入）
- `internal/core/language_model/entities/provider_entity.py`（供动态 provider 使用，可能小幅扩展）
- `internal/core/language_model/providers/custom_api/chat.py` + `protocol_mapping`（协议→类分发）
- `internal/schema/custom_llm_model_schema.py`（新增）
- `internal/handler/custom_llm_model_handler.py`（新增）
- `internal/service/custom_llm_model_service.py`（新增）
- `internal/container.py`（新增服务/handler 工厂 + 给 manager 注 loader）
- `internal/router/router.py`（注册路由）
- `internal/config/settings.py` / `internal/service/__init__.py`（导出，如需）
- `requirements.txt`（加 `langchain-anthropic`）

**前端**（`ai-code-llmops-web`）
- `src/views/settings/components/CustomLlmModelConfig.vue`（新增）
- `src/views/settings/SystemSettings.vue`（接新 tab/区块）
- `src/services/custom-llm-model.ts`（新增 API 封装）
- `src/models/custom-llm-model.ts`（新增类型）
- `src/views/settings/components/LlmProviderConfig.vue`（若有分组标题需同步）

## 7. 风险与后续

- `langchain-anthropic` 新增依赖，需 `pip install` 并写入 requirements.txt。
- 懒加载合并逻辑是本次最有价值的收敛点；需保证不破坏静态 provider 的任何既有行为
  （现有单测 `test_language_model_service.py` / `test_qwen3_local_model_env.py` 已覆盖静态路径）。
- 后续可扩展：协议连通性校验、响应/错误归一化、批量导入。
