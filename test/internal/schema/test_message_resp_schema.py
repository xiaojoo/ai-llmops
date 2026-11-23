#!/usr/bin/env python
"""消息列表响应 schema Pydantic 化测试：归档标记 & sub_task 字段"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from internal.schema.app_schema import GetDebugConversationMessagesWithPageResp
from internal.schema.conversation_schema import GetConversationMessagesWithPageResp


def _mock_message(is_archived: bool):
    msg = MagicMock(
        id=uuid4(), conversation_id=uuid4(), query="q", image_urls=[],
        file_urls=[], answer="a", total_token_count=0, latency=0.0, feedback="",
        agent_thoughts=[], created_at=datetime.now(),
        is_archived=is_archived,
        # 状态三兄弟必须给真值：MagicMock 会自动补出 MagicMock，而 schema 里它们是 str，
        # 校验直接抛错（本文件 _plain_message 的注释记过同一个坑）
        status="normal", run_status="succeeded", run_id=str(uuid4()),
    )
    return msg


def _plain_message(**extra):
    """真实对象形态的消息（避免 MagicMock 自动补属性掩盖 getattr 默认值）"""
    base = dict(
        id=uuid4(), conversation_id=uuid4(), query="q", image_urls=[],
        file_urls=[], answer="a", total_token_count=0, latency=0.0, feedback="",
        agent_thoughts=[], is_archived=False, created_at=datetime.now(),
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _dump_resp(resp_cls, obj):
    """Pydantic 模型兼容的 dump 适配"""
    return resp_cls.model_validate(obj).model_dump(mode="json")


class TestMessageRespSchema:
    def test_debug_resp_includes_is_archived(self):
        data = _dump_resp(GetDebugConversationMessagesWithPageResp, _mock_message(is_archived=True))
        assert data["is_archived"] is True
        data = _dump_resp(GetDebugConversationMessagesWithPageResp, _mock_message(is_archived=False))
        assert data["is_archived"] is False

    def test_conversation_resp_includes_is_archived(self):
        data = _dump_resp(GetConversationMessagesWithPageResp, _mock_message(is_archived=True))
        assert data["is_archived"] is True

    def test_conversation_resp_includes_can_resume(self):
        # 未 enrich 时默认 False
        data = _dump_resp(GetConversationMessagesWithPageResp, _plain_message())
        assert data["can_resume"] is False
        # 服务层 enrich 后透传
        data = _dump_resp(GetConversationMessagesWithPageResp, _plain_message(can_resume=True))
        assert data["can_resume"] is True

    def test_conversation_resp_includes_run_id(self):
        """run_id 未 enrich 时必须是空串而不是缺键：前端按它决定刷新后能不能重连回正在跑的 run。"""
        data = _dump_resp(GetConversationMessagesWithPageResp, _plain_message())
        assert data["run_id"] == ""
        data = _dump_resp(
            GetConversationMessagesWithPageResp, _plain_message(run_id="r-1"),
        )
        assert data["run_id"] == "r-1"

    def test_conversation_resp_includes_sub_task_fields(self):
        agent_thought = MagicMock(
            id=uuid4(), position=1, event="agent_thought", thought="t",
            observation="o", tool="", tool_input={}, latency=0.0,
            created_at=datetime.now(), sub_task_id=uuid4(), sub_task_title="子任务1",
        )
        data = _dump_resp(GetConversationMessagesWithPageResp, _plain_message(agent_thoughts=[agent_thought]))
        assert data["agent_thoughts"][0]["sub_task_id"] == str(agent_thought.sub_task_id)
        assert data["agent_thoughts"][0]["sub_task_title"] == "子任务1"
        # sub_task_id 为空时输出 None
        agent_thought.sub_task_id = None
        data = _dump_resp(GetConversationMessagesWithPageResp, _plain_message(agent_thoughts=[agent_thought]))
        assert data["agent_thoughts"][0]["sub_task_id"] is None
