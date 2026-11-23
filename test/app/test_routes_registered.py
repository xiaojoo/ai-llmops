"""测试 FastAPI 路由注册。

验证：
1. /openapi.json 包含基本路径
2. llmops 路由有 get_current_user 依赖
3. openapi 路由有 get_api_key_account 依赖
4. /webhook 无认证依赖（公开路由）
5. /favicon.ico、/default-app-icon、/healthz 无认证依赖
"""
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# 将 scripts/migration 加入 path 以使用共享 inventory 工具
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "migration"))
from inventory import convert_path, parse_inventory

from app.http.app import app
from internal.server.deps import get_api_key_account, get_current_user


@pytest.fixture
def client():
    """创建测试客户端（不触发 lifespan，中间态下 handler 有旧 Flask 导入）。"""
    return TestClient(app, raise_server_exceptions=False)


def _flatten_api_routes(routes) -> list[APIRoute]:
    """递归摊平路由表。

    fastapi 0.141 / starlette 1.6 的 include_router **不再把子路由拍平进 app.routes**，
    而是挂成 `_IncludedRouter`（真路由在它的 `original_router.routes` 里）。
    只按 `isinstance(r, APIRoute)` 扫 app.routes 的话，166 条业务路由一条都看不见
    ——实测摊平前 4 条、摊平后 170 条。
    """
    flat: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            flat.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            flat.extend(_flatten_api_routes(inner.routes))
    return flat


def _route_dependencies(route: APIRoute) -> set:
    """取这条路由**实际会执行**的全部依赖 callable。

    `route.dependencies` 只有路由级那几条；handler 参数级的
    `user: ApiKeyUser = Depends(get_api_key_account)` 只在 `route.dependant` 树里。
    鉴权判据必须走 dependant，否则会误判成"没挂认证"。
    """
    out: set = set()

    def walk(dep) -> None:
        call = getattr(dep, "call", None) or getattr(dep, "dependency", None)
        if call is not None:
            out.add(call)
        for sub in getattr(dep, "dependencies", []) or []:
            walk(sub)

    for d in getattr(route, "dependencies", []) or []:
        walk(d)
    walk(route.dependant)
    return out


def _get_route_by_path_and_method(path: str, method, routes=None) -> APIRoute | None:
    """从（摊平后的）路由表里查找匹配路径和方法的 APIRoute。"""
    for route in _flatten_api_routes(routes if routes is not None else app.routes):
        if route.path == path and method in route.methods:
            return route
    return None


def _route_depends_on(route: APIRoute, dep_func) -> bool:
    """检查路由的依赖（含路由级与 handler 参数级）是否包含指定依赖函数。"""
    return dep_func in _route_dependencies(route)


@pytest.fixture(scope="module")
def registered_app():
    """一个只用于查表的干净 app：直接把路由注册上去，不碰全局 app、也不进 lifespan。

    业务路由是在 lifespan 第 6 步注册的，而本文件的 client 故意不触发 lifespan，
    所以断言"某条业务路由挂了什么依赖"必须自己注册一份，否则查不到的一律是 None。
    """
    from fastapi import FastAPI

    from internal.router.router import register_routes_from_container

    target = FastAPI()
    register_routes_from_container(app=target)
    return target


class TestRoutesRegistered:
    """路由注册测试类。"""

    def test_openapi_json_accessible(self, client):
        """/openapi.json 应可访问。"""
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_llmops_router_configured_with_auth(self):
        """llmops 路由应通过 handler 参数级 CurrentUser 注入认证。

        路由在 lifespan 内通过 register_routes_from_container(session, app=app) 直接注册。
        认证由 handler 方法的 user: CurrentUser = Depends(get_current_user) 参数注入。
        """
        app_py = Path(__file__).resolve().parents[2] / "app" / "http" / "app.py"
        app_source = app_py.read_text(encoding="utf-8")
        assert "register_routes_from_container" in app_source, "app.py 缺少 register_routes_from_container 调用"

    def test_openapi_router_configured_with_auth(self):
        """openapi 路由应通过 handler 参数级 ApiKeyUser 注入认证。

        认证由 handler 方法的 user: ApiKeyUser = Depends(get_api_key_account) 参数注入。
        """
        deps_py = Path(__file__).resolve().parents[2] / "internal" / "server" / "deps.py"
        deps_source = deps_py.read_text(encoding="utf-8")
        assert "ApiKeyUser" in deps_source, "deps.py 缺少 ApiKeyUser 类型别名"

    def test_openapi_routes_have_api_key_dependency(self, registered_app):
        """openapi 路由（/openapi/chat）必须真的挂上 get_api_key_account。

        此前这里查不到路由就 pytest.skip("中间态下…")，理由写错了：查不到是因为
        1) client fixture 不触发 lifespan，业务路由没注册；
        2) 就算注册了，旧的查找法只扫 app.routes 里的 APIRoute，而 fastapi 0.141 把
           include_router 的路由藏进 `_IncludedRouter`——166 条业务路由一条都扫不到。
        两头叠起来让这条鉴权守卫永久没执行。现在自己注册一份干净 app，查不到就是失败。
        """
        route = _get_route_by_path_and_method("/openapi/chat", "POST", registered_app.routes)
        assert route is not None, "POST /openapi/chat 未注册（路由登记被改动过？）"
        assert _route_depends_on(route, get_api_key_account), \
            "POST /openapi/chat 缺少 get_api_key_account 依赖（路由级或 handler 参数级）"

    def test_lookup_distinguishes_openapi_from_llmops_auth(self, registered_app):
        """反证用的对照：同一条查找法必须能分辨 openapi 与 llmops 两套认证。

        只看 /openapi/chat 有 api-key 不够——依赖摊平若写坏了，两条断言会一起变绿。
        """
        openapi_route = _get_route_by_path_and_method("/openapi/chat", "POST", registered_app.routes)
        llmops_route = _get_route_by_path_and_method("/apps", "POST", registered_app.routes)
        assert openapi_route is not None and llmops_route is not None, "路由摊平没生效"
        assert _route_depends_on(llmops_route, get_current_user), "/apps 应走 get_current_user"
        assert not _route_depends_on(llmops_route, get_api_key_account), \
            "/apps 不应挂 api-key——两条路由依赖集合相同说明量具是坏的"
        assert not _route_depends_on(openapi_route, get_current_user), \
            "/openapi/chat 不应挂 JWT——同上"

    def test_webhook_is_public_route(self, client):
        """/webhook 应为公开路由（无认证依赖）。"""
        # /webhook 在 app.py 顶层直接定义，不在 llmops/openapi router 中
        route = _get_route_by_path_and_method("/webhook", "POST")
        assert route is not None, "/webhook 路由不存在"
        # 公开路由不应有 get_current_user 或 get_api_key_account 依赖
        assert not _route_depends_on(route, get_current_user), \
            "/webhook 不应有 get_current_user 依赖"
        assert not _route_depends_on(route, get_api_key_account), \
            "/webhook 不应有 get_api_key_account 依赖"

    def test_favicon_and_default_icon_are_public(self, client):
        """/favicon.ico 和 /default-app-icon 应为公开路由（无认证依赖）。"""
        for path, method in [("/favicon.ico", "GET"), ("/default-app-icon", "GET")]:
            route = _get_route_by_path_and_method(path, method)
            assert route is not None, f"{method} {path} 路由不存在"
            assert not _route_depends_on(route, get_current_user), \
                f"{path} 不应有 get_current_user 依赖"
            assert not _route_depends_on(route, get_api_key_account), \
                f"{path} 不应有 get_api_key_account 依赖"

    def test_healthz_is_public(self, client):
        """/healthz 应为公开路由（无认证依赖）。"""
        route = _get_route_by_path_and_method("/healthz", "GET")
        assert route is not None, "GET /healthz 路由不存在"
        assert not _route_depends_on(route, get_current_user), \
            "/healthz 不应有 get_current_user 依赖"
        assert not _route_depends_on(route, get_api_key_account), \
            "/healthz 不应有 get_api_key_account 依赖"
