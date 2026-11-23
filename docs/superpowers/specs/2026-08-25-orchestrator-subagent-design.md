# 编排型 Agent（Orchestrator）与子 Agent 任务分解 — 设计文档

- 日期：2026-08-25
- 状态：已与需求方逐节确认（核心引擎 + 产品接入两部分均通过）
- 相关代码：`internal/core/agent/`、`internal/service/chat_runner.py`、`internal/service/app_service.py`、`internal/task/app_task.py`、`internal/model/*`、`ai-code-llmops-web/src/`

## 1. 背景与目标

当前项目已具备：基于 LangGraph 的 `FunctionCallAgent`（preset → 记忆召回 → LLM → tools 循环）、`AgentQueueManager` 线程+队列 SSE 流式管道、工具/知识库/工作流/技能绑定、Celery 异步任务、辅助 Agent（已示范"主 Agent 通过工具委托后端任务"）、前端按事件类型渲染推理步骤（`AgentThought.vue`）。

目标：新增**编排型应用类型**。用户在该应用的会话中给出一个复杂任务后，系统自动：

1. **规划**（plan）：主 Agent 将任务分解为子任务清单；
2. **并行执行**（execute）：为每个子任务动态创建子 Agent，并行运行，过程中子 Agent 的推理/动作事件**实时穿插**推送进主会话（带 `sub_task_id`，前端零协议改动即可展示"直播"）；
3. **汇总**（summarize）：全部子任务完成后，主 Agent 综合各子结果生成最终答案。

约束（与需求方确认）：

- 子 Agent **动态创建**为主，同时允许把已发布的现有应用/工作流作为工具调用（现有 `get_langchain_tools_by_workflow_ids` / `by_skill_ids` 已支持，本期直接复用，不新增）；
- 执行过程**实时穿插流式**展示（复用现有事件管道）；
- 能力挂载为**新增"编排型"应用类型**，进入应用创建/配置/发布链路；
- **断点保存与恢复**：子任务中断（停止/超时/错误）后再次执行时从断点继续，不重头开始；已完成的子任务直接复用结果，不重跑。**恢复触发方式可配置**：`auto` 自动续跑 / `manual` 显式触发（前端"继续执行"按钮）。

## 2. 总体架构

```
用户会话（编排型应用）
   │  SSE 事件流（复用现有管道）
   ▼
ChatRunner.run() ── app_type == "orchestrator" 且 enable
   │
   ▼
OrchestratorAgent（继承 BaseAgent，LangGraph）
   plan节点 ──→ execute节点 ──→ summarize节点 ──→ END
      │                │              │
      │ 0个子任务      │              └─ 汇总子结果 → LLM 流式生成最终答案
      ▼                │
   direct_answer节点   └─ ThreadPoolExecutor 并行动态创建子 Agent
      （普通单轮回答）     （FunctionCallAgent / ReACTAgent）
                          每个子 Agent：独立 task_id + 独立线程 stream()
                          队列桥接：子事件实时转发进主队列（带 sub_task_id）
```

### 2.1 新增文件

- `internal/core/agent/agents/orchestrator_agent.py` — `OrchestratorAgent`（继承 `BaseAgent`）
- `internal/model/sub_task_checkpoint.py` — 子任务断点表模型（并在 `internal/model/__init__.py` 导出）
- `internal/service/sub_task_service.py` — 断点保存/查询/标记完成服务（线程内写库，沿用 flask app context 模式）
- 在 `internal/core/agent/agents/__init__.py` 导出 `OrchestratorAgent`

### 2.2 修改文件（核心引擎）

- `internal/core/agent/entities/queue_entity.py` — `QueueEvent` 新增 3 事件；`AgentThought` 新增 2 字段
- `internal/core/agent/agents/agent_queue_manager.py` — 新增 `forward(task_id, thought)`（只 put、无 stop 副作用）
- `internal/core/agent/entities/agent_entity.py` — `AgentState` 新增 `sub_tasks` / `sub_results` / `conversation_id` / `query` / `resume`；`AgentConfig` 新增 `orchestrator_config` 字段；新增 `SubTaskSpec` / `SubTaskResult` pydantic 模型与规划/汇总提示词模板
- `internal/core/agent/agents/function_call_agent.py` — 入口改为条件入口：正常走 `preset_operation`，`state["resume"]=True` 时直接进 `llm` 节点（向后兼容，现有调用不受影响）
- `internal/service/conversation_service.py` — `save_agent_thoughts` 白名单与透传
- `internal/service/chat_runner.py` — SSE 序列化 include 列表透传 `sub_task_id/sub_task_title`；编排器输入补 `conversation_id` / `query` / `resume_trigger`（取自请求的 `resume` 字段）
- `internal/service/app_service.py`、`internal/handler/*`（如需）— 会话删除时级联清理断点

## 3. 核心引擎设计

### 3.1 图结构

`OrchestratorAgent._build_agent()` 构建 `StateGraph(AgentState)`：

| 节点 | 职责 |
|---|---|
| `plan` | LLM `with_structured_output` 输出 `list[SubTaskSpec]`；空列表 → 条件边走 `direct_answer`；非空 → 发布 `SUB_TASK_PLAN` 事件 |
| `direct_answer` | 普通单轮 LLM 回答（编排器退化行为，复用 `FunctionCallAgent._llm_node` 思路），流式 `AGENT_MESSAGE` → `AGENT_END` |
| `execute` | `ThreadPoolExecutor(max_workers=max_parallel)` 并行执行子任务；每个子任务先查断点：中断过→恢复续跑，已完成→复用缓存结果，否则全新执行；桥接事件；监控停止；收集 `SubTaskResult[]` 写入 state |
| `summarize` | LLM 依据 `sub_results` 生成最终答案，流式 `AGENT_MESSAGE` → `AGENT_END` |

条件边：`plan → (子任务数>0) execute | (==0) direct_answer`；`execute → summarize`；`summarize → END`；`direct_answer → END`。

### 3.2 AgentState 扩展（`agent_entity.py`）

```python
class SubTaskSpec(BaseModel):
    order: int
    title: str
    role_prompt: str          # 子 Agent 的 preset_prompt
    expect_output: str
    required_tools: list[str] = []   # 可选，从应用工具池按名过滤
    task_id: UUID | None = None      # execute 节点派发时赋值为 uuid4()，桥接/停止用

class SubTaskResult(BaseModel):
    order: int
    title: str
    status: str               # normal / error / stop / timeout
    answer: str
    error: str = ""
    latency: float = 0.0
    resumed: bool = False     # 是否从断点恢复

class AgentState(MessagesState):
    # ...现有字段...
    sub_tasks: list[SubTaskSpec] = []      # 带默认值，防 langgraph map_input 丢弃
    sub_results: list[SubTaskResult] = []
    conversation_id: UUID | None = None    # 断点键的一部分（chat_runner 注入）
    query: str = ""                        # 原始用户提问，断点有效性校验（chat_runner 注入）
    resume: bool = False                   # 恢复模式标记（仅用于 FunctionCallAgent 条件入口）
    resume_trigger: bool = False           # 请求级显式恢复标记（manual 模式由前端按钮置位）
```

### 3.3 子 Agent 创建（execute 节点）

每个 `SubTaskSpec` 动态创建子 Agent：

- 模型：与编排器同一 `model_config`（同一 provider/model）
- 类：支持 tool_call → `FunctionCallAgent`，否则 `ReACTAgent`
- `AgentConfig`：`preset_prompt=spec.role_prompt`、`tools=`（应用工具池按 `required_tools` 过滤，为空则全量）、`user_id/invoke_from` 与编排器一致
- 每个子 Agent 独立 `task_id = uuid4()`，在其自身线程内执行 `sub_agent.stream({...})`
- **断点分支**：执行前先查断点（见 3.7）——有中断断点→以 `resume=True` + 断点消息续跑；已完成→不执行，直接复用缓存结果；无断点→全新执行

### 3.4 队列桥接（关键实现细节）

- `AgentQueueManager` 新增：
  ```python
  def forward(self, task_id: UUID, thought: AgentThought) -> None:
      """桥接用：仅写入目标队列，不触发 stop_listen 语义"""
      self.queue(task_id).put(thought)
  ```
  （不能复用 `publish()`——它对 STOP/ERROR/TIMEOUT/AGENT_END 会 `stop_listen`，若桥接误用会提前终止主监听。）
- execute 节点为每个子任务开一个桥接循环：
  ```python
  for t in sub_agent.stream(input):
      if t.event in (PING, AGENT_END, STOP, TIMEOUT, ERROR):
          continue  # 终态由执行器转为 SUB_TASK_END，主消息只保留编排器自己的 AGENT_END
      bridged = t.model_copy(update={"sub_task_id": spec.task_id,
                                     "sub_task_title": spec.title})
      orchestrator_qm.forward(main_task_id, bridged)
  ```
- 子任务开始/结束时执行器发布 `SUB_TASK_START`（thought=role_prompt 摘要）与 `SUB_TASK_END`（observation=状态+answer 摘要，latency=耗时）。

### 3.5 停止 / 超时 / 错误处理

- **停止传播**：监控线程轮询主 task 的 stop 标志（`AgentQueueManager._is_stopped(main_task_id)`），置位后对每个运行中子任务调 `AgentQueueManager.set_stop_flag(sub_task_id, invoke_from, user_id)` → 子 Agent listen 循环自动终止 → 执行器发 `SUB_TASK_END(status=stop)`，编排器发布 `STOP` 收尾。
- **超时**：单子任务超时 `sub_task_timeout` 秒 → 标记 `status=timeout`，不阻塞其他子任务；全部结束后仍走 summarize（带错误说明）。
- **子任务失败**：子 Agent 抛错 → `status=error` + 记录 error，其余子任务不受影响；全部失败时 summarize 输出失败说明（不编造成功）。
- **主监听超时/停止**：复用现有 `listen()` 逻辑（600s 超时、Redis stop 标志），无需改动。

### 3.6 计费与统计

零改动：`AgentThought` 自带 token/price 字段；桥接事件原样携带，`chat_runner` 现有累加逻辑覆盖；`SUB_TASK_END` 事件通过 `total_token_count` / `total_price` / `latency` 字段携带该子任务统计，便于前端与排查。

### 3.7 断点保存与恢复

**目标**：子任务中断（用户停止 / 超时 / 错误）后，同一会话再次执行同一任务时从断点继续，不重头开始；已完成的子任务直接复用结果，不重跑。

**断点是什么**：子 Agent 的 LangGraph 工作状态。每个桥接事件 `AgentThought.message` 都携带该步骤的完整消息列表（`messages_to_dict(state["messages"])`，含系统提示词），因此中断时可以从最后一个事件重建出 `messages` + `iteration_count` + 已流出答案，即完整断点。

**存储**：新表 `sub_task_checkpoint`（见 4.3），按 `(conversation_id, position)` 定位，并记录创建时的原始 `query` 用于有效性校验。

**保存时机**：
- 子任务**异常终止**（stop/timeout/error）时保存断点（状态记为对应终态）；
- 运行中**周期落盘**（默认每桥接 10 个事件且距上次落盘超过 10 秒时写一次，状态为 running），进程/服务中断时也能从最近一次周期点恢复；
- 子任务**成功完成**时写入最终答案并标记 complete（结果缓存）。

**恢复触发（可配置，`orchestrator_config.resume_mode`）**：
- `"auto"`（默认）：同一会话内再次发起编排（用户重发相同任务），execute 节点按 `(conversation_id, position)` 查断点自动续跑；
- `"manual"`：仅当请求显式携带 `resume=true`（前端"继续执行"按钮，重发原 query + resume 标志）时才续跑；普通重发按全新任务执行。

查断点逻辑（两种模式共用）：
- 断点存在且 `query == 当前提问`（字符串完全匹配）且状态为 stop/timeout/error/running → **恢复续跑**；
- 状态为 complete → **跳过执行**，直接复用缓存答案；
- 无断点或 query 不匹配（新任务）→ 全新执行，并覆盖旧断点。

**显式触发链路（manual 模式）**：聊天请求结构体（调试会话 `app_schema.py`、Web 应用会话）新增可选字段 `resume: bool = False` → `chat_runner` 写入 `AgentState.resume_trigger` → execute 节点在 `resume_mode=="manual"` 且 `resume_trigger=False` 时不查断点、全新执行；消息列表响应为编排型应用补充 `can_resume` 标记（message.status ∈ {stop, timeout, error} 且存在断点），供前端渲染"继续执行"按钮（详见 5.4、第 6 节）。

**恢复执行机制**：`FunctionCallAgent._build_agent()` 入口改为**条件入口**（`set_conditional_entry_point`）：`state["resume"]=True` 时直接进 `llm` 节点，否则维持原 `preset_operation`。断点消息已含系统提示词，恢复时以 `resume=True` + `messages=断点消息` + `iteration_count=断点值` 调用子 Agent，LLM 循环从原处继续。现有非编排调用不传 `resume`，行为完全不变。

**校验与清理**：query 不匹配视为新任务；删除会话/消息时级联清理该会话断点。

**边界**：v1 断点只覆盖子任务级；编排器的规划/汇总阶段不落断点（重跑时重新规划，子任务续跑）。恢复后旧的部分答案不会重放，前端通过 `SUB_TASK_START` 的 thought 附注"已从断点恢复（已有 N 字/步）"提示用户。

## 4. 事件协议与数据模型

### 4.1 QueueEvent 新增（`queue_entity.py`）

```python
SUB_TASK_PLAN  = "sub_task_plan"   # thought = 子任务清单 JSON
SUB_TASK_START = "sub_task_start"  # thought = 子任务角色/目标摘要
SUB_TASK_END   = "sub_task_end"    # observation = 状态+结论摘要, latency=耗时
```

### 4.2 AgentThought 新增字段（向后兼容，默认值）

```python
sub_task_id: UUID | None = None
sub_task_title: str = ""
```

### 4.3 落库（alembic 迁移）

`message_agent_thought` 加 2 列：

- `sub_task_id UUID NULL`、`sub_task_title TEXT DEFAULT ''`
- `conversation_service.save_agent_thoughts`：持久化白名单加入 `SUB_TASK_PLAN / SUB_TASK_START / SUB_TASK_END`；create 透传 `sub_task_id / sub_task_title`
- `chat_runner._stream_and_persist`：SSE `model_dump(include=...)` 加入 `"sub_task_id", "sub_task_title"`
- 响应 schema（`app_schema.py` 中 agent_thoughts dump、`assistant_agent_schema.py` 同步）加入两字段

**新表 `sub_task_checkpoint`**（断点保存与结果缓存）：

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | 主键 |
| app_id / conversation_id / message_id | UUID | 归属；message_id 为最后触达的消息 |
| position | int | 子任务在规划中的序号（断点定位键之一） |
| query | text | 创建时的原始用户提问（有效性校验） |
| title / role_prompt / expect_output | text | SubTaskSpec 快照 |
| required_tools | JSONB | SubTaskSpec 快照 |
| status | varchar | running / stop / timeout / error / complete |
| messages | JSONB | 最近一步的完整消息列表（恢复用） |
| iteration_count | int | 已迭代次数（恢复用） |
| partial_answer | text | 已流出的部分答案 |
| total_token_count / total_price | int / numeric | 已累计统计 |
| created_at / updated_at | datetime | 时间戳 |

索引：`(conversation_id, position)`。会话/消息删除时级联清理（`sub_task_service.clear_checkpoints(conversation_id)`）。

## 5. 产品接入（编排型应用类型）

### 5.1 数据模型（同一 alembic 迁移）

- `App` 表新增 `app_type: str = "agent"`（枚举值 `"agent" | "orchestrator"`）
- `internal/entity/app_entity.py` 的 `DEFAULT_APP_CONFIG` 新增：
  ```python
  "orchestrator_config": {
      "enable": False,         # 是否启用任务分解
      "max_sub_tasks": 5,      # 子任务数上限
      "max_parallel": 3,       # 最大并行数
      "sub_task_timeout": 300, # 单子任务超时(秒)
      "resume_mode": "auto",   # 断点恢复触发：auto 自动续跑 / manual 仅显式触发
  },
  ```
- `AppConfig` / `AppConfigVersion` 表各新增 `orchestrator_config JSONB`（默认 `'{}'`）

### 5.2 创建/发布链路（透传）

- `internal/schema/app_schema.py`：`CreateAgentAppReq` 加 `app_type`；应用响应 dump 加 `app_type`
- `internal/service/app_service.py`：`create_app`、拷贝复制逻辑透传 `app_type`
- `internal/task/app_task.py`：`auto_create_app` 接收并透传 `app_type`

### 5.3 运行期选择（`chat_runner.py` 第 122 行附近）

```python
if app.app_type == "orchestrator" and app_config.get("orchestrator_config", {}).get("enable"):
    agent_class = OrchestratorAgent
elif ModelFeature.TOOL_CALL in llm.features:
    agent_class = FunctionCallAgent
else:
    agent_class = ReACTAgent
```

`OrchestratorAgent` 的 `AgentConfig` 额外携带 `orchestrator_config`（内部读取 max_parallel / resume_mode 等）。OpenAPI 服务复用同一运行链路，编排型应用发布后 API 调用自动可用（验证时确认 `open_api_service.py` 无遗漏）。

### 5.4 显式恢复触发链路（manual 模式）

- 聊天请求结构体：调试会话（`internal/schema/app_schema.py`）与 Web 应用会话请求新增可选字段 `resume: bool = False`；
- `chat_runner.run()` 将 `resume` 写入输入 `AgentState.resume_trigger`（编排器专用，普通 Agent 忽略）；
- execute 节点恢复判断：`resume_mode == "manual"` 且 `resume_trigger == False` → 不查断点、全新执行；
- 消息列表分页响应（`internal/schema/app_schema.py` 消息响应）为编排型应用补充 `can_resume: bool`（该消息 `status ∈ {stop, timeout, error}` 且对应会话存在断点），前端据此渲染"继续执行"按钮；按钮动作 = 重发该消息原 `query` 并携带 `resume=true`。

## 6. 前端改动

- `src/config/index.ts`：`QueueEvent` 加 `subTaskPlan / subTaskStart / subTaskEnd`
- `src/views/space/apps/components/AgentThought.vue`：
  - `sub_task_plan` → "任务分解计划"卡片（子任务标题列表，可折叠）
  - `sub_task_start/end` → 图标+文案（"子任务开始/完成"，end 显示耗时）；start 的 thought 附注"已从断点恢复"（v1 以文本呈现，不做专门 UI）
  - 步骤按 `sub_task_id` 分组折叠：现有按 event_id 折叠逻辑不动，叠加一层子任务分组头
- 三个聊天视图（`IndexView.vue / PreviewDebugChat.vue / HomeView.vue`）：事件累积按 event_id 合并，子事件 id 唯一，预期零改动；仅验证新增两字段透传
- 编排型应用的消息气泡：当消息响应 `can_resume=true` 时渲染"继续执行"按钮（auto/manual 模式均显示；manual 模式下它是唯一恢复入口）→ 重发原 query 并带 `resume=true`；按钮仅在 message.status ∈ {stop, timeout, error} 时出现，运行中/正常消息不显示
- 应用创建/配置页（`space/apps` 下）：新增"应用类型"选择（普通/编排）+ 编排配置表单（开关、子任务上限、并行数、恢复触发方式 auto/manual）。具体组件文件在实现阶段定位后再精确改动

## 7. 测试与验证

- **单元**：
  - plan 结构化输出解析：正常分解 / 0 子任务退化 / 超过 `max_sub_tasks` 截断
  - `AgentQueueManager.forward`：无 stop 副作用（终态事件不触发 stop_listen）
  - 桥接过滤：`PING/AGENT_END/STOP/TIMEOUT/ERROR` 不转发
  - 停止传播：主 stop 标志 → 子任务 stop 标志被设置
- **集成**（pytest + Flask test client）：
  - 创建编排型应用 → 发布 → `/web_app/chat` 发"写一篇 XX 市场调研报告"
  - 断言 SSE 事件顺序：`SUB_TASK_PLAN → SUB_TASK_START×N（含并行交错事件）→ SUB_TASK_END×N → AGENT_END`
  - 断言 `message_agent_thought` 落库含 `sub_task_id`
  - 断言 token/price 累加正确
  - 断言停止接口（`stop`）能终止子任务
- **断点专项测试**：
  - 中断续跑：子任务执行中途 stop → 断点落库（status=stop、messages 非空）→ 同会话重发相同 query → 断言该子任务以 `resume=True` 续跑（事件续接、iteration_count 延续、不重头）
  - 结果缓存：子任务 complete 后重发相同 query → 断言该子任务不执行（无新 SUB_TASK_START/桥接事件），summarize 直接复用缓存答案
  - 新任务隔离：换 query 重发 → 断言旧断点不生效（全新执行并覆盖）
  - 周期落盘：断言运行中按事件数/时间触发 checkpoint 更新
  - 清理：删除会话 → 断点级联删除
  - manual 模式：`resume=false` 重发 → 全新执行（不查断点）；`resume=true` 重发 → 续跑
  - `can_resume` 标记：stop/timeout/error 消息为 true，正常/运行中为 false
- **前端**：Playwright（webapp-testing）验证计划卡片、子任务分组渲染、停止按钮

## 8. 二期（本期不做，仅记录）

- 辅助 Agent 启用编排模式
- 子任务间依赖关系（DAG，而非全并行）
- 执行后 re-plan 修正（结果不足时二次规划）
- 全局 token 预算上限
- 编排型应用专用记忆（子任务级上下文）
- 前端应用编排界面（可视化编排子任务）
- 断点：断点过期策略（TTL/版本化）；规划与汇总阶段的断点
- 断点内容快照对比（规划漂移时按内容而非 position 匹配）
