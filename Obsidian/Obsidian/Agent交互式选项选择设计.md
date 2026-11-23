---
tags: [ai/llmops, agent, interaction, design]
date: 2026-08-27
status: done
---

# Agent 交互式选项选择（ask_user）设计

> 关联代码：`internal/core/agent/entities/queue_entity.py`、`internal/core/agent/agents/function_call_agent.py`、`internal/core/agent/agents/agent_queue_manager.py`、`internal/service/chat_runner.py`、`internal/router/router.py`

## 背景

现状对话是**单向一问一答**：用户提问 → Agent 一次跑完 → 返回答案，Agent 无法中途停下来向用户提问。需要新增 **human-in-the-loop 交互决策点**：模型输出过程中遇到多选项时（如设计权限体系时给出 RBAC / ABAC / 混合等授权方案），暂停并把选项展示给用户，用户选择后再继续。

## 需求确认

- **触发方式**：LLM 自主决定（专用工具 `ask_user`，LLM 判断需要用户决策时调用）
- **选项形态**：单选卡片 + 自定义输入（允许用户补充自定义选项文本）
- **超时策略**：等待 + 可跳过（用户可点"跳过"，Agent 按默认方案继续）
- **作用范围**：调试对话（debug_chat）、WebApp 对话、助手 Agent 对话
- **恢复方式**：同轮续跑（同一轮对话内暂停-选择-继续，SSE 流保持打开）
- **LLM 机制**：专用工具 `ask_user`（参数 = 问题 + 选项列表），复用 FunctionCallAgent 工具调用链路

## 方案对比

| 方案 | 机制 | 优点 | 缺点 |
|---|---|---|---|
| **A（选定）** | SSE 流保持 + 队列等待 | 真正同轮续跑；改动集中；编排器子任务天然复用 | Agent 线程等待期间占用（超时兜底） |
| B | 两段式 SSE + 断点续跑 | 线程不占用 | 需主任务 checkpoint，改动大，前端流拼接割裂 |
| C | 新开一轮问答 | 最简单 | 体验割裂，违背同轮续跑诉求 |

## 核心机制与数据流

```
用户提问 → ChatRunner → Agent 子线程推理（FunctionCallAgent / OrchestratorAgent 子任务）
                              │
                    LLM 判断需要用户决策
                              │
                    调用 ask_user 工具 ──→ _tools_node 检测到 ask_user
                              │               │ 不真执行，发布 ask_user 事件
                              │               ▼
                              │    SSE 推送 ask_user（question + options）──→ 前端渲染选项卡片
                              │               │
                              │     Agent 线程阻塞：Redis BLPOP 等待选择（超时 300s）
                              │               │
                用户点选项 / 填自定义 / 点跳过 ──→ POST .../chat/choice {task_id, choice|skip}
                              │               │ 写入 Redis 选择队列
                              │               ▼
                              │    Agent 线程被唤醒，选择包装成 ToolMessage
                              │               │
                              ▼               ▼
                    LLM 带选择结果继续推理 → 同一条 SSE 流输出后续内容 → 正常结束
```

**关键点：SSE 流全程保持打开**，选项卡片出现在消息流中间，选择后继续出答案——即"同轮续跑"。

## 组件改动清单（后端）

| 文件 | 改动 |
|---|---|
| `internal/core/agent/entities/queue_entity.py` | 新增事件 `QueueEvent.ASK_USER = "ask_user"`；`AgentThought` 加字段 `question`、`options`、`choice`（用户最终选择，用于落库/回显） |
| `internal/core/agent/entities/agent_entity.py` | 加常量 `ASK_USER_TOOL_NAME = "ask_user"`；工具 schema 定义（question/options/allow_custom） |
| `internal/core/agent/agents/agent_queue_manager.py` | 加 `submit_choice(task_id, choice)`（LPUSH 选择队列）和 `wait_for_choice(task_id, timeout)`（BLPOP，带 belong 校验） |
| `internal/core/agent/agents/function_call_agent.py` | `_tools_node` 加 ask_user 分支：不执行工具，发布 ASK_USER 事件 + 阻塞等待 + 把选择作为 ToolMessage 返回 |
| `internal/service/chat_runner.py` | 构建 tools 时注入 ask_user 占位工具（让 LLM 知道可调用）；SSE 序列化 include 加 question/options |
| 新文件 `internal/service/choice_service.py` | 提交选择接口的服务逻辑：校验 task_id 归属 → 写 Redis（独立文件，不并入 chat_runner，职责单一） |
| `internal/handler` + `internal/router/router.py` | 三个入口各加 `POST .../chat/choice` 路由 |

## 生效边界（重要）

- **ask_user 仅在支持工具调用的模型（`FunctionCallAgent`）生效**：`chat_runner.py` 注入 ask_user 占位工具时，仅当 `ModelFeature.TOOL_CALL in llm.features` 且走 FunctionCallAgent 分支才注入；不支持工具调用的模型走 `ReACTAgent`，不注入 ask_user，行为与现状完全一致（无选项交互）。
- **OrchestratorAgent 主 Agent 的 plan 节点**不经过 `_tools_node`，不会触发 ask_user；**子任务**（复用 FunctionCallAgent）会触发，事件通过 `forward` 桥接到主队列。
- **ask_user 占位工具**：定义 langchain `StructuredTool`（name=`ask_user`，args_schema={question, options, allow_custom}），仅用于让 LLM 在 bind_tools 时知道可调用；其 `_run` 不会被真正执行（`_tools_node` 特殊分支拦截，永远走等待逻辑）。

## 等待与提交机制细节

- **等待**：Agent 线程在 `_tools_node` 的 ask_user 分支里 `wait_for_choice`，用 Redis `BLPOP`，超时 300 秒。超时按"跳过"处理（返回提示 ToolMessage，LLM 自行决策继续）。超时时长先写死常量，后续可从应用配置覆盖。
- **提交**：前端从 ASK_USER 事件的 `task_id` 字段拿任务 ID（子任务场景是子任务 ID），`POST .../chat/choice` 带 `{task_id, choice}` 或 `{task_id, skip: true}`。服务端校验 task_id 归属（复用 `set_stop_flag` 的 belong 校验模式，防他人乱提交），再写入 Redis。
- **编排器子任务**：子任务调用 ask_user 时，等待发生在子任务线程（队列 key 用子任务 ID），事件通过现有 `forward` 桥接到主队列推给前端，事件里带实际等待的 task_id——前端提交时用事件里的 task_id，天然对齐。

## 事件协议与持久化

### 事件协议（SSE 新增事件）

新增 `QueueEvent.ASK_USER = "ask_user"`。推送的数据结构（在现有 SSE data 基础上扩展）：

```json
{
  "event": "ask_user",
  "id": "<事件id>",
  "conversation_id": "...",
  "message_id": "...",
  "task_id": "<等待此 task_id 的选择>",
  "question": "权限方案设计采用哪种授权模型？",
  "options": ["RBAC 角色权限", "ABAC 属性权限", "RBAC+ABAC 混合"],
  "allow_custom": true,
  "thought": "...", "latency": 0
}
```

- `AgentThought` 新增字段：`question: str`、`options: list[str]`、`choice: str`（用户最终选择，落库回显用）、`allow_custom: bool`
- `event_id` 唯一标识一次提问；同一次推理内多次 ask_user 各是独立事件

### 选择提交接口

三个入口各加一个路由，逻辑相同（校验归属 → 写 Redis 选择队列）：

| 入口 | 路由 |
|---|---|
| 调试 | `POST /apps/<uuid:app_id>/debug-chat/choice` |
| WebApp | `POST /web_apps/<string:token>/chat/choice` |
| 助手 Agent | `POST /assistant_agent/chat/choice` |

请求体：

```json
// 用户选了某个选项或填了自定义
{ "task_id": "<uuid>", "choice": "RBAC 角色权限" }
// 用户点跳过
{ "task_id": "<uuid>", "skip": true }
```

- **幂等**：同一 task_id 重复提交取第一次，后续忽略（Redis SETNX 或检查 key 已存在）
- **归属校验**：复用 `generate_task_belong_cache_key` + belong 值比对（account/end-user 前缀 + user_id），防他人乱提交

### 持久化

- **落库**：`save_agent_thoughts` 已把事件存 `agent_thoughts` 表（JSON 列），ask_user 事件的 `question/options/choice` 随 `AgentThought` 序列化进去，历史消息回显时可还原选项卡片
- **选择结果**：用户 choice 写进 ask_user 事件的 `choice` 字段，随事件落库，前端历史回显时显示"已选：XXX"
- **不新增表**：现有 `agent_thoughts` 表足够承载，避免 schema 迁移

## 前端 UI 与测试

### 前端改动清单

**1. 新增通用组件 `AskUserOptions.vue`**（放 `src/components/`，三端复用）

- Props：`question`、`options`、`allowCustom`、`taskId`、`eventId`、`choice`（已选值，历史回显用）
- 交互：
  - 渲染问题文本 + 选项按钮列表（单选，点击高亮选中）
  - `allowCustom` 为 true 时显示"自定义"输入框（可输入补充方案）
  - "跳过"按钮（`{task_id, skip: true}`）
  - 点击提交 → 调对应入口的 `choice` 接口 → 提交后组件进入"已选：XXX · 继续处理中…"状态（禁用按钮，等 SSE 流后续内容）
  - 历史回显（`choice` 非空）：只展示"已选：XXX"，不可再点
- 三种状态：`等待选择`（可交互）→ `已提交`（禁用，等待续跑）→ `已完成`（回显）

**2. 事件类型与处理（三端各改）**

| 文件 | 改动 |
|---|---|
| `src/types/` 或各页 QueueEvent 定义 | 加 `askUser = 'ask_user'` |
| `PreviewDebugChat.vue` / `IndexView.vue` / `HomeView.vue` | SSE 事件处理加 `ask_user` 分支：把事件（含 question/options/task_id/allow_custom）push 进 `currentMessage.agent_thoughts`；后续 ask_user 续跑出的 `agent_message` 照常追加 |
| 三个页面的消息渲染区 | 在 AI 消息内容下渲染 `AskUserOptions`（从该消息 `agent_thoughts` 中找最后一个 `ask_user` 事件） |

**3. 历史回显**：调试对话消息接口 / WebApp / 助手消息接口返回的 `agent_thoughts` 已含 ask_user 事件（含 `choice`），前端按"已完成"状态渲染选项卡片。

**4. 调试页推理步骤**（`AgentThought.vue`）：可选加一个 `ask_user` 事件的图标+标签（"询问用户"），不阻塞主功能，低优先。

### 测试策略

**后端单元测试**（`test/` 目录已有测试基建）：
1. **ask_user 工具执行分支**：mock LLM 返回 ask_user tool_call → 断言发布 ASK_USER 事件、不执行真实工具、`wait_for_choice` 被调用
2. **选择提交 → 继续推理**：先发布选择再进 `_tools_node` → 断言 ToolMessage 内容 = 用户选择、后续 LLM 消息含选择
3. **跳过**：`wait_for_choice` 返回 skip → ToolMessage 提示"用户跳过，请自行决策"
4. **超时**：timeout 参数为 0/极小 → 等同跳过分支
5. **归属校验**：他人 task_id 提交 → 拒绝（复用 belong 校验单测模式）
6. **幂等**：同一 task_id 二次提交 → 第一次生效

**前端**（vitest 已配置）：
1. `AskUserOptions.vue`：渲染选项/自定义框/跳过；点击提交调接口；提交后禁用；choice 回显
2. SSE 分支：ask_user 事件 push 进 agent_thoughts

**联调验证**（手动 + 可选 Playwright）：
1. 调试页构造"设计权限方案"场景 → 触发 ask_user → 选"RBAC+ABAC 混合" → 观察同一条 SSE 流继续输出、落库 choice
2. WebApp / 助手入口各跑一遍
3. 编排器场景：子任务触发 ask_user → 前端从事件 task_id 提交 → 子任务续跑
