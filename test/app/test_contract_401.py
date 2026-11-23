#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
契约回归：153 路由未认证冒烟。

每条路由：
- 需要认证的（llmops_router 路由，handler 有 user 参数）→ 无 token 请求 → HTTP 200 + code=unauthorized
- 公开路由（/webhook、/favicon.ico、/default-app-icon、/healthz、/docs）→ 直接请求 → 200 + 正确响应

认证面判定依据：route-inventory 蓝图归属（bp → 需认证，openapi_bp → 需 api_key）
+ 公开路由（/webhook、/favicon.ico、/default-app-icon、/healthz）。

黄金契约：401-shape.json → HTTP 200 + {"code":"unauthorized","data":{},"message":"该接口需要授权才能访问，请登录后尝试"}
"""
import uuid

import pytest

# llmops 蓝图路由（需要 Bearer JWT 认证）— 从 route-inventory.md 提取
# 格式：(method, path_template)
# 路径参数使用 UUID 占位符
_UUID = "00000000-0000-0000-0000-000000000001"
_STR_PARAM = "test-param"

# 153 路由分组：llmops 认证路由（bp 蓝图）+ openapi 认证路由 + 公开路由
LLMOPS_AUTH_ROUTES = [
    # ---- 1. 应用模块 ----
    ("GET", "/ping"),
    ("POST", "/apps"),
    ("GET", "/apps"),
    ("POST", f"/apps/{_UUID}/delete"),
    ("GET", f"/apps/{_UUID}"),
    ("POST", f"/apps/{_UUID}"),
    ("POST", f"/apps/{_UUID}/copy"),
    ("GET", f"/apps/{_UUID}/draft_app_config"),
    ("POST", f"/apps/{_UUID}/draft_app_config"),
    ("POST", f"/apps/{_UUID}/publish"),
    ("POST", f"/apps/{_UUID}/cancel_publish"),
    ("GET", f"/apps/{_UUID}/publish_histories"),
    ("POST", f"/apps/{_UUID}/fallback_history"),
    ("GET", f"/apps/{_UUID}/summary"),
    ("POST", f"/apps/{_UUID}/summary"),
    ("POST", f"/apps/{_UUID}/conversations/delete_debug_conversation"),
    ("POST", f"/apps/{_UUID}/conversations"),
    ("POST", f"/apps/{_UUID}/conversations/tasks/{_UUID}/stop"),
    ("POST", f"/apps/{_UUID}/conversations/tasks/{_UUID}/choice"),
    ("GET", f"/apps/{_UUID}/conversations/messages"),
    ("GET", f"/apps/{_UUID}/published_config"),
    ("POST", f"/apps/{_UUID}/published_config/regenerate_web_app_token"),
    ("GET", f"/apps/{_UUID}/memory/facts"),
    ("GET", f"/apps/{_UUID}/memory/facts/history"),
    ("GET", f"/apps/{_UUID}/memory/facts/at"),
    ("GET", f"/apps/{_UUID}/memory/facts/window"),
    ("GET", f"/apps/{_UUID}/memory/episodic"),
    ("GET", f"/apps/{_UUID}/memory/instructions"),
    ("POST", "/memory/test"),
    # ---- 2. 内置插件广场模块 ----
    ("GET", "/builtin_apps"),
    ("GET", "/builtin_apps/categories"),
    ("POST", "/builtin_apps/add_builtin_app_to_space"),
    # ---- 3. 自定义API插件模块 ----
    ("GET", "/api_tools"),
    ("POST", "/api_tools/validate_openapi_schema"),
    ("POST", "/api_tools"),
    ("GET", f"/api_tools/{_UUID}"),
    ("POST", f"/api_tools/{_UUID}"),
    ("GET", f"/api_tools/{_UUID}/tools/{_STR_PARAM}"),
    ("POST", f"/api_tools/{_UUID}/tools/{_STR_PARAM}/debug"),
    ("POST", f"/api_tools/{_UUID}/delete"),
    # ---- 4. 上传文件模块 ----
    ("POST", "/upload-files/file"),
    ("POST", "/upload-files/image"),
    ("GET", "/upload-files/pending"),
    ("POST", f"/upload-files/{_UUID}/delete"),
    ("GET", f"/upload-files/{_UUID}/url"),
    # ---- 5. 知识库模块 ----
    ("POST", "/datasets"),
    ("GET", f"/datasets/{_UUID}"),
    ("POST", f"/datasets/{_UUID}"),
    ("GET", "/datasets"),
    ("GET", "/datasets/embeddings"),
    ("POST", f"/datasets/{_UUID}/delete"),
    ("GET", f"/datasets/{_UUID}/documents/{_UUID}"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/name"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/enabled"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/delete"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/retry"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/pause"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/resume"),
    ("POST", f"/datasets/{_UUID}/documents/preview-chunks"),
    ("GET", f"/datasets/{_UUID}/documents"),
    ("POST", f"/datasets/{_UUID}/documents"),
    ("GET", f"/datasets/{_UUID}/documents/batch/{_STR_PARAM}"),
    ("POST", f"/datasets/{_UUID}/hit"),
    ("GET", f"/datasets/{_UUID}/queries"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/segments"),
    ("GET", f"/datasets/{_UUID}/documents/{_UUID}/segments"),
    ("GET", f"/datasets/{_UUID}/documents/{_UUID}/segments/{_UUID}"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/segments/{_UUID}/delete"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/segments/{_UUID}/enabled"),
    ("POST", f"/datasets/{_UUID}/documents/{_UUID}/segments/{_UUID}"),
    # ---- 6. 授权认证模块 ----
    ("POST", "/auth/logout"),
    # ---- 7. 账号设置 ----
    ("GET", "/account"),
    ("POST", "/account/password"),
    ("POST", "/account/name"),
    ("POST", "/account/avatar"),
    # ---- 8. AI辅助模块 ----
    ("POST", "/ai/optimize_prompt"),
    ("POST", "/ai/suggested_questions"),
    # ---- 9. API秘钥模板 ----
    ("GET", "/openapi/api_keys"),
    ("POST", "/openapi/api_keys"),
    ("POST", f"/openapi/api_keys/{_UUID}"),
    ("POST", f"/openapi/api_keys/{_UUID}/is_active"),
    ("POST", f"/openapi/api_keys/{_UUID}/delete_api_key"),
    # ---- 10. 系统设置 ----
    ("GET", "/settings/config"),
    ("PUT", "/settings/config"),
    # ---- 11. 工作流模块 ----
    ("GET", "/workflows"),
    ("POST", "/workflows"),
    ("POST", f"/workflows/{_UUID}"),
    ("POST", f"/workflows/{_UUID}/delete"),
    ("GET", f"/workflows/{_UUID}"),
    ("POST", f"/workflows/{_UUID}/draft_graph"),
    ("GET", f"/workflows/{_UUID}/draft_graph"),
    ("POST", f"/workflows/{_UUID}/debug"),
    ("POST", f"/workflows/{_UUID}/publish"),
    ("POST", f"/workflows/{_UUID}/cancel_publish"),
    # ---- 12. 语言模型模块 ----
    ("GET", "/language_models"),
    ("GET", f"/language_models/{_STR_PARAM}/{_STR_PARAM}"),
    # ---- 13. 辅助Agent模块 ----
    ("POST", "/assistant_agent/chat"),
    ("POST", f"/assistant_agent/chat/{_UUID}/stop"),
    ("POST", f"/assistant_agent/chat/{_UUID}/choice"),
    ("GET", "/assistant_agent/messages"),
    ("POST", "/assistant_agent/delete_conversation"),
    # ---- 14. 应用统计 ----
    ("GET", f"/analysis/{_UUID}"),
    # ---- 15. WebApp模块 ----
    ("GET", "/web_apps/default"),
    ("POST", "/web_apps/plugin/bootstrap"),
    ("GET", f"/web_apps/{_STR_PARAM}"),
    ("POST", f"/web_apps/{_STR_PARAM}/chat"),
    ("POST", f"/web_apps/{_STR_PARAM}/chat/{_UUID}/stop"),
    ("POST", f"/web_apps/{_STR_PARAM}/chat/{_UUID}/choice"),
    ("POST", f"/web_apps/{_STR_PARAM}/code_action"),
    ("GET", f"/web_apps/{_STR_PARAM}/conversations"),
    # ---- 16. 会话模块 ----
    ("GET", f"/conversations/{_UUID}/messages"),
    ("POST", f"/conversations/{_UUID}/delete"),
    ("POST", f"/conversations/{_UUID}/messages/{_UUID}/delete"),
    ("POST", f"/conversations/{_UUID}/messages/{_UUID}/feedback"),
    ("GET", f"/conversations/{_UUID}/name"),
    ("POST", f"/conversations/{_UUID}/name"),
    ("POST", f"/conversations/{_UUID}/is_pinned"),
    # ---- 17. 语音转换模块 ----
    ("POST", "/audio/audio_to_text"),
    ("POST", "/audio/message_to_audio"),
    # ---- 18. skill模块 ----
    ("POST", "/skill/upload"),
    ("GET", "/skill/skills"),
    ("GET", f"/skill/{_UUID}"),
    ("GET", f"/skill/skill_detail/{_UUID}"),
    ("POST", f"/skill/{_UUID}/delete"),
    ("POST", f"/skill/{_UUID}/visibility"),
    ("GET", f"/skill/{_UUID}/download"),
    # ---- 21. weaviate 模块 ----
    ("POST", "/weaviate/vector/recall"),
    ("POST", "/weaviate/vector/delete"),
    ("GET", "/weaviate/vector/collections"),
    ("GET", "/weaviate/vector/all"),
    ("GET", "/weaviate/vector/all/dataset"),
    ("GET", "/weaviate/vector/documents"),
    ("GET", "/weaviate/vector/segments"),
    ("GET", "/weaviate/vector/metadata"),
]

# bp 蓝图内【公开】路由（旧 Flask 代码这些 handler 无 @login_required；
# 明确 password_login/get_builtin_tools/provider 等不应强制认证；route-inventory 的"bp→认证"
# 是蓝图归属的简化标记，与实际认证面不符）。无 token 请求 → 200 + 正常业务响应（非 unauthorized）。
BP_PUBLIC_ROUTES = [
    # 内置插件广场（get_builtin_tools/get_categories/get_provider_icon/get_provider_tool）
    ("GET", "/builtin_tools"),
    ("GET", f"/builtin_tools/{_STR_PARAM}/tools/{_STR_PARAM}"),
    ("GET", f"/builtin_tools/{_STR_PARAM}/icon"),
    ("GET", "/builtin_tools/categories"),
    # 授权认证（provider 查询 / 授权入口 / 登录）
    ("GET", f"/oauth/{_STR_PARAM}"),
    ("POST", f"/oauth/authorize/{_STR_PARAM}"),
    ("POST", "/auth/password_login"),
    # 语言模型图标（公开获取）
    ("GET", f"/language_models/{_STR_PARAM}/icon"),
    # chroma 文件/向量管理（旧遗留模块，无认证）
    ("GET", "/chroma/list"),
    ("POST", "/chroma/upload"),
    ("GET", "/chroma/download"),
    ("POST", "/chroma/delete"),
    ("GET", "/chroma/vector"),
    ("GET", f"/chroma/{_STR_PARAM}/vector"),
    ("POST", "/chroma/vector/add_vector"),
    ("POST", f"/chroma/{_STR_PARAM}/update_vector"),
    ("POST", f"/chroma/{_STR_PARAM}/delete_vector"),
    ("POST", "/chroma/vector/clear"),
    ("POST", "/chroma/vector/recall"),
    ("POST", "/chroma/vector/sync"),
]

# openapi 蓝图路由（需要 api_key 认证）→ 无 token → 同样 200 + unauthorized
OPENAPI_AUTH_ROUTES = [
    ("POST", "/openapi/chat"),
]

# 公开路由（无认证，直接 200 + 正确响应）
PUBLIC_ROUTES = [
    ("POST", "/webhook"),           # feishu webhook
    ("GET", "/favicon.ico"),        # 204 No Content
    ("GET", "/default-app-icon"),   # 200 image/png
    ("GET", "/healthz"),            # 200 {"status":"ok"}
    ("GET", "/docs"),               # Swagger UI 200
]

# 所有认证路由（需要 unauthorized 验证）
ALL_AUTH_ROUTES = LLMOPS_AUTH_ROUTES + OPENAPI_AUTH_ROUTES

# 黄金 401 shape
GOLDEN_401 = {
    "code": "unauthorized",
    "data": {},
    "message": "该接口需要授权才能访问，请登录后尝试",
}


def _route_id(route):
    """生成参数化测试 ID。"""
    method, path = route
    return f"{method}:{path}"


class TestContract401:
    """153 路由未认证冒烟（黄金契约对照）。

    所有 llmops/openapi 蓝图路由无 token 请求 → HTTP 200 + code=unauthorized。
    逐字段对照 golden 401-shape.json 的 code/message/data 结构。
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("route", ALL_AUTH_ROUTES, ids=[_route_id(r) for r in ALL_AUTH_ROUTES])
    async def test_auth_route_requires_token(self, route, live_client):
        """认证路由无 token → HTTP 200 + code=unauthorized（黄金契约）。"""
        method, path = route
        resp = await live_client.request(method, path)
        # 契约：HTTP 200 + body code=unauthorized
        assert resp.status_code == 200, f"{method} {path}: expected 200, got {resp.status_code}"
        body = resp.json()
        assert body["code"] == GOLDEN_401["code"], f"{method} {path}: code={body['code']}"
        assert body["message"] == GOLDEN_401["message"], f"{method} {path}: message={body['message']}"
        assert body["data"] == GOLDEN_401["data"], f"{method} {path}: data={body['data']}"

    @pytest.mark.asyncio
    async def test_total_auth_routes_count(self):
        """断言认证路由总数与 route-inventory 一致（剔除 bp 蓝图内 20 条公开路由）。

        route-inventory: 156 条路由总计（新增 /web_apps/plugin/bootstrap 兜底接口）。
        - bp 蓝图：153 条；其中 20 条 handler 无 @login_required（builtin_tools/oauth/login/
          language_models icon/chroma，见 BP_PUBLIC_ROUTES）→ 认证 134 条
        - openapi_bp 蓝图：2 条（/openapi/chat → api_key 认证；/webhook → 公开）
        认证路由 = 134 + 1 = 135 条。
        bp 公开路由 = 20 条；总公开（156 内）= 20 + 1（/webhook）= 21 条。
        app 级新增公开路由（不在 156 内）：/healthz、/favicon.ico、/default-app-icon、/docs。
        """
        assert len(ALL_AUTH_ROUTES) == 135, f"Expected 135 auth routes, got {len(ALL_AUTH_ROUTES)}"
        assert len(LLMOPS_AUTH_ROUTES) + len(OPENAPI_AUTH_ROUTES) == 135
        assert len(BP_PUBLIC_ROUTES) == 20

    @pytest.mark.asyncio
    @pytest.mark.parametrize("route", BP_PUBLIC_ROUTES, ids=[_route_id(r) for r in BP_PUBLIC_ROUTES])
    async def test_bp_public_route_no_auth_required(self, route, live_client):
        """bp 蓝图内公开路由（旧代码无 @login_required）无 token → 200 + 正常业务响应
        （非 unauthorized——不应强制认证）。"""
        method, path = route
        resp = await live_client.request(method, path, json={})
        assert resp.status_code == 200, f"{method} {path}: expected 200, got {resp.status_code}"
        body = resp.json()
        assert body["code"] != GOLDEN_401["code"], f"{method} {path}: 不应强制认证，实际 unauthorized"


class TestPublicRoutes:
    """公开路由直接可访问（无认证）。

    公开路由：
    - /webhook（feishu 回调）→ 200 + 正确响应
    - /favicon.ico → 204 No Content
    - /default-app-icon → 200 image/png
    - /healthz → 200 {"status":"ok"}
    - /docs → 200
    """

    @pytest.mark.asyncio
    async def test_webhook_public(self, live_client):
        """webhook 公开路由无认证 → 200（url_verification 或空 body）。"""
        resp = await live_client.post("/webhook", json={"type": "url_verification", "challenge": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("code") == "success"

    @pytest.mark.asyncio
    async def test_favicon(self, live_client):
        """favicon 204 No Content。"""
        resp = await live_client.get("/favicon.ico")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_default_app_icon(self, live_client):
        """default-app-icon → 200 image/png 二进制。"""
        resp = await live_client.get("/default-app-icon")
        assert resp.status_code == 200
        assert "image/png" in resp.headers.get("content-type", "")
        assert len(resp.content) > 0

    @pytest.mark.asyncio
    async def test_healthz(self, live_client):
        """healthz → 200 {"status":"ok"}。"""
        resp = await live_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_docs_accessible(self, live_client):
        """Swagger UI /docs 可访问。"""
        resp = await live_client.get("/docs")
        assert resp.status_code == 200
