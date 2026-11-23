#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
handler 测试 async 化（httpx AsyncClient）。

使用 uvicorn TestServer（live_client）触发 lifespan。
"""
import pytest

from package.response import HttpCode


class TestBuiltinToolHandler:
    """内置工具处理器测试类"""

    @pytest.mark.asyncio
    async def test_get_categories(self, live_client, live_auth_headers):
        resp = await live_client.get("/builtin_tools/categories", headers=live_auth_headers)
        assert resp.status_code == 200
        assert resp.json().get("code") == HttpCode.SUCCESS

    @pytest.mark.asyncio
    async def test_get_builtin_tools(self, live_client, live_auth_headers):
        resp = await live_client.get("/builtin_tools", headers=live_auth_headers)
        assert resp.status_code == 200
        assert resp.json().get("code") == HttpCode.SUCCESS
