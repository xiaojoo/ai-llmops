#!/usr/bin/env python
"""
@Time    : 2026/8/25
@Author  : sunxiaojie
@File    : test_base_node.py
BaseNode 统一包装（异常捕获 + 失败语义）测试
"""
import uuid

from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import (
    BaseNodeData,
    NodeResult,
    NodeStatus,
    NodeType,
)
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode


class _OkNode(BaseNode):
    """正常执行节点"""
    node_data: BaseNodeData

    def run(self, state, config=None, **kwargs):
        return {
            "node_results": [
                NodeResult(node_data=self.node_data, status=NodeStatus.SUCCEEDED, outputs={"output": "ok"})
            ]
        }


class _FailNode(BaseNode):
    """必然抛异常的节点"""
    node_data: BaseNodeData

    def run(self, state, config=None, **kwargs):
        raise RuntimeError("boom")


def _node(node_type: NodeType, title: str) -> BaseNodeData:
    return BaseNodeData(id=uuid.uuid4(), node_type=node_type, title=title)


def _state(failed: list[str]) -> WorkflowState:
    return {
        "inputs": {},
        "outputs": {},
        "node_results": [],
        "failed_nodes": [uuid.UUID(f) for f in failed],
    }


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
    edges = [
        BaseEdgeData(
            id=uuid.uuid4(), source=pred.id, source_type=NodeType.LLM,
            target=curr.id, target_type=NodeType.LLM,
        )
    ]
    node = _OkNode(node_data=curr)
    node.set_graph_context(edges=edges, start_node_id=pred.id, end_node_id=curr.id)
    result = node.invoke(_state([str(pred.id)]))
    assert result["node_results"][0].status == NodeStatus.SKIPPED
    assert str(curr.id) in [str(f) for f in result["failed_nodes"]]


def test_node_runs_when_failure_does_not_block_end():
    other = _node(NodeType.LLM, "other")
    curr = _node(NodeType.LLM, "curr")
    end = _node(NodeType.END, "end")
    edges = [
        BaseEdgeData(
            id=uuid.uuid4(), source=curr.id, source_type=NodeType.LLM,
            target=end.id, target_type=NodeType.END,
        )
    ]
    node = _OkNode(node_data=curr)
    node.set_graph_context(edges=edges, start_node_id=curr.id, end_node_id=end.id)
    # 无关分支失败节点不影响 END 可达性
    result = node.invoke(_state([str(other.id)]))
    assert result["node_results"][0].status == NodeStatus.SUCCEEDED


def test_node_skipped_when_end_unreachable():
    curr = _node(NodeType.LLM, "curr")
    end = _node(NodeType.END, "end")
    edges = [
        BaseEdgeData(
            id=uuid.uuid4(), source=curr.id, source_type=NodeType.LLM,
            target=end.id, target_type=NodeType.END,
        )
    ]
    node = _OkNode(node_data=curr)
    node.set_graph_context(edges=edges, start_node_id=curr.id, end_node_id=end.id)
    # curr 自身处于失败集合 → 通过 curr 到 END 的路径全部断裂
    result = node.invoke(_state([str(curr.id)]))
    assert result["node_results"][0].status == NodeStatus.SKIPPED


def test_end_node_not_skipped_by_predecessor_edge():
    pred = _node(NodeType.LLM, "pred")
    end_data = _node(NodeType.END, "end")
    edges = [
        BaseEdgeData(
            id=uuid.uuid4(), source=pred.id, source_type=NodeType.LLM,
            target=end_data.id, target_type=NodeType.END,
        )
    ]
    node = _OkNode(node_data=end_data)  # END 节点：仅按 REF 判定，不看前驱边
    node.set_graph_context(edges=edges, start_node_id=pred.id, end_node_id=end_data.id)
    result = node.invoke(_state([str(pred.id)]))
    assert result["node_results"][0].status == NodeStatus.SUCCEEDED
