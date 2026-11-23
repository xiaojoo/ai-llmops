#!/usr/bin/env python
"""
@Time    : 2026/8/25
@Author  : sunxiaojie
@File    : test_subgraph.py
子图与失败语义纯函数测试
"""
import uuid

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.nodes import EndNodeData, LLMNodeData, StartNodeData, TemplateTransformNodeData
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
    return BaseEdgeData(
        id=uuid.uuid4(),
        source=source.id,
        source_type=source.node_type,
        target=target.id,
        target_type=target.node_type,
    )


def _config(start: BaseNodeData, end: BaseNodeData, *middle: BaseNodeData, edges) -> WorkflowConfig:
    # WorkflowConfig 的 before 校验器要求 nodes/edges 为原始 dict（内部重新反序列化）
    return WorkflowConfig(
        account_id=uuid.uuid4(),
        name="test_flow",
        description="d",
        nodes=[n.model_dump(mode="json") for n in [start, end, *middle]],
        edges=[e.model_dump(mode="json") for e in edges],
    )


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
    cfg = _config(start, end, llm, edges=edges)
    sub_cfg = subgraph.build_subgraph_config(cfg, [llm.id])
    # 原 END 不在子图内，合成 END 追加
    assert len([n for n in sub_cfg.nodes if n.node_type == NodeType.END]) == 1
    sub_end = next(n for n in sub_cfg.nodes if n.node_type == NodeType.END)
    assert sub_end.title == "调试输出"
    assert sub_end.id != end.id
    assert any(e.source == llm.id and e.target == sub_end.id for e in sub_cfg.edges)
    # 合成 END 的 outputs 引用目标节点
    assert sub_end.outputs[0].value.content.ref_node_id == llm.id


def test_build_subgraph_config_keeps_original_end_when_selected():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    llm = _node(NodeType.LLM, "llm")
    edges = [_edge(start, llm), _edge(llm, end)]
    cfg = _config(start, end, llm, edges=edges)
    sub_cfg = subgraph.build_subgraph_config(cfg, [end.id])
    assert any(n.id == end.id for n in sub_cfg.nodes)


def test_end_reachable():
    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    a, b = _node(NodeType.LLM, "a"), _node(NodeType.LLM, "b")
    edges = [_edge(start, a), _edge(start, b), _edge(a, end), _edge(b, end)]
    assert subgraph.is_end_reachable(start.id, end.id, edges, [])
    assert subgraph.is_end_reachable(start.id, end.id, edges, [a.id])  # b 分支仍可达
    assert not subgraph.is_end_reachable(start.id, end.id, edges, [a.id, b.id])


def test_cleanup_stale_refs_removes_end_outputs_to_deleted_node():
    """删除节点后：END出参中指向已删节点的引用被自动移除，有效引用保留"""
    from internal.core.workflow.entities.variable_entity import (
        VariableEntity,
        VariableValueType,
    )

    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    deleted = _node(NodeType.LLM, "deleted")
    llm = _node(NodeType.LLM, "llm")
    # 给 END 装配 outputs：一个引用已删节点、一个引用存在节点
    end.outputs = [
        VariableEntity(
            name="bad",
            value={"type": VariableValueType.REF, "content": {"ref_node_id": str(deleted.id), "ref_var_name": "output"}},
        ),
        VariableEntity(
            name="good",
            value={"type": VariableValueType.REF, "content": {"ref_node_id": str(llm.id), "ref_var_name": "output"}},
        ),
    ]
    nodes = [start, end, llm]  # deleted 不在其中
    changed = subgraph.cleanup_stale_refs(nodes)
    assert changed == 1
    assert [v.name for v in end.outputs] == ["good"]


def test_cleanup_stale_refs_keeps_node_inputs_untouched_when_valid():
    """节点入参引用存在的节点时不被清理"""
    from internal.core.workflow.entities.variable_entity import (
        VariableEntity,
        VariableValueType,
    )

    start, end = _node(NodeType.START, "start"), _node(NodeType.END, "end")
    llm = _node(NodeType.LLM, "llm")
    tpl = _node(NodeType.TEMPLATE_TRANSFORM, "tpl")
    tpl.inputs = [
        VariableEntity(
            name="a",
            value={"type": VariableValueType.REF, "content": {"ref_node_id": str(llm.id), "ref_var_name": "output"}},
        ),
        VariableEntity(name="b", value={"type": VariableValueType.LITERAL, "content": "hi"}),
    ]
    nodes = [start, end, llm, tpl]
    changed = subgraph.cleanup_stale_refs(nodes)
    assert changed == 0
    assert len(tpl.inputs) == 2
