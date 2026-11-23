# Task 4 Report: 接入点改造（chat_runner / web_app_service / app_service 统一走 MemoryProvider）+ 受影响测试更新

**Status: DONE_WITH_CONCERNS** — 全部实现并提交，测试 GREEN（全量仅剩 1 个已知既有失败），但有两处对 brief 字面代码的必要适配（见 Concerns）。

## What I implemented

### Step 1 — `internal/service/chat_runner.py`
- 导入区：删除 `MemoryTools` / `EpisodicMemoryService` / `ProceduralMemoryService` / `UserMemoryService` 导入，追加 `from .memory_provider import MemoryProvider, MemoryProviderResolver`；删除 `from threading import Thread`（Thread 已迁入 BuiltinMemoryProvider）；删除 `UUID` 导入（仅被删除的两个 `_trigger_*` 方法使用，与 Thread 同理）。
- 字段：删除 `user_memory_service / episodic_memory_service / procedural_memory_service / memory_tools`，追加 `memory_provider_resolver: MemoryProviderResolver`。
- `run()`：`llm` 加载 + `_build_history` 之后解析 provider（`memory_provider = self.memory_provider_resolver.resolve(app_config)`），情景召回改为 `if not episodic_memory: read_ctx = provider.get_read_context(app_config, conversation.app_id, account.id, message.query)`（try/except 容错，`episodic_memory = read_ctx.episodic_memory`）——**不随 enable 门控**（约束 1）。
- 工具/程序记忆段：`if enable_memory:` 门控内注入 `provider.get_memory_tools(...)`；程序记忆在 enable 时从 `read_ctx.procedural_instructions` 取，`read_ctx is None` 时二次 `get_read_context`（try/except 容错）——**随 enable 门控**（约束 2）。
- `_stream_and_persist` 新增参数 `memory_provider: MemoryProvider | None = None`（`procedural_instructions` 之后）；`run()` 调用处追加 `memory_provider=memory_provider`。
- 写侧：原两段 `if enable: Thread(...)` 删除，替换为 `if memory_provider is not None: memory_provider.trigger_write(app_config=app_config, app_id=app.id, user_id=account.id, query=message.query, answer=message.answer)`（关键字参数与 ABC 签名一致）。
- 删除 `_trigger_memory_extraction` / `_trigger_episodic_extraction` 两个方法。

### Step 2 — `internal/service/web_app_service.py`
- 删除 `user_memory_service` 字段与导入，追加 `memory_provider_resolver: MemoryProviderResolver`；`web_app_chat` 画像段替换为 `self.memory_provider_resolver.resolve(app_config).get_user_profile(app_config, app.id, account.id)`。

### Step 3 — `internal/service/app_service.py`
- 保留 `user_memory_service`（458/472 行仍用），新增 `memory_provider_resolver: MemoryProviderResolver` 字段 + 导入；`debug_chat` 画像段替换为 `self.memory_provider_resolver.resolve(draft_app_config).get_user_profile(draft_app_config, app_id, account.id)`。

### Step 4 — 受影响测试（先改后跑）
- `test_chat_runner.py`：模块级追加 `StubProvider` + `MemoryReadContext` 导入；5 个用例全部按 brief 4.2 改为 stub `runner.memory_provider_resolver.resolve`；删除 `SyncThread` 类与 `chat_runner.Thread` monkeypatch；`test_extraction_triggered_after_stream` 断言改为 `stub.triggered` 系列。
- `test_chat_runner_orchestrator.py`：追加 StubProvider，`search_episodes` monkeypatch → `resolve` stub。
- `test_chat_error_handling.py`：追加 StubProvider，**两处**（debug_chat 与 web_app_chat 用例）`service.chat_runner.episodic_memory_service.search_episodes` → `service.chat_runner.memory_provider_resolver.resolve` stub。
- `test_app_service_draft_config.py` / `test_app_service_publish_orchestrator.py`：`_build_service()` 追加 `memory_provider_resolver=MagicMock()`。

### Step 5 — 新增 provider 透传用例
- `test_chat_runner.py` 末尾追加 `TestChatRunnerMemoryProvider::test_run_reads_and_writes_through_resolved_provider`（情景/程序/工具/写侧全链路经 stub provider 透传断言）。

## TDD evidence

**RED**: 首轮 focused 运行 `pytest test/internal/service/test_chat_runner.py test/internal/service/test_chat_runner_orchestrator.py test/internal/service/test_chat_error_handling.py -x -v` 在 `TestChatRunnerProceduralMemory::test_tools_injected_when_long_term_memory_enabled` 失败（4 passed, 1 failed）：brief 4.2 提供的 `SimpleNamespace(name=n)` 工具替身被 `AgentConfig.tools: list[BaseTool]`（pydantic 严格校验）拒绝：`pydantic_core.ValidationError: Input should be a valid dictionary or instance of BaseTool`。用真实 `StructuredTool` 实例（模块级 `_stub_tools()` 助手）替代后转 GREEN。

**GREEN (focused)**: `11 passed, 1 warning (2.04s)` — 含新增用例。

**GREEN (full suite)**: `pytest test/ -x -q` → `152 passed, 1 failed`（唯一失败为已知既有失败 `test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks`，brief 明示与本任务无关，忽略）；随后去 `-x` 复跑确认无其它失败 → `190 passed, 1 failed`。PytestCacheWarning（WinError 5）为已知无害告警。

## Files changed (commit f0c56f8)

- `internal/service/chat_runner.py`（实现，-137 行净减）
- `internal/service/web_app_service.py`（实现）
- `internal/service/app_service.py`（实现）
- `test/internal/service/test_chat_runner.py`（StubProvider + 5 用例改写 + SyncThread 删除 + 新增透传用例）
- `test/internal/service/test_chat_runner_orchestrator.py`（StubProvider + 1 处替换）
- `test/internal/service/test_chat_error_handling.py`（StubProvider + 2 处替换）
- `test/internal/service/test_app_service_draft_config.py` / `test_app_service_publish_orchestrator.py`（_build_service 补字段）
- `test/internal/service/test_app_logical_delete.py`（**brief 未列，必要补充**，见 Concerns 2）

## Self-review findings

- ✅ 行为保留约束逐条核对通过：情景召回不随 enable 门控；工具/程序记忆随 enable 门控（含 read_ctx 二次读取容错）；写侧按 brief 1.7 关键字传纯值（app_config/app_id/user_id/query/answer，无 ORM 对象）。
- ✅ 全仓 grep 确认无任何残留引用 `runner.episodic_memory_service` / `procedural_memory_service` / `user_memory_service` / `memory_tools` / `_trigger_memory_extraction` / `_trigger_episodic_extraction` / `chat_runner.Thread`。
- ✅ `internal/service/__init__.py` 未动（Task 3 已有 `MemoryProviderResolver` 导出）；`internal/service/memory_provider/*`（Task 1-3 交付物）未动。
- ✅ 测试改动机械、精确、无多余内容；工作树对该批路径干净（全部已提交）。
- ✅ SSE 事件格式 / HTTP 响应结构未触碰。

## Concerns

1. **brief 字面代码与真实代码冲突（工具替身）**：brief 4.2/Step 5 的 `SimpleNamespace(name=n)` 工具列表无法通过 `AgentConfig.tools: list[BaseTool]` 的 pydantic 严格校验（首次 focused 运行即 RED 证实）。为保持用例意图（4 个具名记忆工具注入 agent_config.tools），改用真实 `StructuredTool` 实例（新增模块级 `_stub_tools()` 助手；相应地删除了 brief 4.1 加入后已无用的 `from types import SimpleNamespace`）。这是对 brief 字面代码的**必要机械适配**，非设计变更；若希望严格照 brief 原文，需同时放宽 AgentConfig.tools 类型（属额外改动，未做）。
2. **brief 未列出的第三个直接构造点**：`test_app_service_logical_delete.py` 也直接构造 `AppService(...)`（APP_SERVICE_DEPS 字典）与 `WebAppService(...)`（含将被删除的 `user_memory_service` 参数），不改会因 dataclass 字段变化报缺参/多余参数。按 brief Step 7 授权（“如有个别用例因注入字段变化报错，按同法 stub resolver 后复跑”）做了同法最小修补。
3. **写侧门控语义变化（按 brief 原文实现）**：brief 1.7 将写侧门控从 `enable` 改为 `memory_provider is not None`，而 `run()` 每次都解析出非 None 的 provider —— 即 `enable=False` 时 `trigger_write` 仍会被调用（BuiltinMemoryProvider 内部未检查 enable，会起两个子线程）。这是 brief 明确指定的代码；enable 门控责任随之转移到 Provider 实现内部（Task 7 TencentMemoryProvider 应自行判断）。现有测试全部 stub 了 resolver，无用例走真实 provider 验证该路径；生产行为差异（enable=False 时写侧线程仍启动）需 Task 7 或后续任务在 Provider 实现内收敛。
4. 次要：`procedural_instructions` 传入值现仅在 enable=True 时被覆盖（原逻辑 enable=False 时强制置空），与 brief 1.4 一致，无现有调用方受影响。

## Verification commands

```
venv\Scripts\python.exe -m pytest test/internal/service/test_chat_runner.py test/internal/service/test_chat_runner_orchestrator.py test/internal/service/test_chat_error_handling.py -x -v   → 11 passed
venv\Scripts\python.exe -m pytest test/ -x -q          → 152 passed, 1 failed（仅已知既有失败）
venv\Scripts\python.exe -m pytest test/ -q --tb=no -rf → 190 passed, 1 failed（仅已知既有失败）
```

---

## 评审修复（Review Fix）— 恢复写侧 enable 门控

**评审结论（Critical）**：原 Concern #3 属实且为规格违规——brief 1.7 的 `if memory_provider is not None:` 是 plan 缺陷；SPEC 要求"写侧随 enable 门控"且"内置路径行为零变化"。因 `run()` 无条件解析 provider，`memory_provider is not None` 恒为真，导致 `trigger_write` 在长期记忆关闭（绝大多数应用默认）时也触发，改变了既有运行时行为。

**修复**（`internal/service/chat_runner.py` `_stream_and_persist` 写侧块）：

```python
            # 12、长期记忆开启时，异步触发记忆写侧管道（由 Provider 实现，线程内仅持纯值）
            if app_config.get("long_term_memory", {}).get("enable") and memory_provider is not None:
                memory_provider.trigger_write(
                    app_config=app_config,
                    app_id=app.id,
                    user_id=account.id,
                    query=message.query,
                    answer=message.answer,
                )
```

与原实现（两段 `if app_config.get("long_term_memory", {}).get("enable"): Thread(...)`）门控语义完全一致：仅长期记忆开启时触发写侧。

**回归测试**（`test/internal/service/test_chat_runner.py`，扩展 `TestChatRunnerMemoryProvider`）：
- `test_write_not_triggered_when_memory_disabled`：`enable: False` 时断言 `stub.triggered is None`（trigger_write 未调用）。
- `test_write_triggered_when_memory_enabled`：`enable: True` 时断言 `stub.triggered is not None` 且 `stub.triggered.get("app_id") == app_id`。

**验证输出**：
```
pytest test/internal/service/test_chat_runner.py -x -v            → 8 passed（含 2 个新回归用例）
pytest test/internal/service/test_chat_runner.py test_chat_runner_orchestrator.py test_chat_error_handling.py -x -q → 13 passed
pytest test/ -x -q                                                → 154 passed, 1 failed（仅已知既有失败 test_search_fuses_and_ranks）
```

**提交**：`fix(memory): 恢复写侧 enable 门控（trigger_write 仅长期记忆开启时触发）`（见 git log 该 commit SHA）。

原 Concern #3 已由本次修复闭环；Concern #1（StructuredTool 工具替身）与 #2（test_app_logical_delete.py 补字段）维持不变。
