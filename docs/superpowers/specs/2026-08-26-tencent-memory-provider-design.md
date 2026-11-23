# 记忆系统 Provider 化（内置 / 腾讯 TencentDB-Agent-Memory 可切换）— 设计文档

- 日期：2026-08-26
- 状态：approved（方案 A，用户确认）
- 分支：release_20260829
- 关联代码：`internal/service/chat_runner.py`、`internal/service/web_app_service.py`、`internal/service/app_service.py`、`internal/service/system_config_service.py`、`internal/service/__init__.py`、`ai-code-llmops-web/src/views/settings/`、`ai-code-llmops-web/src/views/space/apps/components/abilities/LongTermMemoryAbilityItem.vue`

## 背景与目标

项目现有记忆系统（2026-08-24 分层记忆改造）分四层：短期记忆（`TokenBufferMemory` 滑动窗口 + 滚动摘要）、语义记忆（`UserMemoryService` 用户画像卡片）、情景记忆（`EpisodicMemoryService` Weaviate 向量召回）、程序记忆（`ProceduralMemoryService` 规则 + `MemoryTools` 工具化），由 `ChatRunner` 统一组装读写。

用户需求：接入腾讯开源的 [TencentDB-Agent-Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)（MIT 协议，腾讯云数据库团队的分层记忆框架，四层渐进流水线：提取→整合→反思→复盘，核心/场景/工作分层记忆，全本地零外部 API 依赖），在**系统设置**中新增"记忆系统"选择，选"原来的记忆系统"用现有实现（行为不变），选"腾讯"用腾讯实现。

用户确认的四个决策：
1. **切换粒度**：系统默认 + 应用可覆盖（应用配置里可单独选，缺省跟随系统）。
2. **LLM 接入**：腾讯记忆流水线复用应用当前 `model_config` 的 LLM，不新增独立模型配置。
3. **存量数据**：不迁移。原有语义/情景/程序记忆数据保留原库，切回内置后原样可用；腾讯记忆从零积累。
4. **依赖**：新增腾讯 SDK 依赖；**最终代码提交到新建 `release_20260829` 分支**。

## 范围（Scope）

**做**：
- 新增 `MemoryProvider` 抽象接口与解析器（系统默认 + 应用覆盖两级解析）。
- 新增 `BuiltinMemoryProvider`：现有记忆逻辑薄封装，**行为与现状完全一致**（默认路径）。
- 新增 `TencentMemoryProvider`：腾讯 SDK 封装（懒加载 import，SDK 缺失时告警回退内置）。
- 系统设置新增"记忆系统"tab（`MEMORY_PROVIDER`、`TENCENT_MEMORY_STORAGE_DIR` 配置项）。
- 应用配置长期记忆下新增"记忆系统"下拉（`long_term_memory.provider`），校验更新。
- 接入点改造：`web_app_service` / `app_service` 的 user_profile、`chat_runner` 的读侧（情景召回/程序记忆/记忆工具）与写侧（两个异步线程）统一走 provider。
- 腾讯流水线 LLM 适配器（复用项目 `LanguageModelService` / `BaseLanguageModel`）。
- 测试：resolver 优先级、builtin 行为一致性（现有测试全绿）、tencent 假 SDK 测试、校验测试。

**不做**：
- 不迁移存量记忆数据。
- 不改 `open_api_service`（SERVICE_API）与 `assistant_agent_service`：这两条路径本就不走长期记忆读写管线（仅注入 `conversation.summary`），与 provider 无关。
- 不做腾讯记忆在"长期记忆"审计页（`/memory/facts` 等）的展示——切到腾讯后该页为空是已知边界，后续单独迭代。
- 不评估记忆效果指标（召回命中率/注入增益基线）。

## 方案选型

- **方案 A（选定）**：抽象 `MemoryProvider` 接口 + `BuiltinMemoryProvider` / `TencentMemoryProvider` 两个实现 + `MemoryProviderResolver` 解析。单一接缝，五处记忆触达点统一走 provider；原系统逻辑原样保留；未来加第三个记忆系统只需新增实现类。
- 方案 B（弃）：`chat_runner` 等调用点直接 if/else 分支。记忆逻辑散落多处重复判断，难测难维护。

## 后端设计

### 1. 新增模块 `internal/service/memory_provider/`

```
internal/service/memory_provider/
├── __init__.py            # 导出 MemoryProvider、MemoryProviderResolver
├── base.py                # MemoryProvider 抽象基类 + MemoryReadContext 数据结构
├── builtin_provider.py    # BuiltinMemoryProvider
├── tencent_provider.py    # TencentMemoryProvider
└── resolver.py            # MemoryProviderResolver
```

**`MemoryProvider`（ABC，4 个方法覆盖全部读写触点）**：

```python
@dataclass
class MemoryReadContext:
    episodic_memory: str = ""           # 情景记忆（<情景记忆> 块）
    procedural_instructions: str = ""   # 程序记忆（行为规则/人设）

class MemoryProvider(ABC):
    def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str: ...
    def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext: ...
    def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list: ...   # list[BaseTool]
    def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None: ...
```

说明：`user_profile` 不放入 `MemoryReadContext`——它由 `get_user_profile` 单独提供（`app_service`/`web_app_service` 调用点用），`get_read_context` 只承载 `chat_runner` 的两个提示词块，避免每次对话重复查库。四个方法均显式携带 `app_config`：内置实现忽略它，腾讯实现从中取 `model_config` 构建 LLM（复用应用模型，用户决策 2）。

方法语义与现状映射：

| Provider 方法 | 现状对应（chat_runner / web_app_service / app_service） |
|---|---|
| `get_user_profile` | `user_memory_service._render_current_facts(get_current_facts(app_id, user_id, min_trust=0.3))` |
| `get_read_context` | 情景召回 `episodic_memory_service.search_episodes(app_id, user_id, query, top_k=3)` → 拼接 `- {content}`；程序记忆 `procedural_memory_service.get_instructions(app_id, user_id)` |
| `get_memory_tools` | `memory_tools.get_tools(flask_app=..., app_id=..., user_id=...)`（search/write/update/forget_memory） |
| `trigger_write` | `chat_runner._trigger_memory_extraction` + `_trigger_episodic_extraction` 两个子线程（写侧管道） |

**`BuiltinMemoryProvider`**：`@inject` dataclass，注入 `UserMemoryService`、`EpisodicMemoryService`、`ProceduralMemoryService`、`MemoryTools`、`SQLAlchemy`。四个方法直接委托现有 service（`get_user_profile` / `get_read_context` / `get_memory_tools` 为同步调用；`trigger_write` 内部起两个子线程执行现有抽取逻辑，线程内 `with flask_app.app_context()`）。**行为与现状逐字节一致**——现有 `test_chat_runner*.py` 等测试不改也能过。

**`TencentMemoryProvider`**：`@inject` dataclass，注入 `LanguageModelService`、`SystemConfigService`、`SQLAlchemy`（如需）。
- **懒加载**：`import` 腾讯 SDK 放在方法内部 try/except；`ImportError` 时 `logger.warning` 并回退内置语义（返回空上下文 / 空工具 / 不写）。
- 初始化：按 `(app_id, user_id)` 维度持有/重建腾讯记忆实例，存储目录取 `TENCENT_MEMORY_STORAGE_DIR`（缺省 `./storage/agent_memory`）。
- `get_read_context`：调腾讯记忆查询（核心记忆/场景记忆召回），渲染为与内置相同结构的提示词块（`user_profile` / `episodic_memory` / `procedural_instructions` 三个字段，字段语义对齐：user_profile=核心记忆画像，episodic_memory=场景记忆召回，procedural_instructions=行为规则）。
- `get_memory_tools`：返回空列表 + `logger.info` 提示"腾讯记忆模式下不注入内置记忆工具"（腾讯流水线自管理记忆，避免双写冲突；工具映射列为后续迭代）。
- `trigger_write`：子线程内调用腾讯记忆写入流水线（提取→整合→反思→复盘）。

**`MemoryProviderResolver`**：`@inject` dataclass，注入 `SystemConfigService`、各 provider。

```python
def resolve(self, app_config: dict) -> MemoryProvider:
    # 1) 应用覆盖：app_config["long_term_memory"].get("provider") in {"builtin", "tencent"} → 直接用
    # 2) 系统默认：SystemConfigService.get_config("MEMORY_PROVIDER") in {"builtin", "tencent"} → 用
    # 3) 缺省 builtin
```

### 2. 配置模型

**系统设置（system_config 表，沿用现有 key/value + 环境变量机制）**：

| key | 取值 | 说明 |
|---|---|---|
| `MEMORY_PROVIDER` | `builtin` / `tencent` | 系统默认记忆系统；空 = builtin |
| `TENCENT_MEMORY_ENDPOINT` | URL 字符串 | 腾讯 Memory Core 服务地址（自托管 docker 或腾讯云实例），如 `http://127.0.0.1:8420` |
| `TENCENT_MEMORY_API_KEY` | 字符串 | **敏感项**：Memory 实例 Bearer token；加入 `SENSITIVE_KEYS`（AES 加密入库、GET 脱敏） |
| `TENCENT_MEMORY_SERVICE_ID` | 字符串 | Memory 空间/实例 ID（`x-tdai-service-id`） |

- `TENCENT_MEMORY_API_KEY` 加入 `SystemConfigService.SENSITIVE_KEYS`（`system_config_service.py:29-35`）；其余两项非敏感，普通存储。`MEMORY_PROVIDER` 归组 `_guess_group` 落到 `third`。
- 运行时读取走 `SystemConfigService.get_config(key)`（DB > 环境变量 > 空），**保存后无需重启即时生效**。

> **v2 架构事实（Task 6 验证自 GitHub v2.0.1 tag 源码）**：TencentDB-Agent-Memory v2 为客户端-服务端架构——`sdk/memory-core/python`（PyPI 名 `tencentdb-agent-memory-sdk-python-v2`，README 称发布名 `tencentdb-agent-memory-sdk-python`，PyPI 可用性待用户机器确认）是纯 HTTP 客户端（依赖 httpx），类 `MemoryClient(endpoint, api_key, service_id)`；L0→L3 记忆流水线（提取/整合/反思/复盘）运行在自托管的 **MemoryCore 服务端**，SDK 不接受 LLM 参数。因此：**复用应用模型决策不再适用**（流水线用服务端自有 LLM），`TencentLlmAdapter` 为死代码，不实现。

**应用配置（`AppConfig.long_term_memory` JSON 列，透传于 `_process_and_transformer_app_config`）**：

```json
{ "enable": true, "provider": "default" }
```

- `provider`: `default`（跟随系统默认，缺省）/ `builtin` / `tencent`。
- 校验更新（`internal/service/app_service.py:996-1000`）：从 `set(long_term_memory.keys()) != {"enable"}` 放宽为 `not (set(keys) <= {"enable", "provider"})`；`provider` 取值必须在 `{"default", "builtin", "tencent"}`。
- `DEFAULT_APP_CONFIG`（`internal/entity/app_entity.py`）保持 `{"enable": False}` 不变（缺省即 default，向后兼容存量应用）。

### 3. 接入点改造（五个触点）

| 触点 | 现状 | 改造后 |
|---|---|---|
| `app_service.py:556`（debug_chat user_profile） | `user_memory_service._render_current_facts(...)` | `resolver.resolve(draft_app_config).get_user_profile(draft_app_config, app_id, account.id)` |
| `web_app_service.py:122`（web 应用对话 user_profile） | 同上 | 同上（用 `app_config`） |
| `chat_runner.py:77-84`（情景召回，不随 enable 门控） | `episodic_memory_service.search_episodes(...)` | `provider.get_read_context(app_config, app_id, user_id, query).episodic_memory`（调用方已传入 episodic_memory 时跳过，保持现有 try/except 容错） |
| `chat_runner.py:108-119`（记忆工具 + 程序记忆，随 enable 门控） | `memory_tools.get_tools(...)` + `procedural_memory_service.get_instructions(...)` | `provider.get_memory_tools(app_config, ...)` + `provider.get_read_context(...).procedural_instructions` |
| `chat_runner.py:271-297`（写侧两个子线程，随 enable 门控） | 两个 `Thread(target=_trigger_*)` | `provider.trigger_write(app_config=..., app_id=..., user_id=..., query=..., answer=...)`（provider 内部自行起线程） |

- `chat_runner.run` 注入 `memory_provider_resolver: MemoryProviderResolver`，`provider = resolver.resolve(app_config)`（每次对话解析一次，读侧与写侧共用）。注意：**情景召回现状不随 `enable` 门控**（`chat_runner.py:77-85` 无条件执行），内置实现必须保持该行为——`get_read_context` 的调用不受 `enable` 限制，只有记忆工具/程序记忆/写侧受 `enable` 门控。
- `_trigger_memory_extraction` / `_trigger_episodic_extraction` 两个私有方法迁入 `BuiltinMemoryProvider`（`trigger_write` 内部），`chat_runner` 不再持有；`ChatRunner` 的 `user_memory_service` / `episodic_memory_service` / `procedural_memory_service` / `memory_tools` 字段随之移除（改用 resolver），`WebAppService` 的 `user_memory_service` 字段若不再使用一并移除。

### 4. 腾讯 SDK 客户端与隔离映射

- 唯一接触 SDK 的模块：`internal/service/memory_provider/tencent_client.py`（懒加载 `from tencentdb_agent_memory import MemoryClient`，SDK 缺失抛 `ImportError` → provider 回退）。
- `SdkTencentMemoryClient(endpoint, api_key, service_id, *, session_id="default")`：
  - 读：`client.search_atomic(query, limit=top_k)` → `{"items": [{id, type, content, score, ...}]}` → 归一为 `{type, content, score}` 列表（`TencentMemoryClient.recall` 接口）。
  - 写：`client.add_conversation(session_id, messages=[{role:"user",...},{role:"assistant",...}])` → 服务端异步触发 L0→L3 流水线（`write_round` 接口）。
- **会话隔离映射**：`session_id = f"{app_id}:{user_id}"`（v2 的 team/agent/user 隔离字段可后续再透传，客户端接口保持简单）。

### 5. 服务注册

`internal/service/__init__.py` 追加导出：`MemoryProviderResolver`（以及 `BuiltinMemoryProvider` / `TencentMemoryProvider`，如需外部注入）。服务均为 `@inject` dataclass，injector 自动按类型解析（现有 `app/http/module.py` 无需改动）。

## 前端设计

### 1. 系统设置 — 新增"记忆系统"tab（`SystemSettings.vue`）

- `tabs` 增加 `{ key: 'memory', label: '记忆系统' }`。
- 新增 `src/views/settings/components/MemoryConfig.vue`：
  - `MEMORY_PROVIDER` 单选（内置记忆系统 / 腾讯记忆 TencentDB-Agent-Memory），值为 `builtin` / `tencent`，绑定 `envConfig.MEMORY_PROVIDER`。
  - 腾讯模式可见字段：`TENCENT_MEMORY_ENDPOINT`（URL）、`TENCENT_MEMORY_API_KEY`（敏感，输入框，保存后回显 `********`）、`TENCENT_MEMORY_SERVICE_ID`。
  - 说明文案：切换即时生效；存量记忆数据不迁移；腾讯模式需后端已安装 SDK 且可访问 Memory Core 服务（自托管或腾讯云实例）。
- `SystemSettings.vue` 的 `envConfig` 增加 `MEMORY_PROVIDER: 'builtin'`、`TENCENT_MEMORY_ENDPOINT: ''`、`TENCENT_MEMORY_API_KEY: ''`、`TENCENT_MEMORY_SERVICE_ID: ''` 四个初始键；`SENSITIVE` 集合追加 `TENCENT_MEMORY_API_KEY`。

### 2. 应用配置 — 长期记忆下拉（`LongTermMemoryAbilityItem.vue`）

- 长期记忆开启时显示"记忆系统"下拉：跟随系统默认 / 内置记忆系统 / 腾讯记忆（`default` / `builtin` / `tencent`）。
- `long_term_memory` 对象新增 `provider` 键；关闭长期记忆时 `provider` 不随 `{enable}` 重置（保存 `{ enable: false, provider }` 或重置均可，实现时以校验兼容为准——校验允许 `enable+provider` 组合）。
- 对应 TS 模型 `src/models/app.ts` 的 `long_term_memory` 类型补 `provider?: string`。

## 数据流

**读侧（对话前）**：
1. `resolver.resolve(app_config)` 取 provider（应用覆盖 > 系统默认 > builtin）。
2. `web_app_service` / `app_service`：`provider.get_user_profile(app_config, app_id, user_id)` → 注入 `<用户画像>` 块。
3. `chat_runner.run`：`provider.get_read_context(app_config, app_id, user_id, query)` → `<情景记忆>` 块 + 程序记忆文本；`provider.get_memory_tools(app_config, app_id, user_id)` → 工具列表（enable 门控）。

**写侧（对话后，子线程）**：
- `provider.trigger_write(app_config=..., app_id=..., user_id=..., query=..., answer=...)`：builtin 起两个现有抽取线程；tencent 调腾讯流水线。异常各自捕获记日志，不阻断主流程（与现状一致）。

**回退**：腾讯 SDK 缺失 / import 失败 / 初始化失败 → `logger.warning` + 返回空上下文与空工具（等效关闭长期记忆），系统不崩溃；`MEMORY_PROVIDER` 值非法 → 按 builtin 处理。

## 依赖与部署

- `requirements.txt` 腾讯 SDK 依赖（Task 6 验证结果）：PyPI 包名 `tencentdb-agent-memory-sdk-python-v2`（pyproject 实际名）或 README 宣称的发布名 `tencentdb-agent-memory-sdk-python`；PyPI 可用性本沙箱无法确认（PyPI 不可达），**当前以注释占位行记录，待用户机器确认后启用**。依赖链含 `httpx>=0.24.0`。
- **部署前提（重要）**：腾讯记忆模式需要可访问的 **MemoryCore 服务**（`deploy/global-images/start-all.sh` 一键自托管，或腾讯云托管实例），配置 `TENCENT_MEMORY_ENDPOINT` / `TENCENT_MEMORY_API_KEY` / `TENCENT_MEMORY_SERVICE_ID`。SDK 未安装或服务不可达时按"回退为无记忆"处理（见错误处理），系统不崩溃。
- Docker 构建沿用 `mirrors.tencent.com` PyPI 镜像；若 PyPI 无包则需构建环境可达 GitHub（Jenkinsfile 已有代理相关配置）。
- **Task 6 验证（已完成，2026-08-26）**：GitHub v2.0.1 tag 源码确认——模块 `tencentdb_agent_memory`，类 `MemoryClient(endpoint, api_key, service_id, *, timeout=30, verify=False, stub=None)`；读 `search_atomic(query, limit=...)` → `{"items":[{id,type,content,score,...}]}`；写 `add_conversation(session_id, messages=[{role,content}])`；L0→L3 流水线在服务端执行，SDK 不接受 LLM。

## 错误处理

| 场景 | 处理 |
|---|---|
| SDK 未安装 / import 失败 | `TencentMemoryProvider` 懒加载捕获 `ImportError`，`logger.warning`，读写均返回空（等效关记忆） |
| `MEMORY_PROVIDER` / `provider` 值非法 | resolver 按 builtin 兜底 |
| 腾讯写侧流水线异常 | 子线程内 try/except + `logger.exception`，不阻塞对话主流程 |
| 应用配置校验（provider 值） | `ValidateException`，与现有长期记忆校验一致 |

## 测试策略

遵循仓库模式：`test/conftest.py` 的 `db` fixture（真实 DB + 事务回滚）、`injector.get(Service)` 取真实服务、`monkeypatch` 替换 LLM/依赖。

1. **`test/internal/service/memory_provider/test_resolver.py`**：
   - 无配置 → builtin；系统 `MEMORY_PROVIDER=tencent` → tencent；应用 `provider=tencent` 覆盖系统 builtin；应用 `provider=default` 跟随系统；非法值兜底 builtin。
2. **`test/internal/service/memory_provider/test_builtin_provider.py`**：
   - 四个方法输出与现有 service 直调一致（对照现有行为）；`trigger_write` 触发两个抽取线程（monkeypatch 抽取方法断言调用）。
3. **`test/internal/service/memory_provider/test_tencent_provider.py`**：
   - SDK 缺失回退（monkeypatch `_build_client` 返回 None → 空上下文/空工具/不写）；
   - 假客户端（monkeypatch `_build_client` 返回 FakeClient）→ 读侧渲染（core→procedural_instructions、scene→episodic_memory）、写侧调用、构造参数（endpoint/api_key/service_id 来自系统配置、session_id=f"{app_id}:{user_id}"）。
4. **既有回归**：`test_chat_runner.py`、`test_chat_runner_orchestrator.py`、`test_chat_error_handling.py` 中直接 monkeypatch `runner.episodic_memory_service.search_episodes` / `_trigger_memory_extraction` 等内部成员的用例，需改为 stub `runner.memory_provider_resolver.resolve` 返回测试替身 provider（injector 默认非单例，monkeypatch 无法穿透到 provider 内部的服务实例）。改法机械、语义不变；其余用例不动，全绿。
5. **校验测试**：`long_term_memory.provider` 合法值通过、非法值 `ValidateException`。
6. 每个 Task 结束 `pytest test/ -x` 确认无回归（仓库 Global Constraints）。

## 已知边界与限制

- 应用详情的"长期记忆"审计页（`/memory/facts`、`/memory/episodic`、`/memory/instructions`）仍读内置三张表；腾讯模式下显示为空。后续迭代再做腾讯侧展示。
- 腾讯模式下不注入内置记忆工具（`search_memory` 等），Agent 无法通过工具主动读写记忆（腾讯流水线自管理）；工具映射为后续迭代。
- `open_api_service` / `assistant_agent_service` 两条路径不受影响（本就未走长期记忆读写管线）。
- 切换 provider 只影响之后的新对话/新抽取；存量数据与已生成的会话摘要不受影响。
- **部署边界（腾讯模式）**：依赖自托管/云端的 MemoryCore 服务与三件配置（endpoint/api_key/service_id）；SDK 或服务不可用时腾讯模式等效关闭记忆，不阻塞对话。PyPI 包发布状态待用户机器确认（当前仅注释占位）。

## 提交计划

- 新建分支 `release_20260829`（基于 `release_20260828`），按仓库现有分步提交模式（feat 前缀 + 每 Task 测试通过后提交）。
- 提交内容：后端 provider 模块与接入点改造、校验更新、前端系统设置 tab 与应用配置下拉、测试、依赖清单更新、本设计文档。
