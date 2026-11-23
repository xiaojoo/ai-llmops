#!/usr/bin/env python
"""
@Time    : 2026/1/25 18:17
@Author  : sunxiaojie
@File    : helper.py
"""
import logging
from typing import Any

from internal.core.workflow.entities.variable_entity import (
    VARIABLE_TYPE_DEFAULT_VALUE_MAP,
    VARIABLE_TYPE_MAP,
    VariableEntity,
    VariableValueType,
)
from internal.core.workflow.entities.workflow_entity import WorkflowState

logger = logging.getLogger(__name__)


def _coerce_value(value: Any, variable_type, default: Any) -> Any:
    """将取值安全地转换为变量声明类型：

    - 已是目标类型则原样返回；
    - 布尔类型显式解析 "true/false/1/0/yes/no" 字符串，避免 bool("false") == True 的语义错误；
    - 数值/字符串转换失败时降级为类型默认值并记录告警（与"失败引用降级为默认值"的设计一致）。
    """
    converter = VARIABLE_TYPE_MAP.get(variable_type)
    if converter is None:
        # 类型不在映射表中（新增类型未同步映射），直接降级默认值
        return default
    if value is None:
        return default
    if isinstance(value, converter):
        return value

    # 布尔类型：字符串按显式语义解析，避免 bool("false") == True
    if converter is bool:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes"):
                return True
            if lowered in ("false", "0", "no", ""):
                return False
        return bool(value)

    try:
        return converter(value)
    except (TypeError, ValueError):
        logger.warning(
            "变量值 %r 无法转换为 %s，降级为默认值 %r",
            value, getattr(converter, "__name__", str(converter)), default,
        )
        return default


def extract_variables_from_state(variables: list[VariableEntity], state: WorkflowState) -> dict[str, Any]:
    """从状态中提取变量映射值信息"""

    # 1、构建变量字典信息
    variables_dict = {}

    # 2、循环遍历输入变量实体
    for variable in variables:
        # 3、获取数据变量类型
        variable_type = variable.type
        default_value = VARIABLE_TYPE_DEFAULT_VALUE_MAP.get(variable_type)

        # 4、判断数据是引用还是直接输入
        if variable.value.type == VariableValueType.LITERAL:
            # 字面量直接输入：安全转换
            variables_dict[variable.name] = _coerce_value(
                variable.value.content, variable_type, default_value
            )
        else:
            # 5、引用or生成数据类型，遍历节点获取数据
            for node_result in state["node_results"]:
                if node_result.node_data.id == variable.value.content.ref_node_id:
                    # 6、提取数据并完成安全类型转换
                    raw_value = node_result.outputs.get(
                        variable.value.content.ref_var_name,
                        default_value,
                    )
                    variables_dict[variable.name] = _coerce_value(
                        raw_value, variable_type, default_value
                    )

    return variables_dict
