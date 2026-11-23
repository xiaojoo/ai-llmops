#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
SSE 全链路测试。

SSE 端点：
- POST /apps/{app_id}/conversations (debug_chat)
- POST /web_apps/{token}/chat (web_app_chat)
- POST /assistant_agent/chat (assistant_agent_chat)
- POST /openapi/chat (openapi chat)

SSE 事件协议：
- Content-Type: text/event-stream
- 事件格式：event: <event_type>\ndata: <json>\n\n
- 事件类型：agent_thought / ping / agent_message / agent_end / error
- error/done 路径：error 事件包含错误信息

注意：完整 SSE 流需要真实的 LLM 配置和 app 数据，此处测试：
1. 未认证 → 200 + unauthorized（SSE 端点也是认证路由）
2. 认证但缺参数 → validation_error
3. SSE 响应头验证（Content-Type, Cache-Control, X-Accel-Buffering）
"""
import json

import pytest

_UUID = "00000000-0000-0000-0000-000000000001"


class TestSSEContract:
    """SSE 端点契约验证。"""

    @pytest.mark.asyncio
    async def test_debug_chat_unauthorized(self, live_client):
        """debug_chat 无认证 → 200 + unauthorized。"""
        resp = await live_client.post(
            f"/apps/{_UUID}/conversations",
            json={"query": "hello"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"
        assert "该接口需要授权才能访问" in body["message"]

    @pytest.mark.asyncio
    async def test_web_app_chat_public(self, live_client):
        """web_app_chat 路由在 llmops_router 下，需要认证。

        但 web_app 的 token 参数是 path param，不是 Bearer auth。
        无 Bearer token → unauthorized（router 级认证）。
        """
        resp = await live_client.post(
            f"/web_apps/{_UUID}/chat",
            json={"query": "hello"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_assistant_agent_chat_unauthorized(self, live_client):
        """assistant_agent_chat 无认证 → 200 + unauthorized。"""
        resp = await live_client.post(
            "/assistant_agent/chat",
            json={"query": "hello"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_openapi_chat_unauthorized(self, live_client):
        """openapi/chat 无 api_key → 200 + unauthorized。"""
        resp = await live_client.post(
            "/openapi/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_debug_chat_validation_error(self, live_client, live_auth_headers):
        """debug_chat 认证但缺必需参数 → validation_error。"""
        resp = await live_client.post(
            f"/apps/{_UUID}/conversations",
            json={},  # 缺少 query
            headers=live_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        # 可能是 validation_error 或 not_found（app 不存在）
        assert body["code"] in ("validation_error", "not_found", "fail"), f"unexpected code: {body['code']}"

    @pytest.mark.asyncio
    async def test_sse_response_headers(self, live_client, live_auth_headers):
        """验证 SSE 端点的响应头契约（如果返回流式响应）。

        注意：如果 app 不存在，handler 会先抛异常（not_found），
        不会走到 SSE 流式路径。此处验证认证 + 参数校验通过后的响应。
        """
        resp = await live_client.post(
            f"/apps/{_UUID}/conversations",
            json={"query": "test"},
            headers=live_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        # app 不存在时返回 not_found，这是正常行为
        # 如果 SSE 流式成功，content-type 会是 text/event-stream
        if "text/event-stream" in resp.headers.get("content-type", ""):
            # SSE 流式响应
            assert "no-cache" in resp.headers.get("cache-control", "").lower()
        else:
            # JSON 错误响应（app 不存在等）
            assert body["code"] in ("not_found", "fail", "validation_error")


class TestSSEEventFormat:
    """SSE 事件格式验证（基于 compact_generate_response 的输出契约）。"""

    @pytest.mark.asyncio
    async def test_compact_generate_response_sse_format(self):
        """验证 compact_generate_response 对 async generator 的 SSE 格式。

        直接测试 response 模块，不依赖 lifespan。
        """
        from package.response import compact_generate_response

        async def _mock_stream():
            yield "event: agent_thought\ndata: {\"thought\": \"thinking...\"}\n\n"
            yield "event: ping\ndata: {}\n\n"
            yield "event: agent_message\ndata: {\"answer\": \"hello\"}\n\n"
            yield "event: agent_end\ndata: {}\n\n"

        resp = compact_generate_response(_mock_stream())
        assert resp.media_type == "text/event-stream"
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("X-Accel-Buffering") == "no"

        # 读取流内容
        body_parts = []
        async for chunk in resp.body_iterator:
            if isinstance(chunk, bytes):
                body_parts.append(chunk.decode())
            else:
                body_parts.append(chunk)
        body = "".join(body_parts)

        # 验证事件序列
        assert "event: agent_thought" in body
        assert "event: ping" in body
        assert "event: agent_message" in body
        assert "event: agent_end" in body

    @pytest.mark.asyncio
    async def test_compact_generate_response_error_format(self):
        """验证 error 事件格式。"""
        from package.response import compact_generate_response

        async def _mock_error_stream():
            yield "event: error\ndata: {\"message\": \"something went wrong\"}\n\n"

        resp = compact_generate_response(_mock_error_stream())
        assert resp.media_type == "text/event-stream"

        body_parts = []
        async for chunk in resp.body_iterator:
            if isinstance(chunk, bytes):
                body_parts.append(chunk.decode())
            else:
                body_parts.append(chunk)
        body = "".join(body_parts)
        assert "event: error" in body
        assert "something went wrong" in body

    @pytest.mark.asyncio
    async def test_compact_generate_response_json_passthrough(self):
        """验证 Response 对象走 JSON 路径（非 SSE）。"""
        from package.response import compact_generate_response, Response, success_json

        resp_obj = success_json({"test": "data"})
        result = compact_generate_response(resp_obj)
        # success_json 返回 JSONResponse
        assert result.status_code == 200
