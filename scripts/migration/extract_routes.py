"""从 internal/router/router.py 提取路由清单（AST 解析，无需运行时）。

蓝图名映射：_llmops → bp，_openapi → openapi_bp。
"""
import ast
from pathlib import Path

ROUTER = Path("internal/router/router.py")
OUT = Path("docs/migration/route-inventory.md")

# _register_routes 内的局部变量名 → 蓝图名映射
_VAR_TO_BP = {
    "_llmops": "bp",
    "_openapi": "openapi_bp",
    "llmops_router": "bp",
    "openapi_router": "openapi_bp",
}


def extract(router: str | Path = ROUTER) -> list[tuple[str, str, str, str]]:
    """提取 add_api_route / add_url_rule 路由清单。

    router 为 Path 时按文件读取；为 str 时视为源码字符串（便于测试注入合成源码）。
    """
    source = router.read_text(encoding="utf-8") if isinstance(router, Path) else router
    tree = ast.parse(source)
    routes: list[tuple[str, str, str, str]] = []  # (blueprint, method, path, view)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("add_api_route", "add_url_rule"):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        var_name = node.func.value.id
        bp_name = _VAR_TO_BP.get(var_name, var_name)
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}

        # 解析 path（第一个位置参数或 rule= 关键字）
        rule = kwargs.get("rule") or kwargs.get("path") or (node.args[0] if node.args else None)

        # 解析 view_func / handler（第二个位置参数或关键字）
        view = kwargs.get("view_func") or (node.args[1] if len(node.args) > 1 else None)

        if not isinstance(rule, ast.Constant):
            raise ValueError(
                f"无法解析 {var_name}.{node.func.attr}（第 {node.lineno} 行）: "
                f"rule={type(rule).__name__}"
            )

        # view 可以是 ast.Attribute（handler.method）或 ast.Name
        if isinstance(view, ast.Attribute):
            view_name = view.attr
        elif isinstance(view, ast.Name):
            view_name = view.id
        else:
            raise ValueError(
                f"无法解析 {var_name}.{node.func.attr} view（第 {node.lineno} 行）: "
                f"view={type(view).__name__}"
            )

        # 解析 methods
        methods = kwargs.get("methods")
        if methods is None:
            routes.append((bp_name, "GET", rule.value, view_name))
        elif isinstance(methods, (ast.List, ast.Tuple)):
            for elt in methods.elts:
                if not isinstance(elt, ast.Constant):
                    raise ValueError(
                        f"无法解析 {var_name}.{node.func.attr} methods 元素（第 {node.lineno} 行）"
                    )
                routes.append((bp_name, elt.value, rule.value, view_name))
        else:
            raise ValueError(
                f"无法解析 {var_name}.{node.func.attr} methods（第 {node.lineno} 行）"
            )
    return routes


def main() -> None:
    routes = extract()
    lines = [
        "# 路由清单（Flask → FastAPI 契约基线）",
        "",
        "| 蓝图 | 方法 | 路径 | Handler 方法 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {b} | {m} | {p} | {v} |" for b, m, p, v in sorted(routes)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"提取 {len(routes)} 条路由 -> {OUT}")


if __name__ == "__main__":
    main()
