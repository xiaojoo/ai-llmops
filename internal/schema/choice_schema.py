#!/usr/bin/env python
"""用户选择提交请求结构（task_id 走 URL 路径，不在 body）"""
from pydantic import BaseModel, Field, model_validator


class ChoiceReq(BaseModel):
    """用户选择提交请求：choice 与 skip 至少提供一个（plan 模式走 action/keep_orders/custom）"""
    choice: str = ""
    skip: bool = False
    action: str = ""
    keep_orders: list = Field(default_factory=list)
    custom: str = ""
    event_id: str = ""

    @model_validator(mode="after")
    def validate_choice_or_skip(self):
        # plan 模式无 choice 字段（提交 action/keep_orders/custom），
        # 校验放宽为"choice 非空 或 skip 或 action 非空"三选一
        if not self.choice and not self.skip and not self.action:
            raise ValueError("choice 与 skip 至少提供一个")
        return self
