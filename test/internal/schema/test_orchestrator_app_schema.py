#!/usr/bin/env python
"""创建/调试/对话请求 schema Pydantic 化测试"""
import pytest
from pydantic import ValidationError

from internal.schema.app_schema import CreateAppReq, DebugChatReq
from internal.schema.web_app_schema import WebAppChatReq


class TestOrchestratorAppSchema:
    def test_create_app_req_has_app_type(self):
        """CreateAppReq 默认 app_type 为 agent"""
        req = CreateAppReq(name="测试应用", icon="https://example.com/icon.png", description="描述")
        assert req.app_type == "agent"

    def test_create_app_req_validates_app_type_ok(self):
        """app_type=orchestrator 校验通过"""
        req = CreateAppReq(name="测试应用", icon="https://example.com/icon.png", description="描述", app_type="orchestrator")
        assert req.app_type == "orchestrator"

    def test_create_app_req_validates_app_type_bad(self):
        """app_type=bogus 校验失败"""
        with pytest.raises(ValidationError, match="应用类型仅支持 agent 或 orchestrator"):
            CreateAppReq(name="测试应用", icon="https://example.com/icon.png", description="描述", app_type="bogus")

    def test_debug_chat_req_has_resume(self):
        """DebugChatReq 默认 resume 为 False"""
        req = DebugChatReq(query="test")
        assert req.resume is False

    def test_web_app_chat_req_has_resume(self):
        """WebAppChatReq 默认 resume 为 False"""
        req = WebAppChatReq(query="test")
        assert req.resume is False

    def test_web_app_chat_req_default_mode_is_chat(self):
        """WebAppChatReq 默认 mode 为 chat（纯聊天）"""
        req = WebAppChatReq(query="test")
        assert req.mode == "chat"

    def test_web_app_chat_req_mode_auto_normalized_to_chat(self):
        """旧值 auto 归一化为 chat"""
        req = WebAppChatReq(query="test", mode="auto")
        assert req.mode == "chat"

    def test_web_app_chat_req_mode_agent_ok(self):
        """mode=agent 校验通过"""
        req = WebAppChatReq(query="test", mode="agent")
        assert req.mode == "agent"

    def test_web_app_chat_req_mode_bad_rejected(self):
        """mode 非法值校验失败"""
        with pytest.raises(ValidationError, match="mode 只能是 chat/agent"):
            WebAppChatReq(query="test", mode="bogus")
