#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
handler 测试 async 化（httpx AsyncClient）。

使用 uvicorn TestServer（live_client）触发 lifespan。
"""
import pytest

from package.response import HttpCode


class TestApiToolHandler:
    """自定义API插件处理器测试类"""

    @pytest.mark.asyncio
    async def test_get_api_tools_with_page(self, live_client, live_auth_headers):
        """api_tools 分页列表 → 200 + success。"""
        resp = await live_client.get("/api_tools", headers=live_auth_headers)
        assert resp.status_code == 200
        assert resp.json().get("code") == HttpCode.SUCCESS
