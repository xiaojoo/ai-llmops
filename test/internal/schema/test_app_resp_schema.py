#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""GetAppResp 响应 schema 测试：app_type 字段透传与默认值"""
from types import SimpleNamespace

from internal.schema.app_schema import GetAppResp


def _app(**extra):
    base = dict(
        name="测试应用",
        icon="https://example.com/icon.png",
        description="",
    )
    base.update(extra)
    return SimpleNamespace(**base)


class TestGetAppRespAppType:
    def test_app_type_defaults_to_agent(self):
        """未设置 app_type 的应用，响应中默认返回 agent"""
        data = GetAppResp.model_validate(_app()).model_dump()
        assert data["app_type"] == "agent"

    def test_app_type_passthrough_orchestrator(self):
        """编排型应用，响应中原样返回 orchestrator"""
        data = GetAppResp.model_validate(_app(app_type="orchestrator")).model_dump()
        assert data["app_type"] == "orchestrator"
