"""共享的路由清单解析工具。

从 docs/migration/route-inventory.md 解析 153 条路由清单，
提供 parse_inventory() 和 convert_path() 给 gen_routes.py 和测试共用。
"""
import re
from pathlib import Path

INVENTORY = Path("docs/migration/route-inventory.md")


def parse_inventory(path: Path = INVENTORY) -> list[tuple[str, str, str, str]]:
    """解析 route-inventory.md，返回 (blueprint, method, path, handler_method) 列表。

    每行格式: | bp | GET | /path | handler_method |
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    routes = []
    for line in lines:
        match = re.match(
            r'\|\s*(bp|openapi_bp)\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|',
            line,
        )
        if match:
            bp, method, path_str, handler = match.groups()
            routes.append((bp, method, path_str, handler))
    return routes


def convert_path(flask_path: str) -> str:
    """Flask 路径参数 → FastAPI 路径参数：<uuid:x> → {x}，<string:x> → {x}"""
    path = re.sub(r'<uuid:(\w+)>', r'{\1}', flask_path)
    path = re.sub(r'<string:(\w+)>', r'{\1}', path)
    return path
