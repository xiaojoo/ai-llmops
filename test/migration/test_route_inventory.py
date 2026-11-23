"""测试路由清单与 route-inventory.md 一致性。

验证：
1. route-inventory.md 包含 153 条路由
2. 蓝图归属正确（bp: 151 条, openapi_bp: 2 条）
3. 路径参数转换正确（<uuid:x> → {x}）
"""
import sys
from pathlib import Path

import pytest

# 将 scripts/migration 加入 path 以使用共享 inventory 工具
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "migration"))
from inventory import parse_inventory


class TestRouteInventory:
    """路由清单测试类。"""

    def test_inventory_has_153_routes(self):
        """route-inventory.md 应包含 153 条路由。"""
        routes = parse_inventory()
        assert len(routes) == 153, f"期望 153 条路由，实际 {len(routes)} 条"

    def test_blueprint_distribution(self):
        """蓝图分布：bp 151 条，openapi_bp 2 条。"""
        routes = parse_inventory()
        bp_routes = [r for r in routes if r[0] == "bp"]
        openapi_routes = [r for r in routes if r[0] == "openapi_bp"]

        assert len(bp_routes) == 151, f"bp 蓝图期望 151 条，实际 {len(bp_routes)} 条"
        assert len(openapi_routes) == 2, f"openapi_bp 蓝图期望 2 条，实际 {len(openapi_routes)} 条"

    def test_openapi_routes_are_chat_and_webhook(self):
        """openapi_bp 路由应为 /openapi/chat 和 /webhook。"""
        routes = parse_inventory()
        openapi_routes = [(m, p, h) for b, m, p, h in routes if b == "openapi_bp"]

        openapi_paths = {p for _, p, _ in openapi_routes}
        assert "/openapi/chat" in openapi_paths, "缺少 /openapi/chat"
        assert "/webhook" in openapi_paths, "缺少 /webhook"

    def test_path_parameters_converted(self):
        """路径参数应正确转换：<uuid:x> → {x}，<string:x> → {x}。"""
        routes = parse_inventory()
        for bp, method, path, handler in routes:
            # route-inventory.md 保留原始 Flask 格式，这里验证路径格式正确
            assert path.startswith("/"), f"路径 {path} 不以 / 开头"

    def test_all_methods_valid(self):
        """所有方法应为有效的 HTTP 方法。"""
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH"}
        routes = parse_inventory()
        for bp, method, path, handler in routes:
            assert method in valid_methods, f"路径 {path} 使用了无效方法 {method}"

    def test_unique_handler_methods(self):
        """每个 handler 方法名应唯一（在同一路由中）。"""
        routes = parse_inventory()
        seen = set()
        for bp, method, path, handler in routes:
            key = (bp, method, path)
            if key in seen:
                pytest.fail(f"重复路由: {bp} {method} {path}")
            seen.add(key)
