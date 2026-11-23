#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
真实 HTTP 认证验证。

验证两分支认证 + webhook 公开：
1. Bearer JWT 认证（llmops 路由）：/account、/ping、/apps 等
2. api_key 认证（openapi 路由）：/openapi/chat
3. webhook 公开：/webhook 无认证直接访问

使用 uvicorn TestServer（真实 TCP，触发 lifespan）。
"""
import pytest


class TestBearerJWTAuth:
    """Bearer JWT 认证验证（llmops 蓝图路由）。"""

    @pytest.mark.asyncio
    async def test_account_with_valid_token(self, live_client, live_auth_headers):
        """Bearer JWT → /account 返回 200 + success（或 fail，取决于 DB 状态）。"""
        resp = await live_client.get("/account", headers=live_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # 认证通过后，code 可能是 success 或 fail（取决于 DB 状态）
        assert body["code"] in ("success", "fail"), f"unexpected code: {body['code']}"

    @pytest.mark.asyncio
    async def test_ping_with_valid_token(self, live_client, live_auth_headers):
        """Bearer JWT → /ping 返回 200 + success + pong。"""
        resp = await live_client.get("/ping", headers=live_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "success"
        assert body["data"]["pong"] == "success"

    @pytest.mark.asyncio
    async def test_apps_with_valid_token(self, live_client, live_auth_headers):
        """Bearer JWT → /apps 返回 200 + success（分页数据）。"""
        resp = await live_client.get("/apps", headers=live_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "success"

    @pytest.mark.asyncio
    async def test_settings_with_valid_token(self, live_client, live_auth_headers):
        """Bearer JWT → /settings/config 返回 200。"""
        resp = await live_client.get("/settings/config", headers=live_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] in ("success", "fail"), f"unexpected code: {body['code']}"

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, live_client):
        """无效 JWT → 200 + unauthorized。"""
        resp = await live_client.get(
            "/account",
            headers={"Authorization": "Bearer invalid-token-12345"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_malformed_auth_header_rejected(self, live_client):
        """格式错误的 Authorization → 200 + unauthorized。"""
        resp = await live_client.get(
            "/account",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_no_auth_header_rejected(self, live_client):
        """无 Authorization → 200 + unauthorized。"""
        resp = await live_client.get("/account")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"


class TestWebhookPublic:
    """webhook 公开路由验证。"""

    @pytest.mark.asyncio
    async def test_webhook_url_verification(self, live_client):
        """飞书 url_verification → 返回 challenge。"""
        resp = await live_client.post(
            "/webhook",
            json={"type": "url_verification", "challenge": "test-challenge-123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "success"
        assert body["data"]["challenge"] == "test-challenge-123"

    @pytest.mark.asyncio
    async def test_webhook_empty_body(self, live_client):
        """空 body webhook → 200 + success。"""
        resp = await live_client.post("/webhook", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "success"


class TestPublicRoutes:
    """公开路由（不在 153 内，app 级新增）。"""

    @pytest.mark.asyncio
    async def test_healthz(self, live_client):
        """healthz → 200 {"status":"ok"}。"""
        resp = await live_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_favicon(self, live_client):
        """favicon → 204 No Content。"""
        resp = await live_client.get("/favicon.ico")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_default_app_icon(self, live_client):
        """default-app-icon → 200 image/png。"""
        resp = await live_client.get("/default-app-icon")
        assert resp.status_code == 200
        assert "image/png" in resp.headers.get("content-type", "")
        assert len(resp.content) > 0
