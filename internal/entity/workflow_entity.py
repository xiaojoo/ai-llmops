#!/usr/bin/env python
"""
@Time    : 2026/1/25 23:59
@Author  : sunxiaojie
@File    : workflow_entity.py
"""
from enum import Enum


class WorkflowStatus(str, Enum):
    """工作流状态类型枚举"""
    DRAFT = "draft"
    PUBLISHED = "published"


class WorkflowResultStatus(str, Enum):
    """工作流运行结果状态"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


DEFAULT_WORKFLOW_CONFIG = {
    "graph": {},
    "draft_graph": {
        "nodes": [],
        "edges": [],
    }
}
