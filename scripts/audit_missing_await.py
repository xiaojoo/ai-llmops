#!/usr/bin/env python
"""审计 v2：定位项目内"真·未 await 的协程调用"。

策略（降低误报）：
- 收集每个文件定义的 async 函数；每个类定义的 async 方法（含项目内基类，如 BaseService）
- 未 await 判定：Call 的父链不含 Await/AsyncFor/AsyncWith/异步推导，且不在 create_task/gather 等包裹内
- 命中分两类：
    A. 裸调用 name(...)：name 为本项目 async 函数（排除内建名）
    B. self.name(...)：name 为当前类或其项目内基类的 async 方法
    C. obj.name(...)：obj 非 self —— 仅当 name 为本项目某类 async 方法时低置信提示（需人工核对）
"""
import ast
import os

ROOT = r"H:\ai-code-llmops"
INCLUDE_DIRS = {"internal", "package", "app", "scripts", "test", "config"}
SKIP_DIRS = {"venv", ".git", "node_modules", ".idea", "__pycache__", ".dsh", "docs",
             ".superpowers", "tmp", "storage", "deploy", "tencentdb_agent_memory", "study"}

BUILTIN_NAMES = {
    "list", "dict", "set", "tuple", "str", "int", "float", "bool", "bytes", "bytearray",
    "sorted", "map", "filter", "sum", "len", "next", "iter", "min", "max", "all", "any",
    "enumerate", "zip", "reversed", "range", "print", "repr", "format", "vars", "type",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "object", "super",
    "open", "input", "id", "hash", "abs", "round", "divmod", "pow", "ord", "chr",
    "bin", "oct", "hex", "slice", "staticmethod", "classmethod", "property", "globals", "locals",
}

AWAIT_WRAPPERS = {"create_task", "gather", "ensure_future", "TaskGroup", "wait",
                  "run", "run_until_complete"}

module_async_fns = {}      # name -> set(files)
class_async_methods = {}   # class name -> set(method names)
class_bases = {}           # class name -> list(base names)


def collect(tree, fname):
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            # async generator（含 yield）调用返回生成器，由 async for/__anext__ 消费，不纳入
            if not any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(node)):
                module_async_fns.setdefault(node.name, set()).add(fname)
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and not any(
                    isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(item)
                ):
                    class_async_methods.setdefault(node.name, set()).add(item.name)
            class_bases[node.name] = [
                b.id for b in node.bases if isinstance(b, ast.Name)
            ]


def is_consumed(node):
    """该 Call 的协程是否被 await / async for / async with / 异步推导消费。"""
    p = node
    while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module, ast.ClassDef)):
        if isinstance(p, ast.Await):
            return True
        if isinstance(p, ast.AsyncFor) and p.iter is node:
            return True
        if isinstance(p, ast.AsyncWith) and any(item.context_expr is node for item in p.items):
            return True
        if isinstance(p, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for g in p.generators:
                if g.iter is node and isinstance(g, ast.comprehension) and getattr(g, "is_async", False):
                    return True
        if isinstance(p, ast.Call) and p is not node:
            fname = getattr(p.func, "attr", None) or getattr(p.func, "id", None)
            if fname in AWAIT_WRAPPERS:
                return True
            return False
        p = getattr(p, "parent", None)
    return False


def async_in_bases(cls_name, method, memo=None):
    """当前类或其项目基类链上是否定义了 async 方法 method。"""
    memo = memo if memo is not None else set()
    if cls_name in memo:
        return False
    memo.add(cls_name)
    if cls_name in class_async_methods and method in class_async_methods[cls_name]:
        return True
    for base in class_bases.get(cls_name, []):
        if async_in_bases(base, method, memo):
            return True
    return False


def analyze(fname, tree):
    parent_map = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node
    for node in ast.walk(tree):
        setattr(node, "parent", parent_map.get(node))

    enclosing_class = {}

    def walk_ctx(n, cls=None):
        if isinstance(n, ast.ClassDef):
            cls = n.name
        for child in ast.iter_child_nodes(n):
            walk_ctx(child, cls)
        if cls is not None and isinstance(n, ast.ClassDef):
            enclosing_class[id(n)] = cls

    walk_ctx(tree)

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if is_consumed(node):
            continue
        func = node.func
        # 定位所在类
        cls = None
        cur = node
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = getattr(cur, "parent", None)
        while cur is not None and not isinstance(cur, ast.ClassDef):
            cur = getattr(cur, "parent", None)
        if isinstance(cur, ast.ClassDef):
            cls = cur.name

        if isinstance(func, ast.Name):
            name = func.id
            if name in BUILTIN_NAMES:
                continue
            if name in module_async_fns:
                src = ast.get_source_segment(open(fname, encoding="utf-8").read(), node) or ""
                hits.append((fname, node.lineno, " ".join(src.split())[:90], name, "A-bare"))
        elif isinstance(func, ast.Attribute):
            name = func.attr
            if isinstance(func.value, ast.Name) and func.value.id == "self":
                if cls and async_in_bases(cls, name):
                    src = ast.get_source_segment(open(fname, encoding="utf-8").read(), node) or ""
                    hits.append((fname, node.lineno, " ".join(src.split())[:90], name, "B-self"))
            else:
                # C 类：外部接收者，仅当方法名是本项目某类的 async 方法时提示
                if name in class_async_methods:
                    src = ast.get_source_segment(open(fname, encoding="utf-8").read(), node) or ""
                    hits.append((fname, node.lineno, " ".join(src.split())[:90], name, "C-obj"))

    return hits


def main():
    all_hits = []
    for dirname in INCLUDE_DIRS:
        base = os.path.join(ROOT, dirname)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    src = open(fp, encoding="utf-8").read()
                    tree = ast.parse(src)
                except Exception:
                    continue
                collect(tree, fp)
    for dirname in INCLUDE_DIRS:
        base = os.path.join(ROOT, dirname)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    src = open(fp, encoding="utf-8").read()
                    tree = ast.parse(src)
                except Exception:
                    continue
                all_hits.extend(analyze(fp, tree))

    seen, out = set(), []
    for f, line, src, name, cat in all_hits:
        key = (f, line, name)
        if key in seen:
            continue
        seen.add(key)
        out.append((f, line, src, name, cat))
    out.sort(key=lambda x: (x[0], x[1]))
    print(f"=== 疑似未 await 的调用: {len(out)} 处 ===")
    for f, line, src, name, cat in out:
        print(f"[{cat}] {os.path.relpath(f, ROOT)}:{line}: {src}")


if __name__ == "__main__":
    main()
