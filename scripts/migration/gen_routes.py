#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析 route-inventory.md 路由清单，生成登记参考清单。

读取 docs/migration/route-inventory.md 的 153 条路由清单，
按蓝图分组统计并打印参考清单供手工核对。

蓝图→APIRouter 映射：
- bp → llmops_router（Depends(get_current_user)）
- openapi_bp → openapi_router（Depends(get_api_key_account)）

公开路由（/webhook、/favicon.ico、/default-app-icon）不进认证 router。
"""
from pathlib import Path

from inventory import convert_path, parse_inventory

OUTPUT = Path("internal/router/router.py")


def main():
    routes = parse_inventory()
    print(f"解析到 {len(routes)} 条路由")

    # 统计
    bp_count = sum(1 for b, _, _, _ in routes if b == "bp")
    openapi_count = sum(1 for b, _, _, _ in routes if b == "openapi_bp")
    print(f"  bp 蓝图: {bp_count} 条")
    print(f"  openapi_bp 蓝图: {openapi_count} 条")

    # 打印路由清单供核对
    print("\n路由清单:")
    for bp, method, path, handler in routes:
        fastapi_path = convert_path(path)
        print(f"  {bp:12s} {method:6s} {fastapi_path:60s} {handler}")


if __name__ == "__main__":
    main()
