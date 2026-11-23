#!/usr/bin/env python
"""
@Time    : 2026/8/30
@Author  : sunxiaojie
@File    : test_variable_coercion.py
变量安全类型转换（M1 修复）回归测试：
- 布尔字面量 "false" 必须解析为 False（修复 bool("false") == True）
- 数值转换失败降级为类型默认值（不再抛 ValueError 导致节点失败）
- 已匹配类型的值原样透传
"""
import uuid

from internal.core.workflow.entities.node_entity import (
    BaseNodeData,
    NodeResult,
    NodeStatus,
)
from internal.core.workflow.entities.variable_entity import (
    VariableEntity,
    VariableType,
    VariableValueType,
)
from internal.core.workflow.utils.helper import extract_variables_from_state


def _state_with(node_results=None):
    return {
        "inputs": {},
        "outputs": {},
        "node_results": node_results or [],
        "failed_nodes": [],
    }


def test_bool_literal_false_string_is_false():
    """核心回归：bool('false') 在旧实现下为 True"""
    var = VariableEntity(
        name="flag",
        type=VariableType.BOOLEAN,
        value={"type": VariableValueType.LITERAL, "content": "false"},
    )
    assert extract_variables_from_state([var], _state_with())["flag"] is False


def test_bool_literal_true_variants():
    for raw in ("true", "True", "1", "yes"):
        var = VariableEntity(
            name="flag",
            type=VariableType.BOOLEAN,
            value={"type": VariableValueType.LITERAL, "content": raw},
        )
        assert extract_variables_from_state([var], _state_with())["flag"] is True


def test_bool_literal_numeric():
    var = VariableEntity(
        name="flag",
        type=VariableType.BOOLEAN,
        value={"type": VariableValueType.LITERAL, "content": 1},
    )
    assert extract_variables_from_state([var], _state_with())["flag"] is True


def test_int_literal_valid_string():
    var = VariableEntity(
        name="n",
        type=VariableType.INT,
        value={"type": VariableValueType.LITERAL, "content": "42"},
    )
    assert extract_variables_from_state([var], _state_with())["n"] == 42


def test_int_literal_garbage_degrades_to_default():
    """旧实现 int('abc') 抛 ValueError 导致节点失败，现降级为默认值 0"""
    var = VariableEntity(
        name="n",
        type=VariableType.INT,
        value={"type": VariableValueType.LITERAL, "content": "abc"},
    )
    assert extract_variables_from_state([var], _state_with())["n"] == 0


def test_already_typed_value_passthrough():
    var = VariableEntity(
        name="n",
        type=VariableType.INT,
        value={"type": VariableValueType.LITERAL, "content": 7},
    )
    assert extract_variables_from_state([var], _state_with())["n"] == 7


def test_ref_value_coerced():
    """REF 引用取值同样做安全转换"""
    src = BaseNodeData(id=uuid.uuid4(), node_type="llm", title="src")
    var = VariableEntity(
        name="x",
        type=VariableType.INT,
        value={
            "type": VariableValueType.REF,
            "content": {"ref_node_id": str(src.id), "ref_var_name": "num"},
        },
    )
    state = _state_with([
        NodeResult(node_data=src, status=NodeStatus.SUCCEEDED, outputs={"num": 7}),
    ])
    assert extract_variables_from_state([var], state)["x"] == 7
