#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
handler 测试 async 化（httpx AsyncClient）。

使用 uvicorn TestServer（live_client/live_auth_headers）触发 lifespan。
handler 路由在 lifespan 中注册（register_routes_from_container）。
"""
import pytest

from package.response import HttpCode


class TestAppHandler:
    """app控制器的测试类"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [{}, {"query": ""}])
    async def test_debug_chat_validation(self, payload, live_client, live_auth_headers):
        resp = await live_client.post(
            "/apps/00000000-0000-0000-0000-000000000000/conversations",
            json=payload, headers=live_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json().get("code") in (HttpCode.VALIDATION_ERROR, HttpCode.NOT_FOUND, HttpCode.FAIL)

    @pytest.mark.asyncio
    async def test_ping(self, live_client, live_auth_headers):
        resp = await live_client.get("/ping", headers=live_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("code") == HttpCode.SUCCESS
        assert body.get("data", {}).get("pong") == "success"
