"""路由提取脚本测试（add_url_rule → add_api_route）。"""
import ast
from pathlib import Path

import pytest

from scripts.migration.extract_routes import extract


def test_extract_counts():
    routes = extract()
    assert len(routes) >= 150


def test_extract_matches_call_sites():
    """提取数量应与 router.py 中的 add_api_route 调用数量一致。"""
    router = Path("internal/router/router.py")
    tree = ast.parse(router.read_text(encoding="utf-8"))
    call_sites = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("add_api_route", "add_url_rule")
    )
    assert len(extract(router)) == call_sites


def test_extract_known_routes():
    routes = extract()
    keys = {(bp, m, p) for bp, m, p, _ in routes}
    assert ("bp", "GET", "/ping") in keys
    assert ("bp", "POST", "/apps") in keys
    assert ("openapi_bp", "POST", "/openapi/chat") in keys


def test_extract_tuple_methods():
    """add_api_route + methods tuple → 每个 method 一条路由。"""
    src = '_llmops.add_api_route("/x", self.h.x, methods=["GET", "POST"])\n'
    routes = extract(src)
    assert ("bp", "GET", "/x", "x") in routes
    assert ("bp", "POST", "/x", "x") in routes
    assert len(routes) == 2


def test_extract_raises_on_unparseable():
    """第一个位置参数非字符串常量 → ValueError。"""
    with pytest.raises(ValueError):
        extract("_llmops.add_api_route(rule_var, self.h.x)\n")
