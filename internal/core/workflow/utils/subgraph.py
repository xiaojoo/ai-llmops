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

SYNTHETIC_END_TITLE = "调试输出"


def build_reverse_adjacency(edges: list[BaseEdgeData]) -> dict[UUID, list[UUID]]:
    """构建逆邻接表，key 为目标节点id，value 为该节点的直接前驱id列表"""
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
    # 起点自身已失败 → 不存在合法路径
    if start_id in failed:
        return False
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


def drop_stale_ref_variables(node_data: BaseNodeData, existing_ids: set[UUID]) -> bool:
    """移除节点变量（END用outputs，其余用inputs）中引用不存在节点的变量，返回是否发生变更"""
    variables_key = "outputs" if node_data.node_type == NodeType.END else "inputs"
    variables = getattr(node_data, variables_key, None)
    if not variables:
        return False
    kept = [
        variable for variable in variables
        if not (
            variable.value.type == VariableValueType.REF
            and variable.value.content.ref_node_id
            and UUID(str(variable.value.content.ref_node_id)) not in existing_ids
        )
    ]
    if len(kept) != len(variables):
        setattr(node_data, variables_key, kept)
        return True
    return False


def cleanup_stale_refs(node_data_list: list[BaseNodeData]) -> int:
    """批量清理所有节点的失效引用（指向不存在节点的REF变量），返回清理的节点数量"""
    existing_ids = {node_data.id for node_data in node_data_list}
    count = 0
    for node_data in node_data_list:
        if drop_stale_ref_variables(node_data, existing_ids):
            count += 1
    return count


def build_subgraph_config(config: WorkflowConfig, target_node_ids: list[UUID]) -> WorkflowConfig:
    """构建选中节点的上游闭包子图配置。

    - 若原 END 不在目标中：追加合成 END（title=调试输出，outputs=REF 各目标节点首个输出），
      并添加 目标节点 → 合成 END 的边；
    - 若原 END 在目标中：直接保留原 END 作为终点（闭包会包含整条链路）。
    """
    # 延迟导入避免与 nodes 包的循环依赖
    from internal.core.workflow.nodes.end.end_entity import EndNodeData

    nodes_by_id: dict[UUID, BaseNodeData] = {n.id: n for n in config.nodes}
    end_node = next(n for n in config.nodes if n.node_type == NodeType.END)
    reverse_adj = build_reverse_adjacency(config.edges)

    include_end = end_node.id in target_node_ids
    targets = [nid for nid in target_node_ids if nid != end_node.id]
    if include_end:
        # 选中 END 等价于运行整条链路：END 的全部前驱都在闭包内
        targets.append(end_node.id)
    closure = compute_upstream_closure(targets, reverse_adj)

    sub_nodes = [nodes_by_id[nid] for nid in closure]
    sub_edges = [e for e in config.edges if e.source in closure and e.target in closure]

    if include_end:
        return WorkflowConfig(
            account_id=config.account_id,
            name=f"{config.name}_debug",
            description="调试子图",
            nodes=[n.model_dump(mode="json") for n in sub_nodes],
            edges=[e.model_dump(mode="json") for e in sub_edges],
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
        nodes=[*[n.model_dump(mode="json") for n in sub_nodes], synthetic_end.model_dump(mode="json")],
        edges=[*[e.model_dump(mode="json") for e in sub_edges], *[e.model_dump(mode="json") for e in synthetic_edges]],
    )
