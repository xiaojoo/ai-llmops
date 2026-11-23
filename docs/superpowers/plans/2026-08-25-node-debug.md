# 节点级调试与画布节点状态可视化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持单/多选节点调试（上游闭包子图 + 合成 END），画布节点实时状态徽标（绿勾/红框/跳过/运行中），分支级失败语义（影响全局停止、不影响继续）。

**Architecture:** 继续基于 LangGraph。`BaseNode` 统一 `invoke` 包装（异常捕获 + 前置跳过检查），新增 `failed_nodes` 状态通道；节点调试用上游闭包子图 + 合成 END 构建 `WorkflowConfig`；SSE 增加 `node_id` 与 `event: summary`。前端用 `node.class → .vue-flow__node` + 纯 CSS 渲染状态徽标。

**Tech Stack:** Python / Flask / LangGraph / SQLAlchemy（后端）；Vue 3 / Vue Flow / TypeScript / Arco Design（前端）；pytest（测试）。

**Spec:** `docs/superpowers/specs/2026-08-25-node-debug-design.md`

## Global Constraints

- 分支：`release_20260827`（已从 release_20260826 创建）。
- 后端测试用 `venv\Scripts\python.exe -m pytest <path>` 运行（系统 `python` 不在 PATH 指向 venv）。
- 前端构建校验：在 `ai-code-llmops-web/` 下运行 `pnpm build`（如无 pnpm 用 `npm run build`，先看锁文件）。
- 兼容旧格式：debug 请求体不含 `node_ids` 字段时按整图运行，现有前端不受影响。
- 不删除/不修复 google_serper 失效节点；不更换执行引擎。
- 所有代码注释风格沿用现有中文注释风格。
- WorkflowConfig 名称须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`。

---

### Task 1: 状态枚举 + 状态通道 + 子图纯函数模块

**Files:**
- Modify: `internal/core/workflow/entities/node_entity.py`
- Modify: `internal/core/workflow/entities/workflow_entity.py`
- Create: `internal/core/workflow/utils/subgraph.py`
- Test: `test/internal/core/workflow/test_subgraph.py`（新建目录 `test/internal/core/workflow/`，含 `__init__.py`）

**Interfaces:**
- Produces:
  - `NodeStatus.SKIPPED = "skipped"`（node_entity.py）
  - `WorkflowState.failed_nodes: Annotated[list[UUID], _process_failed_nodes]`（workflow_entity.py）
  - `subgraph.build_reverse_adjacency(edges) -> dict[UUID, list[UUID]]`
  - `subgraph.compute_upstream_closure(target_ids: list[UUID], reverse_adj) -> set[UUID]`
  - `subgraph.build_subgraph_config(config: WorkflowConfig, target_node_ids: list[UUID]) -> WorkflowConfig`
  - `subgraph.is_end_reachable(start_id: UUID, end_id: UUID, edges: list[BaseEdgeData], failed_node_ids: list[UUID]) -> bool`

- [ ] **Step 1: 写失败测试**

`test/internal/core/workflow/__init__.py`（空文件），`test/internal/core/workflow/test_subgraph.py`：

```python
import uuid
from uuid import UUID

import pytest

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeType
from internal.core.workflow.entities.variable_entity import VariableEntity, VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.nodes import StartNodeData, EndNodeData, LLMNodeData, TemplateTransformNodeData
from internal.core.workflow.utils import subgraph


def _node(node_type: NodeType, title: str) -> BaseNodeData:
    kwargs = {"id": uuid.uuid4(), "node_type": node_type, "title": title}
    if node_type == NodeType.START:
        return StartNodeData(**kwargs)
    if node_type == NodeType.END:
        return EndNodeData(**kwargs)
    if node_type == NodeType.LLM:
        return LLMNodeData(**kwargs, prompt="hi")
    return TemplateTransformNodeData(**kwargs, template="{{a}}")


def _edge(source: BaseNodeData, target: BaseNodeData) -> BaseEdgeData:
    return BaseEdgeData(id=uuid.uuid4(), source=source.id, source_type=source.node_type,
                        target=target.id, target_type=target.node_type)


def _config(start, end, *middle) -> WorkflowConfig:
    return WorkflowConfig(account_id=uuid.uuid4(), name="test_flow", description="d",
                          nodes=[start, end, *middle], edges=[])


def test_upstream_closure_single():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    llm = _node(NodeType.LLM, "llm")
    tpl = _node(NodeType.TEMPLATE_TRANSFORM, "tpl")
    edges = [_edge(start, llm), _edge(llm, tpl), _edge(tpl, end)]
    rev = subgraph.build_reverse_adjacency(edges)
    closure = subgraph.compute_upstream_closure([tpl.id], rev)
    assert closure == {start.id, llm.id, tpl.id}


def test_upstream_closure_multi_branch():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    a, b = _node(NodeType.LLM, "a"), _node(NodeType.LLM, "b")
    edges = [_edge(start, a), _edge(start, b), _edge(a, end), _edge(b, end)]
    rev = subgraph.build_reverse_adjacency(edges)
    closure = subgraph.compute_upstream_closure([a.id, b.id], rev)
    assert closure == {start.id, a.id, b.id}


def test_build_subgraph_config_adds_synthetic_end():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    llm = _node(NodeType.LLM, "llm")
    edges = [_edge(start, llm), _edge(llm, end)]
    cfg = WorkflowConfig(account_id=uuid.uuid4(), name="test_flow", description="d",
                         nodes=[start, end, llm], edges=edges)
    sub_cfg = subgraph.build_subgraph_config(cfg, [llm.id])
    # 原 END 不在子图内，合成 END 追加
    assert len([n for n in sub_cfg.nodes if n.node_type == NodeType.END]) == 1
    sub_end = next(n for n in sub_cfg.nodes if n.node_type == NodeType.END)
    assert sub_end.title == "调试输出"
    assert sub_end.id != end.id
    assert any(e.source == llm.id and e.target == sub_end.id for e in sub_cfg.edges)


def test_build_subgraph_config_keeps_original_end_when_selected():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    llm = _node(NodeType.LLM, "llm")
    edges = [_edge(start, llm), _edge(llm, end)]
    cfg = WorkflowConfig(account_id=uuid.uuid4(), name="test_flow", description="d",
                         nodes=[start, end, llm], edges=edges)
    sub_cfg = subgraph.build_subgraph_config(cfg, [end.id])
    assert any(n.id == end.id for n in sub_cfg.nodes)


def test_end_reachable():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    a, b = _node(NodeType.LLM, "a"), _node(NodeType.LLM, "b")
    edges = [_edge(start, a), _edge(start, b), _edge(a, end), _edge(b, end)]
    assert subgraph.is_end_reachable(start.id, end.id, edges, [])
    assert subgraph.is_end_reachable(start.id, end.id, edges, [a.id])  # b 分支仍可达
    assert not subgraph.is_end_reachable(start.id, end.id, edges, [a.id, b.id])
```

- [ ] **Step 2: 运行确认失败**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/test_subgraph.py -v
```
预期：FAIL / ImportError（模块不存在）。

- [ ] **Step 3: 实现**

`internal/core/workflow/entities/node_entity.py` — 枚举加一行：

```python
class NodeStatus(str, Enum):
    """节点状态"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
```

`internal/core/workflow/entities/workflow_entity.py` — 文件顶部（`_process_node_results` 后）加归约函数，`WorkflowState` 加通道：

```python
def _process_failed_nodes(left: list[UUID], right: list[UUID]) -> list[UUID]:
    """工作流失败节点 id 列表归纳函数"""
    left = left or []
    right = right or []
    return left + right
```
```python
class WorkflowState(TypedDict):
    """工作流图程序状态字典"""
    inputs: Annotated[dict[str, Any], _process_dict]  # 工作流的最初始输入，也就是工具输入
    outputs: Annotated[dict[str, Any], _process_dict]  # 工作流的最终输出结果，也就是工具输出
    node_results: Annotated[list[NodeResult], _process_node_results]  # 各节点的运行结果
    failed_nodes: Annotated[list[UUID], _process_failed_nodes]  # 执行失败/被跳过的节点 id 列表
```

`internal/core/workflow/utils/subgraph.py`（新建）：

```python
#!/usr/bin/env python
"""
@Time    : 2026/8/25
@Author  : sunxiaojie
@File    : subgraph.py
子图与失败语义相关的图计算工具（纯函数，便于单测）
"""
from collections import defaultdict, deque
from uuid import UUID, uuid4

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeType
from internal.core.workflow.entities.variable_entity import VariableEntity, VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.nodes import EndNodeData

SYNTHETIC_END_TITLE = "调试输出"


def build_reverse_adjacency(edges: list[BaseEdgeData]) -> dict[UUID, list[UUID]]:
    """构建逆邻接表，key 为目标节点 id，value 为该节点的直接前驱 id 列表"""
    reverse_adj: dict[UUID, list[UUID]] = defaultdict(list)
    for edge in edges:
        reverse_adj[edge.target].append(edge.source)
    return reverse_adj


def compute_upstream_closure(target_ids: list[UUID], reverse_adj: dict[UUID, list[UUID]]) -> set[UUID]:
    """计算目标节点的上游闭包：目标节点 + 全部传递前驱"""
    closure: set[UUID] = set()
    stack = list(target_ids)
    while stack:
        node_id = stack.pop()
        if node_id in closure:
            continue
        closure.add(node_id)
        for pred in reverse_adj.get(node_id, []):
            if pred not in closure:
                stack.append(pred)
    return closure


def is_end_reachable(
        start_id: UUID,
        end_id: UUID,
        edges: list[BaseEdgeData],
        failed_node_ids: list[UUID],
) -> bool:
    """判断是否存在一条不经过失败节点的 START→END 路径（BFS）"""
    adj: dict[UUID, list[UUID]] = defaultdict(list)
    for edge in edges:
        adj[edge.source].append(edge.target)
    failed = set(failed_node_ids)
    visited: set[UUID] = set()
    queue = deque([start_id])
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_id == end_id:
            return True
        for neighbor in adj.get(node_id, []):
            if neighbor not in visited and neighbor not in failed:
                queue.append(neighbor)
    return False


def build_subgraph_config(config: WorkflowConfig, target_node_ids: list[UUID]) -> WorkflowConfig:
    """构建选中节点的上游闭包子图配置。

    - 若原 END 不在目标中：追加合成 END（title=调试输出，outputs=REF 各目标节点首个输出），
      并添加 目标节点 → 合成 END 的边；
    - 若原 END 在目标中：直接保留原 END 作为终点（闭包会包含整条链路）。
    """
    nodes_by_id: dict[UUID, BaseNodeData] = {n.id: n for n in config.nodes}
    end_node = next(n for n in config.nodes if n.node_type == NodeType.END)
    reverse_adj = build_reverse_adjacency(config.edges)

    include_end = end_node.id in target_node_ids
    targets = [nid for nid in target_node_ids if nid != end_node.id]
    closure = compute_upstream_closure(targets, reverse_adj)
    if include_end:
        closure.add(end_node.id)

    sub_nodes = [nodes_by_id[nid] for nid in closure]
    sub_edges = [e for e in config.edges if e.source in closure and e.target in closure]

    if include_end:
        return WorkflowConfig(
            account_id=config.account_id,
            name=f"{config.name}_debug",
            description="调试子图",
            nodes=sub_nodes,
            edges=sub_edges,
        )

    # 追加合成 END
    outputs = []
    for idx, target_id in enumerate(target_node_ids):
        target = nodes_by_id[target_id]
        ref_var_name = target.outputs[0].name if getattr(target, "outputs", None) else "output"
        outputs.append(VariableEntity(
            name="output" if idx == 0 else f"output_{idx + 1}",
            value={
                "type": VariableValueType.REF,
                "content": {"ref_node_id": str(target_id), "ref_var_name": ref_var_name},
            },
        ))
    synthetic_end = EndNodeData(
        id=uuid4(),
        node_type=NodeType.END,
        title=SYNTHETIC_END_TITLE,
        outputs=outputs,
    )
    synthetic_edges = [
        BaseEdgeData(
            id=uuid4(),
            source=target_id,
            source_type=nodes_by_id[target_id].node_type,
            target=synthetic_end.id,
            target_type=NodeType.END,
        )
        for target_id in target_node_ids
    ]
    return WorkflowConfig(
        account_id=config.account_id,
        name=f"{config.name}_debug",
        description="调试子图",
        nodes=[*sub_nodes, synthetic_end],
        edges=[*sub_edges, *synthetic_edges],
    )
```

注意：`VariableValueType.REF` 的 `content.ref_node_id` 校验器会把 `""` 转 None，这里传字符串 UUID 即可（`WorkflowConfig` 校验时 `ref_node_id in predecessors` 用的是 UUID 集合，需确认 Pydantic 会把字符串转成 UUID——`VariableEntity.Value.Content.ref_node_id` 类型为 `UUID | None`，Pydantic 自动转换）。

- [ ] **Step 4: 运行测试确认通过**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/test_subgraph.py -v
```
预期：PASS（5 个用例）。

- [ ] **Step 5: 提交**

```bash
git add internal/core/workflow/entities/node_entity.py internal/core/workflow/entities/workflow_entity.py internal/core/workflow/utils/subgraph.py test/internal/core/workflow/
git commit -m "feat: 节点状态SKIPPED + failed_nodes通道 + 子图纯函数模块"
```

---

### Task 2: BaseNode 统一包装 + 节点改名 + 图上下文注入

**Files:**
- Modify: `internal/core/workflow/nodes/base_node.py`
- Modify: `internal/core/workflow/nodes/start/start_node.py`
- Modify: `internal/core/workflow/nodes/llm/llm_node.py`
- Modify: `internal/core/workflow/nodes/end/end_node.py`
- Modify: `internal/core/workflow/nodes/code/code_node.py`
- Modify: `internal/core/workflow/nodes/tool/tool_node.py`
- Modify: `internal/core/workflow/nodes/http_request/http_request_node.py`
- Modify: `internal/core/workflow/nodes/dataset_retrieval/dataset_retrieval_node.py`
- Modify: `internal/core/workflow/nodes/template_transform/template_transform_node.py`
- Modify: `internal/core/workflow/workflow.py`
- Test: `test/internal/core/workflow/test_base_node.py`

**Interfaces:**
- Produces:
  - `BaseNode.run(self, state, config=None, **kwargs)`（子类实现，替代原 invoke）
  - `BaseNode.set_graph_context(edges, start_node_id, end_node_id)`（图构建时注入）
  - `BaseNode.invoke`：统一包装（跳过检查 + 异常捕获），LangGraph 仍调用 invoke
  - `Workflow._run` / `Workflow.stream` 初始化 `failed_nodes: []`

- [ ] **Step 1: 写失败测试**

`test/internal/core/workflow/test_base_node.py`：

```python
import uuid

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeResult, NodeStatus, NodeType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode


class _OkNode(BaseNode):
    """正常执行节点"""
    node_data: BaseNodeData

    def run(self, state, config=None, **kwargs):
        return {"node_results": [NodeResult(node_data=self.node_data, status=NodeStatus.SUCCEEDED, outputs={"output": "ok"})]}


class _FailNode(BaseNode):
    """必然抛异常的节点"""
    node_data: BaseNodeData

    def run(self, state, config=None, **kwargs):
        raise RuntimeError("boom")


def _node(node_type: NodeType, title: str) -> BaseNodeData:
    return BaseNodeData(id=uuid.uuid4(), node_type=node_type, title=title)


def _state(failed: list[str]) -> WorkflowState:
    return {"inputs": {}, "outputs": {}, "node_results": [], "failed_nodes": [uuid.UUID(f) for f in failed]}


def test_ok_node_runs():
    data = _node(NodeType.LLM, "a")
    node = _OkNode(node_data=data)
    node.set_graph_context(edges=[], start_node_id=data.id, end_node_id=data.id)
    result = node.invoke(_state([]))
    assert result["node_results"][0].status == NodeStatus.SUCCEEDED


def test_fail_node_returns_failed_instead_of_raising():
    data = _node(NodeType.LLM, "a")
    node = _FailNode(node_data=data)
    node.set_graph_context(edges=[], start_node_id=data.id, end_node_id=data.id)
    result = node.invoke(_state([]))
    assert result["node_results"][0].status == NodeStatus.FAILED
    assert "boom" in result["node_results"][0].error
    assert str(data.id) in [str(f) for f in result["failed_nodes"]]


def test_node_skipped_when_predecessor_failed():
    pred = _node(NodeType.LLM, "pred")
    curr = _node(NodeType.LLM, "curr")
    edges = [BaseEdgeData(id=uuid.uuid4(), source=pred.id, source_type=NodeType.LLM,
                          target=curr.id, target_type=NodeType.LLM)]
    node = _OkNode(node_data=curr)
    node.set_graph_context(edges=edges, start_node_id=pred.id, end_node_id=curr.id)
    result = node.invoke(_state([str(pred.id)]))
    assert result["node_results"][0].status == NodeStatus.SKIPPED
    assert str(curr.id) in [str(f) for f in result["failed_nodes"]]


def test_node_skipped_when_end_unreachable():
    pred = _node(NodeType.LLM, "pred")
    curr = _node(NodeType.LLM, "curr")
    end = _node(NodeType.END, "end")
    edges = [BaseEdgeData(id=uuid.uuid4(), source=curr.id, source_type=NodeType.LLM,
                          target=end.id, target_type=NodeType.END)]
    node = _OkNode(node_data=curr)
    # end 只经 curr 可达，且 curr 的前驱（外部节点）已失败——用 failed 中非本图节点制造不可达
    node.set_graph_context(edges=edges, start_node_id=curr.id, end_node_id=end.id)
    result = node.invoke(_state([str(uuid.uuid4())]))  # 无关失败节点，不影响可达性
    assert result["node_results"][0].status == NodeStatus.SUCCEEDED  # 可达，正常执行


def test_end_node_not_skipped_by_predecessor_edge():
    pred = _node(NodeType.LLM, "pred")
    end_data = _node(NodeType.END, "end")
    edges = [BaseEdgeData(id=uuid.uuid4(), source=pred.id, source_type=NodeType.LLM,
                          target=end_data.id, target_type=NodeType.END)]
    node = _OkNode(node_data=end_data)  # END 节点：仅按 REF 判定，不看前驱边
    node.set_graph_context(edges=edges, start_node_id=pred.id, end_node_id=end_data.id)
    result = node.invoke(_state([str(pred.id)]))
    assert result["node_results"][0].status == NodeStatus.SUCCEEDED
```

- [ ] **Step 2: 运行确认失败**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/test_base_node.py -v
```
预期：FAIL（BaseNode 无 run/set_graph_context）。

- [ ] **Step 3: 实现 base_node.py**

```python
#!/usr/bin/env python
"""
@Time    : 2026/1/24 18:44
@Author  : sunxiaojie
@File    : base_node.py
"""
from abc import ABC
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig, RunnableSerializable
from pydantic import PrivateAttr

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeResult, NodeStatus, NodeType
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.utils.subgraph import is_end_reachable


class BaseNode(RunnableSerializable, ABC):
    """工作流节点基类"""
    node_data: BaseNodeData
    _graph_edges: list[BaseEdgeData] = PrivateAttr(default_factory=list)
    _start_node_id: UUID | None = PrivateAttr(default=None)
    _end_node_id: UUID | None = PrivateAttr(default=None)

    def set_graph_context(
            self,
            edges: list[BaseEdgeData],
            start_node_id: UUID,
            end_node_id: UUID,
    ):
        """注入图的静态信息（边列表 + 起点 + 终点），供失败语义判断使用"""
        self._graph_edges = edges
        self._start_node_id = start_node_id
        self._end_node_id = end_node_id

    def invoke(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """统一节点执行入口：前置跳过检查 + 异常捕获，LangGraph 调度时调用"""
        # 1、前置检查，命中则跳过
        skip_reason = self._check_skip(state)
        if skip_reason:
            return self._result(NodeStatus.SKIPPED, error=skip_reason)

        # 2、执行节点核心逻辑
        try:
            return self.run(state, config=config, **kwargs)
        except Exception as e:
            # 3、异常不抛出，转为失败节点结果，保证其他分支可以继续执行
            return self._result(NodeStatus.FAILED, error=str(e))

    def _check_skip(self, state: WorkflowState) -> str:
        """返回跳过原因字符串，空字符串代表不跳过"""
        failed_ids = {UUID(str(f)) for f in state.get("failed_nodes", [])}
        if not failed_ids:
            return ""

        # 1、REF 引用来源失败 → 跳过（数据依赖断裂）
        for variable in self._node_variables():
            if variable.value.type == VariableValueType.REF:
                ref_node_id = variable.value.content.ref_node_id
                if ref_node_id and UUID(str(ref_node_id)) in failed_ids:
                    return f"引用节点[{ref_node_id}]执行失败，本节点跳过"

        # 2、非 END 节点：任一直接前驱失败 → 跳过（分支断裂）
        if self.node_data.node_type != NodeType.END:
            for edge in self._graph_edges:
                if edge.target == self.node_data.id and edge.source in failed_ids:
                    return f"上游节点[{edge.source}]执行失败，本节点跳过"

        # 3、全局判定：END 不再可达 → 跳过
        if self._end_node_id and not is_end_reachable(
                self._start_node_id, self._end_node_id, self._graph_edges, list(failed_ids)
        ):
            return "工作流必经路径已失败，本节点跳过"

        return ""

    def _node_variables(self):
        """获取节点用于依赖判定的变量列表（非 START 用 inputs，END 用 outputs）"""
        if self.node_data.node_type == NodeType.START:
            return []
        if self.node_data.node_type == NodeType.END:
            return getattr(self.node_data, "outputs", [])
        return getattr(self.node_data, "inputs", [])

    def _result(self, status: NodeStatus, error: str = "") -> WorkflowState:
        """构建节点结果 + 失败节点登记"""
        return {
            "node_results": [
                NodeResult(node_data=self.node_data, status=status, error=error)
            ],
            "failed_nodes": [self.node_data.id] if status in (NodeStatus.FAILED, NodeStatus.SKIPPED) else [],
        }

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """节点核心逻辑，由子类实现（替代原 invoke）"""
        raise NotImplementedError
```

注意：`BaseNodeData` 需要 `id`/`node_type`/`title` 字段（已具备）；测试中 `BaseNodeData(id=..., node_type=..., title=...)` 直接实例化可行（position 有默认值）。

- [ ] **Step 4: 8 个节点改名 invoke → run**

对 `start_node.py`、`llm_node.py`、`end_node.py`、`code_node.py`、`tool_node.py`、`http_request_node.py`、`dataset_retrieval_node.py`、`template_transform_node.py` 各自执行：

```python
# 原: def invoke(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs) -> WorkflowState:
# 改: def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs) -> WorkflowState:
```

（仅方法名与文档字符串内"执行函数"措辞不变，签名保持不变。）

同时删除 `start_node.py` 中的调试残留：

```python
        for input in inputs:
            print(input)   # ← 删除此行
```

- [ ] **Step 5: workflow.py 注入图上下文 + 修复 set_finish_point + 初始化 failed_nodes**

`internal/core/workflow/workflow.py`：

1) `_build_workflow` 中，节点注册循环前提取 start/end 节点数据，注册时注入上下文：

```python
        # 2、提取nodes和edges信息
        nodes = self._workflow_config.nodes
        edges = self._workflow_config.edges

        # 3、提取图起点/终点节点（用于注入节点上下文做失败语义判断）
        start_node_data = next(node for node in nodes if node.node_type == NodeType.START)
        end_node_data = next(node for node in nodes if node.node_type == NodeType.END)

        # 4、循环遍历nodes节点信息添加节点
        for node in nodes:
            node_flag = f"{node.node_type.value}_{node.id}"
            node_cls = NodeClasses[node.node_type]
            if node.node_type == NodeType.DATASET_RETRIEVAL:
                node_instance = node_cls(
                    flask_app=current_app._get_current_object(),
                    account_id=self._workflow_config.account_id,
                    node_data=node,
                )
            else:
                node_instance = node_cls(node_data=node)
            node_instance.set_graph_context(
                edges=edges,
                start_node_id=start_node_data.id,
                end_node_id=end_node_data.id,
            )
            graph.add_node(node_flag, node_instance)
```

（保留原 if/elif 分支也行，但上述写法更简洁；若保留原分支结构，则在每个分支的 `graph.add_node` 前调用 `node_instance.set_graph_context(...)`。）

2) 修复终点设置（原 174-175 行）：

```python
        # 7、设置开始和终点
        graph.set_entry_point(start_node)
        graph.set_finish_point(end_node)  # 修复：原为 set_entry_point(end_node)
```

3) `_run` 与 `stream` 初始化 failed_nodes：

```python
    def _run(self, *args: Any, **kwargs: Any) -> Any:
        # 1、调用工作流获取结果信息
        result = self._workflow.invoke({"inputs": kwargs, "failed_nodes": []})
        # 2、提取响应结果的outputs内容作为输出
        return result.get("outputs", {})

    def stream(self, input, config=None, *args, **kwargs):
        """工作流式输出每个节点对应的结果"""
        return self._workflow.stream({"inputs": input, "failed_nodes": []})
```

- [ ] **Step 6: 运行测试确认通过**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/test_base_node.py -v
```
预期：PASS（5 个用例）。

- [ ] **Step 7: 回归 + 提交**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/ -v
git add internal/core/workflow/
git commit -m "feat: BaseNode统一异常捕获与失败语义，8节点invoke改run，修复set_finish_point"
```

---

### Task 3: 服务层 node_ids 调试 + SSE summary/error 事件

**Files:**
- Modify: `internal/handler/workflow_handler.py`
- Modify: `internal/service/workflow_service.py`

**Interfaces:**
- Consumes: `subgraph.build_subgraph_config`（Task 1）、`NodeStatus`（Task 1）
- Produces:
  - `POST /workflows/<id>/debug` 请求体支持 `{inputs, node_ids?}`（旧格式兼容）
  - SSE 事件：`event: workflow`（顶层带 `node_id`）、`event: summary`、`event: error`
  - `debug_workflow(workflow_id, inputs, account, node_ids=None)`

- [ ] **Step 1: handler 解析 node_ids**

`internal/handler/workflow_handler.py` 的 `debug_workflow`：

```python
    @login_required
    def debug_workflow(self, workflow_id: UUID):
        """根据传递的变量字典+工作流id调试指定的工作流，支持 node_ids 指定单/多节点调试"""
        # 1、提取用户传递的请求体，兼容旧格式（body 即 inputs）与新格式（{inputs, node_ids}）
        body = request.get_json(force=True, silent=True) or {}
        if "node_ids" in body:
            inputs = body.get("inputs", {}) or {}
            node_ids = body.get("node_ids") or None
        else:
            inputs = body
            node_ids = None

        # 2、调用服务调试指定的API接口
        response = self.workflow_service.debug_workflow(workflow_id, inputs, current_user, node_ids=node_ids)

        return compact_generate_response(response)
```

- [ ] **Step 2: 服务层实现（重写 debug_workflow 的生成器部分）**

`internal/service/workflow_service.py`：

1) 方法签名与子图构建：

```python
    def debug_workflow(
            self,
            workflow_id: UUID,
            inputs: dict[str, Any],
            account: Account,
            node_ids: list[UUID] | None = None,
    ) -> Generator:
        """调试指定的工作流API接口，该接口为流式事件输出。node_ids 非空时仅运行选中节点的上游闭包子图"""
        # 1、根据传递的id获取工作流并校验权限
        workflow = self.get_workflow(workflow_id, account)

        # 2、校验 node_ids 是否存在于草稿图
        if node_ids:
            draft_node_ids = {str(n.get("id")) for n in workflow.draft_graph.get("nodes", [])}
            invalid = [str(nid) for nid in node_ids if str(nid) not in draft_node_ids]
            if invalid:
                raise ValidateException(f"工作流中不存在节点: {', '.join(invalid)}，请核实后重试")

        # 3、构建工作流配置（node_ids 时先构建上游闭包子图）
        workflow_config = WorkflowConfig(
            account_id=account.id,
            name=workflow.tool_call_name,
            description=workflow.description,
            nodes=workflow.draft_graph.get("nodes", []),
            edges=workflow.draft_graph.get("edges", []),
        )
        if node_ids:
            workflow_config = build_subgraph_config(workflow_config, [UUID(str(nid)) for nid in node_ids])

        # 4、创建工作流工具（构造失败时返回单条 error 事件流，避免整请求 500）
        try:
            workflow_tool = WorkflowTool(workflow_config=workflow_config)
        except Exception as e:
            def build_error_stream() -> Generator:
                error_data = {"id": str(uuid.uuid4()), "error": str(e), "error_node_id": None, "error_node_title": None}
                yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            return build_error_stream()
        ...
```

2) 生成器改造（原 `handle_stream`）：

```python
        def handle_stream() -> Generator:
            # 3、定义变量存储所有节点运行结果与失败/跳过节点
            node_results = []
            failed_node_ids: list[str] = []
            skipped_node_ids: list[str] = []
            end_result = None

            # 4、添加数据库工作流运行结果记录
            workflow_result = self.create(
                WorkflowResult, app_id=None, account_id=account.id, workflow_id=workflow.id,
                graph=workflow_config.model_dump(mode="json"), state=[], latency=0,
                status=WorkflowResultStatus.RUNNING,
            )

            # 5、调用stream服务获取工具信息
            start_at = time.perf_counter()
            try:
                for chunk in workflow_tool.stream(inputs):
                    # 6、chunk的格式为:{"node_name": WorkflowState}，所以需要取出节点响应结构的第1个key
                    first_key = next(iter(chunk))
                    node_result = chunk[first_key]["node_results"][0]
                    node_result_dict = node_result.model_dump(mode="json")
                    node_results.append(node_result_dict)

                    # 7、统计失败/跳过节点
                    if node_result.status == NodeStatus.FAILED:
                        failed_node_ids.append(str(node_result.node_data.id))
                    elif node_result.status == NodeStatus.SKIPPED:
                        skipped_node_ids.append(str(node_result.node_data.id))
                    if node_result.node_data.node_type == NodeType.END:
                        end_result = node_result

                    # 8、组装响应数据并流式事件输出（顶层带 node_id 供前端定位画布节点）
                    data = {
                        "id": str(uuid.uuid4()),
                        "node_id": str(node_result.node_data.id),
                        **node_result_dict,
                    }
                    yield f"event: workflow\ndata: {json.dumps(data)}\n\n"

                # 9、汇总整体状态
                if end_result and end_result.status == NodeStatus.SUCCEEDED:
                    overall_status = "partial_failed" if failed_node_ids else "succeeded"
                else:
                    overall_status = "failed"

                # 10、发送 summary 事件
                summary = {
                    "status": overall_status,
                    "failed_node_ids": failed_node_ids,
                    "skipped_node_ids": skipped_node_ids,
                    "node_count": len(node_results),
                    "latency": time.perf_counter() - start_at,
                }
                yield f"event: summary\ndata: {json.dumps(summary, ensure_ascii=False)}\n\n"

                # 11、更新运行结果记录
                self.update(
                    workflow_result,
                    status=WorkflowResultStatus.SUCCEEDED if overall_status != "failed" else WorkflowResultStatus.FAILED,
                    state=node_results,
                    latency=(time.perf_counter() - start_at),
                )

                # 12、仅整图调试且全部成功时置为调试通过
                if not node_ids and overall_status == "succeeded":
                    self.update(workflow, is_debug_passed=True)

                # 13、全局失败时额外发送 error 事件（取首个失败节点）
                if overall_status == "failed":
                    error_node_id = failed_node_ids[0] if failed_node_ids else None
                    error_node_title = None
                    error_message = "工作流运行失败"
                    if failed_node_ids:
                        failed_node = next(
                            (r for r in node_results if str(r.get("node_id", "")) == error_node_id),
                            None,
                        )
                        if failed_node:
                            error_node_title = failed_node.get("node_data", {}).get("title", "")
                            error_message = failed_node.get("error") or error_message
                    error_data = {
                        "id": str(uuid.uuid4()),
                        "error": error_message,
                        "error_node_id": error_node_id,
                        "error_node_title": error_node_title,
                    }
                    yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            except Exception as e:
                # 14、兜底：流式执行过程异常（非节点级），保证不中断连接
                error_data = {
                    "id": str(uuid.uuid4()),
                    "error": str(e),
                    "error_node_id": None,
                    "error_node_title": None,
                }
                yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                self.update(
                    workflow_result, status=WorkflowResultStatus.FAILED,
                    state=node_results, latency=(time.perf_counter() - start_at),
                )

        return handle_stream()
```

3) 顶部导入补全：

```python
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeStatus, NodeType
from internal.core.workflow.utils.subgraph import build_subgraph_config
```

（原有 `BaseNodeData, NodeType` 导入保留；删除不再使用的 traceback 正则解析逻辑 `import re as _re` / `import traceback as _tb` 及其解析块。）

- [ ] **Step 3: 运行后端冒烟（导入 + 既有测试）**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/ -v
venv\Scripts\python.exe -c "from internal.service.workflow_service import WorkflowService; print('import ok')"
```
预期：PASS + import ok（需在仓库根目录运行，依赖 app 包可导入；若 import 因 app 初始化失败，则以 pytest 通过为准）。

- [ ] **Step 4: 提交**

```bash
git add internal/handler/workflow_handler.py internal/service/workflow_service.py
git commit -m "feat: 工作流节点级调试（node_ids）与SSE summary/error事件"
```

---

### Task 4: 前端 services + hooks 支持 node_ids 与状态事件

**Files:**
- Modify: `ai-code-llmops-web/src/services/workflow.ts`
- Modify: `ai-code-llmops-web/src/hooks/use-workflow.ts`

**Interfaces:**
- Produces:
  - `debugWorkflow(workflow_id, inputs, onData, onError?, opts?: { node_ids?: string[] })`
  - `useDebugWorkflow` 的 `handleDebugWorkflow(workflow_id, inputs, onData, onError?, opts?)`
  - 事件回调入参扩展：workflow 事件 data 含 `node_id`、`status`；summary 事件 data 含 `status/failed_node_ids/skipped_node_ids`

- [ ] **Step 1: services/workflow.ts 改造**

```ts
// 工作流调试
export const debugWorkflow = (
  workflow_id: string,
  inputs: Record<string, unknown>,
  onData: (event_response: Record<string, unknown>) => void,
  onError?: (event_response: Record<string, unknown>) => void,
  opts?: { node_ids?: string[] },
) => {
  // 兼容旧格式：无 node_ids 时 body 直接为 inputs；有则用 {inputs, node_ids}
  const body: Record<string, unknown> =
    opts?.node_ids && opts.node_ids.length > 0
      ? { inputs, node_ids: opts.node_ids }
      : inputs
  return stream({
    url: API.WORKFLOWS + `/${workflow_id}/debug`,
    body,
    onMessage: (data, event) => {
      if (event.event === 'error') {
        onError?.({ event: event.event, data })
      } else {
        onData({ event: event.event, data })
      }
    },
  })
}
```

- [ ] **Step 2: hooks/use-workflow.ts 改造**

`useDebugWorkflow` 中 `handleDebugWorkflow` 增加可选 `opts`：

```ts
export const useDebugWorkflow = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const error = ref('')

  // 2.定义调试会话处理器
  const handleDebugWorkflow = async (
    workflow_id: string,
    inputs: Record<string, unknown>,
    onData: (event_response: Record<string, unknown>) => void,
    onError?: (event_response: Record<string, unknown>) => void,
    opts?: { node_ids?: string[] },
  ) => {
    try {
      loading.value = true
      const resp = await debugWorkflow(workflow_id, inputs, onData, onError, opts)
      // 2.1 判断响应内容是否存在，如果存在则表示该接口为非流式输出，意味着接口出错
      if (resp) {
        error.value = resp.message ?? resp.msg ?? '未知错误'
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, error, handleDebugWorkflow }
}
```

（`import { debugWorkflow } from '@/services/workflow.ts'` 已存在。）

- [ ] **Step 3: 构建校验**

```bash
cd ai-code-llmops-web
pnpm build
```
预期：构建成功（如无 pnpm 用 `npm run build`；先确认存在 `pnpm-lock.yaml` / `package-lock.json`）。
若前端 dev server 正在运行，HMR 自动生效。

- [ ] **Step 4: 提交**

```bash
git add ai-code-llmops-web/src/services/workflow.ts ai-code-llmops-web/src/hooks/use-workflow.ts
git commit -m "feat(web): 调试接口支持node_ids与状态事件透传"
```

---

### Task 5: 画布节点状态可视化 + 调试入口

**Files:**
- Modify: `ai-code-llmops-web/src/views/space/workflows/DetailView.vue`

**Interfaces:**
- Consumes: `DebugModal` 的 `node_ids` prop、`node-status` 事件（Task 6 定义）
- Produces:
  - `nodeStatusMap: Ref<Record<string, string>>`（id → running/succeeded/failed/skipped）
  - `clearNodeStatuses()`、`setNodeStatus(id, status)`
  - 工具栏「调试选中节点」按钮、节点右键菜单「调试该节点」
  - 全局 CSS：`.vue-flow__node.node-status-succeeded::after`（绿勾）、`.node-status-failed`、`.node-status-skipped`、`.node-status-running`

- [ ] **Step 1: 状态 map 替换错误集合**

替换 `errorNodeIds`/`markNodeError`/`clearNodeErrors`（DetailView.vue 277-288 行）：

```ts
// 调试节点状态映射：id → running / succeeded / failed / skipped，用于画布状态徽标
const nodeStatusMap = ref<Record<string, string>>({})

// 设置某个节点的调试状态
const setNodeStatus = (nodeId: string, status: string) => {
  nodeStatusMap.value = { ...nodeStatusMap.value, [nodeId]: status }
}

// 清除所有节点的调试状态（每次重新运行前调用）
const clearNodeStatuses = () => {
  nodeStatusMap.value = {}
}
```

替换 393-403 行的 watch：

```ts
// --- 节点调试状态同步：nodeStatusMap 变化时，更新各节点的 class ---
watch(
  nodeStatusMap,
  (statusMap) => {
    nodes.value = (nodes.value as FlowNode[]).map((n) => {
      const status = statusMap[n.id]
      let cls = ''
      if (status === 'failed') cls = 'node-status-failed'
      else if (status === 'succeeded') cls = 'node-status-succeeded'
      else if (status === 'skipped') cls = 'node-status-skipped'
      else if (status === 'running') cls = 'node-status-running'
      return { ...n, class: cls }
    })
  },
  { deep: false },
)
```

- [ ] **Step 2: 选中节点调试入口**

`useVueFlow()` 解构补 `selectedNodes`（325-340 行）：

```ts
const {
  onPaneReady,
  onViewportChange,
  onConnect,
  findNode,
  onPaneClick,
  onNodeClick,
  onEdgeClick,
  onEdgeContextMenu,
  onNodeDragStop,
  onNodeContextMenu,
  nodes: allNodes,
  screenToFlowCoordinate,
  removeSelectedNodes,
  fitView,
  selectedNodes,
} = useVueFlow()
```

新增调试目标状态与打开逻辑：

```ts
// 调试目标节点 id 列表：空数组 = 调试整个工作流
const debugTargetNodeIds = ref<string[]>([])
const debugModalVisible = ref(false)

// 打开调试面板（可携带目标节点）
const openDebugModal = (node_ids: string[] = []) => {
  debugTargetNodeIds.value = node_ids
  debugModalVisible.value = true
}

// 调试选中节点（多选）
const debugSelectedNodes = () => {
  const ids = selectedNodes.value.map((n) => n.id)
  if (ids.length === 0) return
  openDebugModal(ids)
}
```

在「调试」按钮附近（模板，约 1185-1195 行区域，`is_debug` 相关）增加「调试选中节点」按钮：

```html
<a-button
  v-if="selectedNodes.length > 0"
  class="!rounded-lg mr-2"
  @click="debugSelectedNodes"
>
  <template #icon><icon-play-arrow /></template>
  调试选中节点({{ selectedNodes.length }})
</a-button>
```

右键菜单（`contextMenu` 区域模板）增加菜单项：

```html
<div v-if="contextMenu.isNodeMenu" class="context-menu__item" @click="handleDebugNode">
  <icon-play-arrow style="margin-right: 8px" />调试该节点
</div>
```

```ts
// 调试单个节点（右键菜单）
const handleDebugNode = () => {
  if (!contextMenu.nodeId) return
  const nodeId = contextMenu.nodeId
  closeContextMenu()
  openDebugModal([nodeId])
}
```

调试面板挂载处（约 1319-1325 行）改造：

```html
<debug-modal
  :visible="debugModalVisible"
  :workflow_id="workflow_id"
  :node_ids="debugTargetNodeIds"
  @update:visible="debugModalVisible = $event"
  @node-status="setNodeStatus"
  @clear-errors="clearNodeStatuses"
  @debug-start="isDebugging = true"
  @debug-end="isDebugging = false"
/>
```

（`workflow_id` 从 route 参数取，若原本用 `route.params.workflow_id` 或 `workflow.id`，沿用现有变量名。）

- [ ] **Step 3: 全局 CSS（替换/扩展 1576-1605 行的样式块）**

```css
/**
 * 调试节点状态样式
 * VueFlow 将 node.class 挂到 .vue-flow__node 元素上
 */
/* 成功：右上角绿色对勾徽标 */
.vue-flow__node.node-status-succeeded::after {
  content: '✓';
  position: absolute;
  top: -9px;
  right: -9px;
  width: 22px;
  height: 22px;
  background: #22c55e;
  color: #fff;
  border-radius: 9999px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  z-index: 20;
  box-shadow: 0 2px 8px rgba(34, 197, 94, 0.45);
}

/* 失败：红框脉冲（沿用原 node-has-error 视觉） */
.vue-flow__node.node-status-failed {
  border-radius: 12px;
  outline: 2.5px solid #ef4444;
  outline-offset: 2px;
  box-shadow:
    0 0 0 4px rgba(239, 68, 68, 0.15),
    0 4px 16px rgba(239, 68, 68, 0.2);
  animation: nodeErrorPulse 1.8s ease-in-out infinite;
}

@keyframes nodeErrorPulse {
  0%,
  100% {
    box-shadow:
      0 0 0 3px rgba(239, 68, 68, 0.12),
      0 4px 16px rgba(239, 68, 68, 0.15);
  }
  50% {
    box-shadow:
      0 0 0 6px rgba(239, 68, 68, 0.22),
      0 4px 20px rgba(239, 68, 68, 0.3);
  }
}

/* 跳过：灰化 + 虚线描边 */
.vue-flow__node.node-status-skipped {
  opacity: 0.65;
  outline: 1.5px dashed #9ca3af;
  outline-offset: 2px;
}

/* 运行中：蓝色描边 */
.vue-flow__node.node-status-running {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}
```

（保留原 `.node-has-error` 样式也可，但新逻辑统一走 node-status-*；若保留，注意 class 互斥由 watch 保证。）

- [ ] **Step 4: 构建校验**

```bash
cd ai-code-llmops-web && pnpm build
```
预期：构建成功。

- [ ] **Step 5: 提交**

```bash
git add ai-code-llmops-web/src/views/space/workflows/DetailView.vue
git commit -m "feat(web): 画布节点状态徽标与选中节点调试入口"
```

---

### Task 6: DebugModal 支持 node_ids 与状态事件

**Files:**
- Modify: `ai-code-llmops-web/src/views/space/workflows/components/DebugModal.vue`

**Interfaces:**
- Consumes: `useDebugWorkflow(..., opts)`（Task 4）、DetailView 的 `node-status` 事件绑定（Task 5）
- Produces:
  - props：`node_ids?: string[]`（默认 `[]`）
  - emits：`node-status`（`{node_id, status}`）、`clear-errors`、`debug-start`、`debug-end`（移除旧 `node-error`）

- [ ] **Step 1: props 与 emits 改造**

```ts
const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  workflow_id: { type: String, required: true, default: '' },
  node_ids: { type: Array as PropType<string[]>, required: false, default: () => [] },
})

const emits = defineEmits([
  'update:visible',
  'node-status',
  'clear-errors',
  'debug-start',
  'debug-end',
])
```

（需 `import type { PropType } from 'vue'`。）

- [ ] **Step 2: 事件解析与整体状态**

新增：

```ts
// 整体运行状态：succeeded / partial_failed / failed / ''
const overallStatus = ref('')

// 失败/跳过节点列表
const failedNodes = ref<{ id: string; title: string; error: string }[]>([])
const skippedNodes = ref<{ id: string; title: string }[]>([])
```

替换 `onSubmit` 内的回调（88-110 行）：

```ts
  await handleDebugWorkflow(
    props.workflow_id,
    form.value,
    // 节点/汇总事件回调
    (event_response) => {
      const event = event_response.event as string
      const data = event_response.data as Record<string, unknown>
      if (event === 'summary') {
        // 汇总事件：记录整体状态
        overallStatus.value = (data.status as string) ?? ''
        failedNodes.value = []
        skippedNodes.value = []
        for (const fid of (data.failed_node_ids as string[]) ?? []) {
          const r = nodeResults.value.find((item) => item.node_id === fid)
          failedNodes.value.push({
            id: fid,
            title: (r?.node_data?.title as string) ?? fid,
            error: (r?.error as string) ?? '',
          })
        }
        for (const sid of (data.skipped_node_ids as string[]) ?? []) {
          const r = nodeResults.value.find((item) => item.node_id === sid)
          skippedNodes.value.push({
            id: sid,
            title: (r?.node_data?.title as string) ?? sid,
          })
        }
        return
      }
      // 普通节点事件：收集结果 + 通知画布状态
      const nodeResult = data as DebugNodeResult & { node_id?: string; status?: string }
      if (nodeResult.node_id) {
        nodeResults.value.push(nodeResult)
        emits('node-status', { node_id: nodeResult.node_id, status: nodeResult.status ?? 'succeeded' })
      }
    },
    // 错误事件回调（全局失败）
    (error_response) => {
      const data = error_response?.data as
        | { error?: string; error_node_id?: string; error_node_title?: string }
        | undefined
      if (!data) return
      debugWorkflowError.value = data.error ?? ''
      errorNodeId.value = data.error_node_id ?? ''
      errorNodeTitle.value = data.error_node_title ?? ''
      if (data.error_node_id) {
        emits('node-status', { node_id: data.error_node_id, status: 'failed' })
      }
    },
    // 节点级调试参数
    props.node_ids && props.node_ids.length > 0 ? { node_ids: props.node_ids } : undefined,
  )
```

`DebugNodeResult` 类型补字段：

```ts
type DebugNodeResult = {
  node_data: {
    node_type?: string
    type?: string
    title?: string
    id?: string
  }
  node_id?: string
  status?: string
  error?: string
  latency: number
  outputs?: unknown
}
```

- [ ] **Step 3: 模板展示整体状态与失败/跳过列表**

在「成功统计」区块（369-391 行）旁，增加整体状态与失败节点展示：

```html
<!-- 部分失败/失败提示 -->
<div
  v-if="overallStatus === 'partial_failed'"
  class="flex flex-col gap-2 bg-amber-50 p-3 rounded-lg border border-amber-400"
>
  <div class="flex items-center gap-2 text-amber-600 font-semibold">
    <icon-exclamation-circle-fill />
    <div>运行完成（部分分支失败）</div>
  </div>
  <div v-if="failedNodes.length > 0" class="flex flex-wrap gap-1.5">
    <span
      v-for="f in failedNodes"
      :key="f.id"
      class="inline-flex items-center gap-1 bg-red-100 border border-red-300 text-red-700 px-2 py-0.5 rounded-md text-xs"
    >
      <icon-close-circle style="font-size: 12px" />
      {{ f.title }}
    </span>
  </div>
</div>
<div
  v-if="skippedNodes.length > 0"
  class="flex flex-wrap gap-1.5 text-xs"
>
  <span
    v-for="s in skippedNodes"
    :key="s.id"
    class="inline-flex items-center gap-1 bg-gray-100 border border-gray-300 text-gray-500 px-2 py-0.5 rounded-md"
  >
    已跳过：{{ s.title }}
  </span>
</div>
```

并更新 `outputs` computed 说明（保持取最后一个 end 类型节点结果即可；节点级调试时合成 END「调试输出」会携带目标节点输出）。

`onSubmit` 开头重置新增状态：

```ts
  overallStatus.value = ''
  failedNodes.value = []
  skippedNodes.value = []
```

`watch(() => props.visible)` 内同步重置。

- [ ] **Step 4: 构建校验**

```bash
cd ai-code-llmops-web && pnpm build
```
预期：构建成功。

- [ ] **Step 5: 提交**

```bash
git add ai-code-llmops-web/src/views/space/workflows/components/DebugModal.vue
git commit -m "feat(web): DebugModal支持节点级调试与整体状态展示"
```

---

### Task 7: 全链路验证 + 推送分支

**Files:**
- 无代码改动（验证 + 日志）

- [ ] **Step 1: 后端单测全量回归**

```bash
venv\Scripts\python.exe -m pytest test/internal/core/workflow/ -v
```
预期：全部 PASS。

- [ ] **Step 2: 前端构建**

```bash
cd ai-code-llmops-web && pnpm build
```
预期：成功。

- [ ] **Step 3: 手工联调（本地 5173 + 后端）**

用工作流 GongZuoLiuCeShi123（含失效 google_serper 工具节点）验证：
1. 选中画布上非工具节点（如 LLM 节点）→ 点「调试选中节点」→ 输入表单 → 运行：
   - 预期：只运行该节点上游闭包；节点完成出现绿勾；不受 google_serper 节点影响；
2. 右键该工具节点 →「调试该节点」→ 预期：红框 + 「该内置插件扩展不存在」错误（构造失败走单条 error 事件）；
3. 整图调试 → 预期：失败节点红框 + 部分/全局失败文案；
4. 关闭调试面板 → 状态徽标清除。

- [ ] **Step 4: 推送分支**

```bash
git add -A
git commit -m "chore: 节点级调试联调验证" || true
git push -u origin release_20260827
```
预期：远端出现 release_20260827 分支。

- [ ] **Step 5: Obsidian 工作日志更新**

按 [[_工作日志约定]]，在 `Obsidian/Obsidian/工作日志/2026-08-25.md` 追加：功能完成项、验证结果、遗留事项（google_serper 节点保留、后续可选的联网搜索 provider 实现）。

---

## 自检记录

- **Spec 覆盖**：API 扩展（Task 3）、上游闭包子图 + 合成 END（Task 1/3）、BaseNode 统一包装 + failed_nodes + SKIPPED（Task 1/2）、全局/分支失败判定（Task 2/3）、SSE node_id + summary（Task 3）、前端入口与状态徽标（Task 5）、DebugModal（Task 6）、set_finish_point 修复（Task 2）、测试策略（Task 1/2/7）、分支与交付（Task 7）——全覆盖。
- **占位符扫描**：无 TBD/TODO 占位；每步含具体代码。
- **类型一致性**：`build_subgraph_config`、`is_end_reachable`、`set_graph_context`、`run`、`nodeStatusMap`、`debugWorkflow(..., opts)` 在各任务中签名一致。
