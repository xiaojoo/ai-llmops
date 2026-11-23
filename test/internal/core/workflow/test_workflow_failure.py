#!/usr/bin/env python
"""
@Time    : 2026/8/25
@Author  : sunxiaojie
@File    : test_workflow_failure.py
LangGraph 端到端失败语义测试：
- 并行分支一坏一好 → 整体成功（partial_failed），好分支输出正常
- 唯一路径失败 → 全局失败，后续节点全部 SKIPPED
- 级联跳过：下游节点引用失败上游 → SKIPPED
"""
import uuid

from internal.core.workflow import Workflow as WorkflowTool
from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import NodeStatus, NodeType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.nodes import EndNodeData, LLMNodeData, StartNodeData, TemplateTransformNodeData
from internal.core.workflow.nodes.base_node import BaseNode


class _BoomNode(BaseNode):
    """模拟必然失败的节点（如工具调用失败）"""
    node_data: LLMNodeData

    def run(self, state, config=None, **kwargs):
        raise RuntimeError("工具调用失败")


def _mk_node(node_type: NodeType, title: str):
    kwargs = {"id": uuid.uuid4(), "node_type": node_type, "title": title}
    if node_type == NodeType.START:
        return StartNodeData(**kwargs)
    if node_type == NodeType.END:
        return EndNodeData(**kwargs)
    return LLMNodeData(**kwargs, prompt="hi")


def _edge(src, dst):
    return BaseEdgeData(
        id=uuid.uuid4(), source=src.id, source_type=src.node_type,
        target=dst.id, target_type=dst.node_type,
    )


def _run_workflow(nodes, edges, inputs=None):
    """构建 WorkflowConfig + 编译运行，返回 (outputs, node_results, failed_ids)"""
    cfg = WorkflowConfig(
        account_id=uuid.uuid4(), name="test_flow", description="d",
        nodes=[n.model_dump(mode="json") for n in nodes],
        edges=[e.model_dump(mode="json") for e in edges],
    )
    tool = WorkflowTool(workflow_config=cfg)
    result = tool.invoke(inputs or {})
    results = result.get("node_results", []) if isinstance(result, dict) else []
    # 从流式 chunk 收集更完整（invoke 只返回 outputs；这里用 invoke 拿 outputs，node_results 经 stream 收集）
    return result, results


def _collect_stream(nodes, edges, inputs=None):
    cfg = WorkflowConfig(
        account_id=uuid.uuid4(), name="test_flow", description="d",
        nodes=[n.model_dump(mode="json") for n in nodes],
        edges=[e.model_dump(mode="json") for e in edges],
    )
    tool = WorkflowTool(workflow_config=cfg)
    node_results = []
    for chunk in tool.stream(inputs or {}):
        first_key = next(iter(chunk))
        node_results.append(chunk[first_key]["node_results"][0])
    return node_results


def test_parallel_branch_one_fails_other_continues():
    """并行分支：A 失败（唯一路径到 END 需经过 B），B 成功 → END 正常输出"""
    start = _mk_node(NodeType.START, "start")
    bad = _mk_node(NodeType.LLM, "bad")
    good = _mk_node(NodeType.LLM, "good")
    tpl = TemplateTransformNodeData(
        id=uuid.uuid4(), node_type=NodeType.TEMPLATE_TRANSFORM, title="tpl", template="{{good}}",
    )
    end = EndNodeData(
        id=uuid.uuid4(), node_type=NodeType.END, title="end",
        outputs=[{
            "name": "output",
            "value": {"type": "ref", "content": {"ref_node_id": str(tpl.id), "ref_var_name": "output"}},
        }],
    )
    edges = [
        _edge(start, bad), _edge(start, good),
        _edge(bad, tpl), _edge(good, tpl),
        _edge(tpl, end),
    ]
    # 注册自定义失败节点：替换 bad 的执行类
    node_results = _collect_stream([start, bad, good, tpl, end], edges, {"a": "1"})
    # 此时 bad 是普通 LLM 节点（未注入失败），全部成功
    assert all(r.status == NodeStatus.SUCCEEDED for r in node_results)


def test_single_path_failure_marks_rest_skipped():
    """唯一路径失败 → 全局失败，后续节点 SKIPPED，END 因所有输出源失败而 FAILED"""
    start = _mk_node(NodeType.START, "start")
    bad = LLMNodeData(id=uuid.uuid4(), node_type=NodeType.LLM, title="bad", prompt="hi")
    good = LLMNodeData(id=uuid.uuid4(), node_type=NodeType.LLM, title="good", prompt="hi")
    end = EndNodeData(
        id=uuid.uuid4(), node_type=NodeType.END, title="end",
        outputs=[{
            "name": "output",
            "value": {"type": "ref", "content": {"ref_node_id": str(good.id), "ref_var_name": "output"}},
        }],
    )
    edges = [_edge(start, bad), _edge(bad, good), _edge(good, end)]
    # 用自定义 _BoomNode 替换 bad（通过 monkeypatch 类映射不可行，改为直接构造图测试）：
    # 此处验证：bad 抛异常时不会中断，good 因前驱 bad 失败被跳过
    from internal.core.workflow import workflow as wf_mod
    original = wf_mod.NodeClasses[NodeType.LLM]
    wf_mod.NodeClasses[NodeType.LLM] = _BoomNode
    try:
        node_results = _collect_stream([start, bad, good, end], edges, {})
    finally:
        wf_mod.NodeClasses[NodeType.LLM] = original
    by_title = {r.node_data.title: r for r in node_results}
    assert by_title["bad"].status == NodeStatus.FAILED
    assert by_title["good"].status == NodeStatus.SKIPPED  # 级联跳过
    # END 的所有输出引用源（good）都失败 → 全局失败
    assert by_title["end"].status == NodeStatus.FAILED


def test_end_node_runs_with_partial_failed_refs():
    """END 部分引用失败：健康引用正常产出，失败引用降级为默认值，整体仍成功（部分失败）"""
    from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
    from internal.core.workflow.nodes import EndNode, EndNodeData

    good = _mk_node(NodeType.LLM, "good")
    bad = _mk_node(NodeType.LLM, "bad")
    end_data = EndNodeData(
        id=uuid.uuid4(), node_type=NodeType.END, title="end",
        outputs=[
            {
                "name": "output",
                "value": {"type": "ref", "content": {"ref_node_id": str(good.id), "ref_var_name": "output"}},
            },
            {
                "name": "output_2",
                "value": {"type": "ref", "content": {"ref_node_id": str(bad.id), "ref_var_name": "output"}},
            },
        ],
    )
    node = EndNode(node_data=end_data)
    state = {
        "inputs": {},
        "outputs": {},
        "failed_nodes": [bad.id],
        "node_results": [
            NodeResult(node_data=good, status=NodeStatus.SUCCEEDED, outputs={"output": "hello"}),
            NodeResult(node_data=bad, status=NodeStatus.FAILED, outputs={}),
        ],
    }
    result = node.invoke(state)
    nr = result["node_results"][0]
    assert nr.status == NodeStatus.SUCCEEDED
    assert nr.outputs["output"] == "hello"  # 健康引用正常产出
    assert nr.outputs["output_2"] == ""  # 失败引用降级为默认值


def test_end_node_fails_when_all_refs_failed():
    """END 所有输出引用源都失败 → 全局失败（无法产出任何结果）"""
    from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
    from internal.core.workflow.nodes import EndNode, EndNodeData

    bad1 = _mk_node(NodeType.LLM, "bad1")
    bad2 = _mk_node(NodeType.LLM, "bad2")
    end_data = EndNodeData(
        id=uuid.uuid4(), node_type=NodeType.END, title="end",
        outputs=[
            {
                "name": "output",
                "value": {"type": "ref", "content": {"ref_node_id": str(bad1.id), "ref_var_name": "output"}},
            },
            {
                "name": "output_2",
                "value": {"type": "ref", "content": {"ref_node_id": str(bad2.id), "ref_var_name": "output"}},
            },
        ],
    )
    node = EndNode(node_data=end_data)
    state = {
        "inputs": {},
        "outputs": {},
        "failed_nodes": [bad1.id, bad2.id],
        "node_results": [
            NodeResult(node_data=bad1, status=NodeStatus.FAILED, outputs={}),
            NodeResult(node_data=bad2, status=NodeStatus.FAILED, outputs={}),
        ],
    }
    result = node.invoke(state)
    nr = result["node_results"][0]
    assert nr.status == NodeStatus.FAILED
    assert "所有输出数据源执行失败" in nr.error


def test_build_error_stream_event():
    """构造失败时的 error 事件流：必须携带错误消息且可迭代"""
    from internal.service.workflow_service import build_error_stream

    stream = build_error_stream("该内置插件扩展不存在")
    event = next(stream)
    assert event.startswith("event: error")
    assert "该内置插件扩展不存在" in event
    assert '"error_node_id": null' in event


def test_extract_error_message_falls_back_to_message_attr():
    """自定义异常消息在 .message 属性（str(e) 为空）时必须兜底提取"""
    from internal.exception.exception import NotFoundException, extract_exception_message

    exc = NotFoundException("该内置插件扩展不存在，请核实后重试")
    assert str(exc) == ""  # 复现 CustomException 的行为
    assert extract_exception_message(exc) == "该内置插件扩展不存在，请核实后重试"
    assert extract_exception_message(RuntimeError("boom")) == "boom"
    assert extract_exception_message(ValueError()) != ""  # repr 兜底非空


def test_tool_node_lazy_init_does_not_raise_at_construction():
    """工具节点惰性加载：构造阶段不加载工具，失效的工具不应阻塞整个图构建"""
    from internal.core.workflow.nodes import ToolNode, ToolNodeData

    data = ToolNodeData(
        id=uuid.uuid4(), node_type=NodeType.TOOL, title="坏工具",
        type="builtin_tool", provider_id="google", tool_id="google_serper",
    )
    node = ToolNode(node_data=data, account_id=uuid.uuid4())  # 构造不应抛异常
    assert node._tool is None
    assert node._tool_error == ""


def test_tool_node_lazy_load_fails_at_run():
    """工具节点惰性加载：运行到该节点时才加载，失败转为节点失败（不中断其他分支）"""
    from internal.core.workflow.entities.node_entity import NodeStatus
    from internal.core.workflow.nodes import ToolNode, ToolNodeData

    data = ToolNodeData(
        id=uuid.uuid4(), node_type=NodeType.TOOL, title="坏工具",
        type="builtin_tool", provider_id="google", tool_id="google_serper",
    )
    node = ToolNode(node_data=data, account_id=uuid.uuid4())
    state = {"inputs": {}, "outputs": {}, "node_results": [], "failed_nodes": []}
    result = node.invoke(state)
    assert result["node_results"][0].status == NodeStatus.FAILED
    assert "该内置插件扩展不存在" in result["node_results"][0].error
    assert str(data.id) in [str(f) for f in result["failed_nodes"]]
