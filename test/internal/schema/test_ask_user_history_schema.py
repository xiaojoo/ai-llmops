#!/usr/bin/env python
"""ask_user 历史消息回显 schema Pydantic 化测试：agent_thoughts 顶层 question/options/allow_custom/choice 字段"""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from internal.schema.app_schema import GetDebugConversationMessagesWithPageResp
from internal.schema.assistant_agent_schema import GetAssistantAgentMessagesWithPageResp
from internal.schema.conversation_schema import GetConversationMessagesWithPageResp


def _now():
    return datetime.now(timezone.utc)


def _message(agent_thoughts):
    return SimpleNamespace(
        id=uuid4(), conversation_id=uuid4(), query="q", image_urls=[],
        file_urls=[], answer="a", total_token_count=0, latency=0.0, feedback="",
        agent_thoughts=agent_thoughts, is_archived=False, can_resume=False,
        created_at=_now(),
    )


def _ask_user_thought():
    """真实落库形态的 ask_user 推理步骤：
    question/options/sub_task_options/allow_custom 在 tool_input，choice 在 observation，
    task_id 独立列（SSE 事件携带，历史回显后仍可提交选择）"""
    return SimpleNamespace(
        id=uuid4(), position=1, event="ask_user", thought="",
        observation="RBAC", tool="ask_user",
        tool_input={
            "question": "选择授权模型？",
            "options": ["RBAC", "ABAC"],
            "sub_task_options": [
                {"order": 1, "title": "设计 RBAC 模型", "role_prompt": "你是权限模型设计师",
                 "expect_output": "输出 RBAC 设计文档", "required_tools": []},
                {"order": 2, "title": "实现 RBAC 接口", "role_prompt": "你是后端工程师",
                 "expect_output": "输出接口实现", "required_tools": ["code_interpreter"]},
            ],
            "allow_custom": True,
        },
        model_name="deepseek-v4-flash", llm_output="", tool_calls=[], message=[],
        trace=[], latency=0.0, total_token_count=0, total_price=0.0,
        created_at=_now(), sub_task_id=None, sub_task_title="",
        task_id=uuid4(),
    )


def _plain_thought(event="agent_thought"):
    """非 ask_user 推理步骤：交互字段应全部为空"""
    return SimpleNamespace(
        id=uuid4(), position=1, event=event, thought="t",
        observation="o", tool="", tool_input={}, trace=[], latency=0.0,
        model_name="deepseek-v4-flash", llm_output="", tool_calls=[], message=[],
        total_token_count=0, total_price=0.0,
        created_at=_now(), sub_task_id=None, sub_task_title="",
        task_id=None,
    )


_SUB_TASK_OPTIONS = [
    {"order": 1, "title": "设计 RBAC 模型", "role_prompt": "你是权限模型设计师",
     "expect_output": "输出 RBAC 设计文档", "required_tools": []},
    {"order": 2, "title": "实现 RBAC 接口", "role_prompt": "你是后端工程师",
     "expect_output": "输出接口实现", "required_tools": ["code_interpreter"]},
]


def _assert_ask_user_fields(thought: dict) -> None:
    assert thought["question"] == "选择授权模型？"
    assert thought["options"] == ["RBAC", "ABAC"]
    assert thought["sub_task_options"] == _SUB_TASK_OPTIONS
    assert thought["allow_custom"] is True
    assert thought["choice"] == "RBAC"
    assert thought["task_id"]


def _assert_empty_fields(thought: dict) -> None:
    assert thought["question"] == ""
    assert thought["options"] == []
    assert thought["sub_task_options"] == []
    assert thought["allow_custom"] is True
    assert thought["choice"] == ""
    assert thought["task_id"] == ""


def _dump_resp(resp_cls, obj):
    """Pydantic 模型兼容的 dump 适配"""
    return resp_cls.model_validate(obj).model_dump(mode="json")


class TestAskUserHistorySchema:
    def test_debug_resp_maps_ask_user_fields(self):
        data = _dump_resp(GetDebugConversationMessagesWithPageResp, _message([_ask_user_thought()]))
        _assert_ask_user_fields(data["agent_thoughts"][0])

    def test_debug_resp_non_ask_user_fields_empty(self):
        data = _dump_resp(GetDebugConversationMessagesWithPageResp, _message([_plain_thought()]))
        _assert_empty_fields(data["agent_thoughts"][0])

    def test_conversation_resp_maps_ask_user_fields(self):
        data = _dump_resp(GetConversationMessagesWithPageResp, _message([_ask_user_thought()]))
        _assert_ask_user_fields(data["agent_thoughts"][0])

    def test_conversation_resp_non_ask_user_fields_empty(self):
        data = _dump_resp(GetConversationMessagesWithPageResp, _message([_plain_thought()]))
        _assert_empty_fields(data["agent_thoughts"][0])

    def test_assistant_agent_resp_maps_ask_user_fields(self):
        data = _dump_resp(GetAssistantAgentMessagesWithPageResp, _message([_ask_user_thought()]))
        _assert_ask_user_fields(data["agent_thoughts"][0])

    def test_assistant_agent_resp_non_ask_user_fields_empty(self):
        data = _dump_resp(GetAssistantAgentMessagesWithPageResp, _message([_plain_thought()]))
        _assert_empty_fields(data["agent_thoughts"][0])
