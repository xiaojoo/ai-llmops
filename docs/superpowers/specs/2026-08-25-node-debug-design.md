# 节点级调试与画布节点状态可视化 — 设计文档

- 日期：2026-08-25
- 状态：approved（方案 A）
- 分支：release_20260827
- 关联代码：`internal/core/workflow/`、`internal/service/workflow_service.py`、`internal/handler/workflow_handler.py`、`ai-code-llmops-web/src/views/space/workflows/`

## 背景与目标

当前工作流调试只能"整图运行"（LangGraph 任一节点异常即整体中止），无法单独验证某个节点；画布上只有失败节点红框，没有成功/运行中/跳过等状态反馈。

本次目标（用户需求）：
1. 支持**单个/多个选中节点调试**：只运行选中节点的上游闭包，给出真实输出。
2. 画布**节点状态可视化**：哪个节点完成立刻显示绿色 ✓（右上角），失败显示红框，运行中/跳过有对应表现；下次运行/关闭调试时清除。
3. **分支级失败语义**：失败"影响全局"（被下游引用或处于必经路径）→ 终止全流程；"不影响全局"（独立并行分支）→ 该分支标记失败，其他分支继续。

用户确认的三个语义：
- 节点级调试 = 运行选中节点的上游闭包（推荐项）；
- 分支失败 = 按引用关系判定（推荐项）；
- 状态显示 = 运行中动态显示，下次运行/关闭调试时清除（推荐项）。

明确不做：不删除/不修复 google_serper 失效节点；不更换执行引擎。

## 方案选型

- **方案 A（选定）**：继续基于 LangGraph。`BaseNode` 统一异常捕获 + 新增 `failed_nodes` 状态通道 + 节点前置检查；节点级调试用"上游闭包子图 + 合成 END"。
- 方案 B（弃）：自研 DAG 执行器替换 LangGraph，改动大、风险高。

## 后端设计

### 1. 节点级/选中节点调试

**API**：`POST /workflows/<id>/debug` 请求体扩展为 `{inputs: {...}, node_ids?: [uuid, ...]}`。
- 兼容旧格式：请求体不含 `node_ids` 字段时按整个工作流运行（现有前端不受影响）。
- 校验：`node_ids` 必须是非空 UUID 数组且存在于草稿图节点中；无效则返回校验错误。

**子图构建**（新增纯函数模块 `internal/core/workflow/utils/subgraph.py`）：
1. 计算选中节点的**上游闭包**：选中节点 + 全部传递前驱（逆邻接表 DFS）+ 端点均在闭包内的边。
2. 若原 END 节点不在闭包内，追加**合成 END**：`id=新UUID`、`node_type=end`、title=「调试输出」、`outputs=[VariableEntity(name="output", value={type: REF, content:{ref_node_id: 目标节点id, ref_var_name: 目标节点首个输出变量名}})]`，并添加边 目标节点 → 合成 END。
3. 用闭包构建 `WorkflowConfig`（name 用 `{tool_call_name}_debug`，满足名称正则），复用其严格校验（单 START/END、连通、无环、引用校验均自动满足）。
4. 用该配置构建 `WorkflowTool` 流式运行。

`WorkflowService.debug_workflow` 增加 `node_ids` 参数处理：有则走子图路径，无则原逻辑。

### 2. 分支级失败语义（核心）

**节点统一包装**：
- `BaseNode` 增加统一 `invoke` 包装（每个节点核心逻辑从 `invoke` 改名 `run`）：
  - 前置检查 → 跳过判定；
  - `try: return self.run(state, config, **kwargs)`；
  - `except Exception as e: return {node_results: [NodeResult(status=FAILED, error=str(e), ...)]}`（不抛出，LangGraph 继续调度）。
- `NodeResult` 增加 `SKIPPED` 状态（`NodeStatus` 枚举加 `SKIPPED = "skipped"`）。

**新增状态通道**：`WorkflowState` 增加 `failed_nodes: Annotated[list[UUID], reducer(累加)]`。

**前置检查**（`BaseNode.invoke` 内，`_check_skip(state)`）：
1. 任一**直接前驱**（边 source）∈ failed_nodes，或任一 **REF 来源** ∈ failed_nodes → 返回 `SKIPPED` 结果（error 注明"上游节点[title]执行失败，本节点跳过"），并把自己 id 计入 failed_nodes（级联跳过）。
2. **全局判定**：以当前 failed_nodes 为禁行集合，判断「START → END 是否存在不经过 failed 节点的路径」：
   - 不存在 → 本节点同样返回 `SKIPPED`（整体已注定失败，剩余节点全部空转跳过）；
   - 存在 → 正常执行。

**图的静态信息注入**：`_build_workflow` 构造节点时把 `graph_context`（edges 列表 + END 节点 id + 是否子图）注入节点（`PrivateAttr`），供前置检查使用（邻接表预计算一次）。

**结果汇总（服务层）**：流式结束后：
- 若 END 节点结果为 FAILED，或 failed_nodes 中存在使 END 不可达的失败 → 整体失败；
- 否则整体成功（可含部分分支失败，`partial_failed` 标记）。

### 3. SSE 协议（向后兼容）

- 每个 `event: workflow` 事件顶层增加 `node_id`（= node_data.id），status 透传（succeeded/failed/skipped）。
- 新增 `event: summary`（流末尾）：`{status: "succeeded"|"partial_failed"|"failed", failed_node_ids, skipped_node_ids, node_count, latency}`。
- `event: error` 保留：仅全局失败时发送，`error_node_id` 直接取真实失败节点 id（不再解析 LangGraph traceback）。
- 删除/弱化 traceback 正则解析逻辑（保留字段但优先用真实节点 id）。

### 4. 顺带修复

`internal/core/workflow/workflow.py` 174-175 行：`graph.set_entry_point(end_node)` → `graph.set_finish_point(end_node)`（避免 END 在启动时先执行一次）。

## 前端设计

### 1. 调试入口（DetailView.vue）

- 工具栏新增「调试选中节点」按钮：`selectedNodes`（Vue Flow 多选）非空时可点，点击打开 DebugModal 并携带 `node_ids`。
- 节点右键菜单新增「调试该节点」。
- 原「调试整个工作流」保留（不携带 node_ids）。

### 2. 画布节点状态可视化

- 新增 `nodeStatusMap: ref<Record<string, "running"|"succeeded"|"failed"|"skipped">>`；
- SSE 事件到达即更新对应节点（哪个节点完成立刻显示）；
- 复用 `node.class → .vue-flow__node` 机制，纯 CSS 实现（不改 8 个节点组件）：
  - `.node-status-succeeded::after` → 右上角绿色 ✓ 徽标；
  - `.node-status-failed` → 红框（复用现有 `node-has-error` 脉冲样式，统一为 status 体系）；
  - `.node-status-skipped` → 灰色标记；
  - `.node-status-running` → 蓝色描边。
- 每次运行前清除全部状态（现有 `clearNodeErrors` 扩展为 `clearNodeStatuses`）；关闭调试时同样清除。

### 3. DebugModal.vue

- 事件解析补 `node_id`；
- 节点级调试时：结果面板展示选中节点（合成 END「调试输出」）的 outputs；节点列表展示每个节点状态；
- 部分失败展示：失败/跳过节点列表 + 整体文案「运行成功（部分分支失败）/ 运行失败」；
- `use-workflow.ts` / `services/workflow.ts`：`debugWorkflow` 支持 `node_ids`，事件回调增加 node_id/status/summary 解析。

## 测试策略

- 后端单测（不依赖 Flask 的 seam：`subgraph.py` 纯函数 + `BaseNode` 包装逻辑）：
  1. 上游闭包计算（含多选、跨层传递前驱）；
  2. 合成 END 构建（单目标/多目标）；
  3. 并行分支一坏一好 → 整体成功（partial_failed），好分支照常输出；
  4. 唯一路径失败 → 全局失败，后续节点全部 SKIPPED；
  5. 级联跳过（下游 REF 上游失败节点）。
- 前端：`pnpm build` 类型+构建校验；本地 5173 手工联调。
- 全链路验收：用含 google_serper 失效节点的工作流验证——节点级调试其它节点可运行；整图调试时该节点红框报错且不阻塞其他分支调试。

## 分支与交付

- 分支：`release_20260827`（已从 release_20260826 创建）；
- 完成后提交并 push 到 origin；
- 交付物：后端（subgraph.py、BaseNode 包装、workflow.py、workflow_service.py、workflow_handler.py、node_entity.py、workflow_entity.py、helper.py）+ 前端（DetailView.vue、DebugModal.vue、use-workflow.ts、services/workflow.ts）+ 单测 + 本设计文档。

## 风险与注意

- LangGraph 同一 superstep 内并行节点的 failed_nodes 合并依赖 reducer（累加），跨 superstep 可见，语义正确；
- 跳过节点的 `SKIPPED` 结果也会进入 `node_results`（前端据此渲染灰色），不影响 outputs；
- 合成 END 只用于调试，不写入数据库 graph/draft_graph；
- 节点级调试仍会创建 `WorkflowResult` 记录（graph=子图配置），便于追溯。
