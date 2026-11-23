#!/usr/bin/env python
"""choice 提交请求 schema Pydantic 化测试：option 模式与 plan 模式校验"""
import pytest
from pydantic import ValidationError

from internal.schema.choice_schema import ChoiceReq


def test_choice_mode_valid():
    """option 模式：choice 非空通过"""
    req = ChoiceReq(choice="RBAC", skip=False, event_id="e1")
    assert req.choice == "RBAC"


def test_plan_mode_with_action_valid():
    """plan 模式无 choice 但有 action 时校验通过"""
    req = ChoiceReq(action="confirm", keep_orders=[1, 3], custom="", skip=False, event_id="e1")
    assert req.action == "confirm"
    assert req.keep_orders == [1, 3]
    assert req.custom == ""


def test_plan_mode_replan_valid():
    """plan 模式 replan：action 非空 + custom 原因通过"""
    req = ChoiceReq(action="replan", keep_orders=[], custom="第二个子任务改用ABAC", skip=False, event_id="e1")
    assert req.custom == "第二个子任务改用ABAC"


def test_empty_invalid():
    """choice/skip/action 全空 → 校验失败"""
    with pytest.raises(ValidationError, match="choice 与 skip 至少提供一个"):
        ChoiceReq(choice="", skip=False, event_id="e1")


def test_skip_alone_valid():
    """仅 skip=true 通过（跳过场景）"""
    req = ChoiceReq(choice="", skip=True, event_id="e1")
    assert req.skip is True
