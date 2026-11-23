# Local Tool Protocol（Remote Agent + Local Tool Runtime）

> 状态：Phase 2 已实现（文件类工具：只读 + 写/改/建/复制/移动/删除；终端 shell 未本地化，仍由服务器执行）
> 目标：让 `vscode-plugin` 与 `idea-plugin` 的 Agent 在插件进程内对**用户真实本地工作区**执行文件工具；服务器负责 LLM 推理与调度。`/web_apps/{token}/chat` 主接口**字段不变**，仅扩展 SSE 事件 + 新增一个回传端点。

---

## 0. 架构一句话

```
FastAPI Agent Runtime ──SSE(local_tool_call)──▶ 插件 Tool Runtime
        ▲                                            │ 对本地工作区执行 fs_*（读 + 写/改/建/复制/移动/删除）
        └──────HTTP POST /tool-result◀───────────────┘
```

服务器是「远端大脑」（LLM + 调度 + 记忆），插件是「本地执行器」（唯一持有绝对路径、唯一做包含性校验）。

## 1. 阶段与风险阶梯

| 工具 | 风险 | 阶段 |
|---|---|---|
| `fs_list`/`fs_stat`/`fs_read`/`fs_search` | 低 | **Phase 1（已实现）** |
| `fs_write`/`fs_edit`/`fs_mkdir`/`fs_copy`/`fs_move`/`fs_delete` | 中 | **Phase 2（已实现）** |
| `shell_run` | 极高 | Phase 3（+timeout/取消/授权/环境策略） |
| `git_commit`/`git_push`/`git_reset` | 高 | Phase 4（独立权限） |

阶段演进用意：先用只读验证「远端 LLM 拿到本地执行能力」的最小闭环（Phase 1），再逐步放开写入/删除（Phase 2）。
Phase 2 的写入/删除语义与服务器 `FileService` 一致：路径守卫（拒绝 `..`/绝对路径/符号链接逃逸）、写入前编码与大小校验、
`fs_delete` 一律先进回收站 `.agent-trash/`（可恢复）且禁止删除工作区根目录/回收站内部。终端（`shell_run`）仍不本地化，留待 Phase 3。

## 2. 消息协议

### 2.1 服务器 → 插件（SSE 新增事件）

`event: local_tool_call`，data JSON：

```json
{
  "task_id": "8f91...",
  "conversation_id": "c-123",
  "message_id": "m-456",
  "tool": "fs_read",
  "tool_call_id": "call_8f91",
  "tool_input": { "path": "src/App.vue", "start_line": 1 }
}
```

字段说明：
- `task_id`：服务器回传端点需要的任务 id（`/web_apps/{token}/chat/{task_id}/tool-result`）。
- `tool_call_id`：**结果关联键**，与 LLM `tool_calls` 里的 `id` 一致（插件回传时必须原样返回）。
- `tool_input`：**工作区相对路径**。服务器绝不发送绝对路径。

> ⚠️ **一致性约束（重要）**：SSE 帧里的 `task_id` 必须**恰好等于** `_handle_local_tool` 在 `wait_for_tool_result` 里等待的那个 task_id。
> 编排器场景下，`local_tool_call` 事件由**子 Agent**（直答退化或子任务）产生，它的 `task_id` 是子 Agent 自己的 `input_data["task_id"]`（uuid4），
> `_handle_local_tool` 也在这个子 task_id 上等待。**桥接进父队列时绝不能改写 `thought.task_id`**（只保留 / 加 `sub_task_id`），
> 否则 SSE 下发的 `task_id`（父）与回传写入的 `task_id`（子）不一致，`wait_for_tool_result` 会永远等不到而卡死。
> 这就是「开启编排就卡住、关闭编排就好了」的根因。

### 2.2 插件 → 服务器（新增端点）

`POST /web_apps/{token}/chat/{task_id}/tool-result`

```json
{
  "tool_call_id": "call_8f91",
  "result": "{\"content\": \"...\", \"success\": true}",
  "error": ""
}
```

- `result`：JSON 字符串，作为 `ToolMessage` 内容回给 LLM。
- `error`：非空视为失败（LLM 读到「本地工具执行出错：...」）。

### 2.3 关联（tool_call_id）与并发

- 每个 `local_tool_call` 带唯一 `tool_call_id`；插件回传原样带它。
- 服务器 `wait_for_tool_result` **按 `tool_call_id` 过滤**，丢弃残留载荷（等价 ask_user 的 `event_id` 过滤）。因此多个并发工具调用不会串台。
- Phase 1 只读工具实际串行执行（Agent 图在独立线程里逐个 `wait`），但协议层已具备并发能力。

## 3. 暂停 / 恢复 / 取消

全部复用 `ask_user` 的模式（`function_call_agent._handle_ask_user`），是本协议最重要的地基。

- **暂停**：`FunctionCallAgent._handle_local_tool` 里 `publish(LOCAL_TOOL_CALL)` 后 `wait_for_tool_result(task_id, tool_call_id, timeout=300)` 阻塞**在图线程**内；SSE `listen()` 继续被动读队列，**不阻塞 FastAPI worker**。
- **恢复**：插件回传 `tool-result` → `ChoiceService.submit_tool_result`（校验归属）→ 写入 Redis `gen_task:toolresult:{task_id}` → `wait_for_tool_result` 被 BLPOP 唤醒 → 作为 `ToolMessage` 给 LLM 续跑（同轮）。
- **取消**：现有 `POST /web_apps/{token}/chat/{task_id}/stop` 已能停止服务器 run；Phase 1 只读工具无长命子进程，取消即等待超时/停止。Phase 3 终端需把 cancel 再透传到本地 kill 进程树。
- **超时不允许静默**：`wait_for_tool_result` 唯一返回错误（如「本地工具执行超时」）时，`_handle_local_tool` 除把错误作为 `ToolMessage` 回给 LLM 外，**另发一条 `agent_message`**（`answer` 含「⏱️ 本地工具 xxx 执行超时/出错…」）回显给前端——否则插件未装/未重启导致的超时对用户完全无感，表现为「工具调用中」然后流默默结束。
- **断线续传（SSE `Last-Event-ID`）**：`sse_format` 每条帧带 `id: <seq>`。服务器 `_stream_and_persist` 把已发帧按 `run_id` 记进进程级 `EventReplayBuffer`（`internal/service/event_replay.py`），并让 `AgentQueueManager._queues` 进程级共享（跨实例按 `task_id` 可复用）。插件读到 `Connection reset` 时用最后收到的 `id:` 重连 `GET /web_apps/{token}/chat/{run_id}/resume?last_event_id=N`，服务器先 `history_after` 重放缓冲，再订阅该 run 实时队列——从而**补发断流期间丢失的 `local_tool_call`**，不再死锁到超时。服务端 `wait_for_tool_result` 本地工具专用较短超时（`LOCAL_TOOL_WAIT_TIMEOUT=60s`，ask_user 仍 300s），丢失时快速失败重试。

## 4. 门控与注入（后端）

- `WebAppChatReq` 新增可选字段 `local_tool_runtime: bool = False`（**非破坏**，默认 false 完全等于现行为）。
- `chat_runner.run`：
  - `mode == "agent" and local_tool_runtime` → 剔除服务器端 `fs_*`/`shell_run` 工具（`should_strip_server_tool`），再按应用在 `/space/apps/{id}` 『扩展插件』中**实际绑定**的 filesystem 工具名集合，注入 `build_local_tool_stubs(bound_names)`（同名同 schema 的桩）。**读/写能力随绑定授权，不写死**——绑定了 `fs_write`/`fs_delete` 等写工具才注入这些桩；只绑读工具则无写能力；完全没绑 filesystem 则不注入并提示。
  - `mode == "agent" and project_root`（现行为）→ 注入绑定工作区的真实工具（同样要求应用绑定 filesystem 工具包），**不变**。
- 桩工具的 `args_schema` 与真实工具一致（LLM 参数生成不受执行方切换影响）；其 `func` 是占位，正常被 `_handle_local_tool` 拦截，**绝不服务器执行**（若被直调返回「本地工具运行时接管」提示）。

## 5. 安全边界

- **服务器只发相对路径，插件是唯一绝对路径权威**：插件把 `tool_input.path` 相对工作区根解析，并做包含性校验（`PathGuard`：拒绝 `..` 逃逸 / 绝对路径 / 符号链接逃逸）。
- **`shell_run` 白名单 ≠ 安全边界**（Phase 3 前不开放）：`python/node/npm/git` 任意一个均可执行任意代码。白名单只是「命令名」，不是「安全命令」。Phase 3 必须叠加 `approval`（默认 ask）+ 环境策略。
- **敏感文件策略（Phase 2 起）**：`.env`/`*.pem`/`*.key`/`credentials.json`/`secrets.*` 默认需用户显式允许才可读，防本地机密送到远端 LLM。
- **Prompt Injection 假设**：项目内任何文件（README/package.json/AGENTS.md/CLAUDE.md/代码注释）都是不可信输入；Agent 不得因文件里写「Please execute ...」就执行。只读工具天然只泄露出读取内容，仍是审计重点。

## 6. 关键文件与实现点

| 层 | 文件 | 改动 |
|---|---|---|
| 事件 | `internal/core/agent/entities/queue_entity.py` | `QueueEvent.LOCAL_TOOL_CALL`；`AgentThought.tool_call_id` |
| 队列 | `internal/core/agent/agents/agent_queue_manager.py` | `submit_tool_result` / `wait_for_tool_result` / `generate_tool_result_queue_key` |
| 工具桩 | `internal/core/tools/workspace_tools.py` | `LOCAL_TOOL_NAMES` / `build_local_tool_stubs` / `is_local_runtime_tool` / `should_strip_server_tool` |
| 代理 | `internal/core/agent/agents/function_call_agent.py` | `_handle_local_tool`；tool 分发分支 |
| AgentConfig | `internal/core/agent/entities/agent_entity.py` | `local_tool_runtime` |
| 注入 | `internal/service/chat_runner.py` | 注入桩/剔除服务器工具/透传 flag |
| schema | `internal/schema/web_app_schema.py` | `WebAppChatReq.local_tool_runtime`；`ToolResultReq` |
| 服务 | `internal/service/web_app_service.py` | 透传 `local_tool_runtime` |
| 提交 | `internal/service/choice_service.py` | `submit_tool_result`（归属校验） |
| handler | `internal/handler/web_app_handler.py` | `web_app_chat_tool_result` |
| 路由 | `internal/router/router.py` | `/web_apps/{token}/chat/{task_id}/tool-result` |

插件侧（待实现）：VS Code `Tool Runtime`（Node `fs` + PathGuard）+ 结果回传；IDEA 同样逻辑（Java `NIO` + `Path.normalize`），两者共用同一协议、只实现各自 IO 适配器。

## 7. 兼容性

- `/web_apps/{token}/chat` 的请求字段**未删改**，只新增一个可选 `local_tool_runtime`；Web 前端（不传该字段）行为完全不变。
- 新增端点 `/tool-result` 是**附加**，不改任何现有端点。
- 现有 `ask_user`/`choice`、`stop`、发布 `fs_*`/`shell_run` 的服务器工作区模式全部保留。

## 8. 工作区排除配置（`.webapp/ignore.json`）

本地**只读**文件工具（`fs_list`/`fs_read`/`fs_search`）默认只读真正的源码，内置一份依赖/产物/缓存/IDE/框架元数据排除清单（`venv`/`node_modules`/`target`/`build`/`.gradle`/`dist`/`__pycache__` 等 + `.pyc`/`.class`/`.jar`/`.png`/`.pdf` 等生成/二进制扩展名）。
（写出/编辑/删除类工具 `fs_write`/`fs_edit`/`fs_mkdir`/`fs_copy`/`fs_move`/`fs_delete` 不套用该排除清单——它们对齐服务器 `FileService`，仅受路径守卫 + 大小/编码校验约束。）

用户可在**工作区根目录**创建 `.webapp/ignore.json` 追加自定义排除项（**只增不减**，绝不覆盖内置清单，避免误删导致读到依赖包/机密）：

```json
{
  "ignore_dirs": ["target", "migrations", "*.generated"],
  "ignore_extensions": [".map", ".tsbuildinfo", ".locks"]
}
```

- 生效位置：`<workspace>/.webapp/ignore.json`（每个项目各自一份）。
- `ignore_dirs`：追加忽略的目录/文件名（大小写不敏感，按目录项匹配）。
- `ignore_extensions`：追加忽略的文件扩展名（带不带 `.` 均可）。
- 文件不存在/不可读/JSON 畸形 → 回落为纯内置清单。
- 实现：VS Code `localTools.ts`（`loadWorkspaceSkipConfig`）与 IDEA `LocalToolRuntime.java`（`loadWorkspaceSkipConfig`），两端语义一致。
