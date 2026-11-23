#!/usr/bin/env python
"""
@Time    : 2026/8/30
@Author  : sunxiaojie
@File    : test_code_node.py
代码节点沙箱化（H1 修复）回归测试：
- 正常执行 main(params) 并返回 JSON 化结果
- 结构校验：非字典返回 / 多余语句 / 多余函数均拒绝
- 安全隔离：文件读写 / 网络 / 进程 / 非 JSON 入参/出参均被拒绝
"""
import uuid

import pytest

from internal.core.workflow.entities.node_entity import NodeStatus
from internal.core.workflow.nodes.code.code_entity import CodeNodeData
from internal.core.workflow.nodes.code.code_node import CodeNode
from internal.exception import FailedException


def _mk_node(code: str) -> CodeNode:
    return CodeNode(node_data=CodeNodeData(
        id=uuid.uuid4(),
        node_type="code",
        title="code_node",
        code=code,
    ))


def _empty_state():
    return {"inputs": {}, "outputs": {}, "node_results": [], "failed_nodes": []}


def _raises_message(exc_type, message: str, func, *args, **kwargs):
    """断言抛出 exc_type 且 .message 包含指定内容（项目自定义异常 str(e) 为空）"""
    with pytest.raises(exc_type) as exc_info:
        func(*args, **kwargs)
    assert message in exc_info.value.message


def test_code_node_executes_main_and_returns_dict():
    """正常执行：main(params) 计算结果通过 JSON 协议返回"""
    result = CodeNode._execute_function(
        "def main(params):\n    return {'sum': params['a'] + params['b']}\n",
        params={"a": 1, "b": 2},
    )
    assert result == {"sum": 3}


def test_code_node_run_success():
    """节点级执行：完整 run 流程返回 SUCCEEDED"""
    node = _mk_node("def main(params):\n    return {'out': params.get('x', '')}\n")
    result = node.invoke(_empty_state())
    assert result["node_results"][0].status == NodeStatus.SUCCEEDED


def test_code_node_rejects_non_dict_return():
    """main 返回值必须是字典（run 层校验）"""
    node = _mk_node("def main(params):\n    return 123\n")
    result = node.invoke(_empty_state())
    nr = result["node_results"][0]
    assert nr.status == NodeStatus.FAILED
    assert "字典" in nr.error


def test_code_node_rejects_extra_top_level_statement():
    """顶层只允许函数定义"""
    _raises_message(
        FailedException, "只能包含函数定义",
        CodeNode._execute_function,
        "x = 1\ndef main(params):\n    return {}\n", params={},
    )


def test_code_node_rejects_extra_function():
    """只允许一个 main 函数"""
    _raises_message(
        FailedException, "只能有main函数",
        CodeNode._execute_function,
        "def other():\n    pass\ndef main(params):\n    return {}\n", params={},
    )


def test_code_node_blocks_file_access():
    """审计钩子拦截文件读写（open）"""
    code = (
        "def main(params):\n"
        "    with open('C:/Windows/win.ini') as f:\n"
        "        return {'data': f.read()}\n"
    )
    _raises_message(FailedException, "禁止", CodeNode._execute_function, code, params={})


def test_code_node_blocks_network():
    """审计钩子拦截网络连接（socket 创建）"""
    code = (
        "def main(params):\n"
        "    import socket\n"
        "    s = socket.socket()\n"
        "    return {}\n"
    )
    _raises_message(FailedException, "禁止", CodeNode._execute_function, code, params={})


def test_code_node_blocks_subprocess():
    """审计钩子拦截进程启动（subprocess）"""
    code = (
        "def main(params):\n"
        "    import subprocess\n"
        "    subprocess.run(['whoami'])\n"
        "    return {}\n"
    )
    _raises_message(FailedException, "禁止", CodeNode._execute_function, code, params={})


def test_code_node_rejects_non_json_input():
    """入参必须可 JSON 序列化"""
    _raises_message(
        FailedException, "无法序列化",
        CodeNode._execute_function,
        "def main(params):\n    return params\n", params={"bad": object()},
    )


def test_code_node_rejects_non_json_return():
    """出参必须可 JSON 序列化（与结果落库要求一致）"""
    code = "def main(params):\n    return {'x': object()}\n"
    _raises_message(FailedException, "执行出错", CodeNode._execute_function, code, params={})


def test_code_node_reports_real_error():
    """用户代码抛异常时透出真实错误信息（不再吞成通用消息）"""
    code = "def main(params):\n    raise ValueError('boom')\n"
    _raises_message(FailedException, "boom", CodeNode._execute_function, code, params={})
