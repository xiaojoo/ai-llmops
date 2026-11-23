#!/usr/bin/env python
"""全量门禁：internal/ 全量 + package/ 禁止 flask / werkzeug / flask_weaviate / injector 导入。

扫描范围：internal/（全量）+ package/
豁免清单：internal/handler、internal/router、internal/schema、app/http、
         internal/task、internal/migrations、package/response（frozen）

断言：
1. 扫描范围内无 flask/werkzeug/flask_weaviate/injector 导入
2. app/http/module.py 已删除
3. package/sqlalchemy/ 目录已删除
4. internal/extension/ 目录已删除（旧的，internal/extensions/ 复数保留）
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # 仓库根

# 扫描范围：internal/ 全量 + package/（排除豁免后）
SCAN_DIRS = ["internal", "package"]

# 豁免目录（这些目录下的文件不扫描）
EXEMPT_DIRS = {
    "internal/handler",
    "internal/router",
    "internal/schema",
    "internal/task",
    "internal/migrations",
    "internal/server",
    "package/response",
    "package/paginator",  # PaginatorReq(FlaskForm) 冻结
    "app/http",
    "internal/middleware",
}

# 与全量门禁 grep 模式对齐
# \binjector\.\w+ 防 injector.Injector/Module 引用漏网
FORBIDDEN_PATTERNS = [
    re.compile(r"^\s*from flask(?:\.|\s|_)"),
    re.compile(r"^\s*import flask\b"),
    re.compile(r"^\s*from werkzeug\b"),
    re.compile(r"^\s*from flask_weaviate\b"),
    re.compile(r"^\s*from injector\b"),
    re.compile(r"^\s*import injector\b"),
    re.compile(r"^\s*@inject\b"),
    re.compile(r"\binjector\.\w+"),
]


def _is_exempt(py: Path) -> bool:
    """检查文件是否在豁免目录下"""
    rel = py.relative_to(ROOT).as_posix()
    return any(rel.startswith(exempt) for exempt in EXEMPT_DIRS)


def _iter_py_files():
    for rel in SCAN_DIRS:
        base = ROOT / rel
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            parts = py.relative_to(ROOT).parts
            if "test" in parts or py.name.startswith("test_"):
                continue
            if _is_exempt(py):
                continue
            yield py


def _violations() -> list[str]:
    hits = []
    for py in _iter_py_files():
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), start=1):
            # 跳过纯注释行
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(pattern.search(line) for pattern in FORBIDDEN_PATTERNS):
                hits.append(f"{py.relative_to(ROOT).as_posix()}:{lineno}: {line.strip()}")
    return hits


def test_no_flask_werkzeug_flask_weaviate_injector_imports():
    """internal/ + package/ 不得出现 flask/werkzeug/flask_weaviate/injector 导入（豁免清单外）"""
    hits = _violations()
    assert not hits, (
        "扫描范围内存在 flask/werkzeug/flask_weaviate/injector 导入:\n"
        + "\n".join(hits)
    )


def test_module_py_deleted():
    """app/http/module.py（injector 容器）已删除"""
    module_py = ROOT / "app" / "http" / "module.py"
    assert not module_py.exists(), f"app/http/module.py 仍存在，请删除"


def test_package_sqlalchemy_deleted():
    """package/sqlalchemy/ 目录已删除"""
    sqlalchemy_dir = ROOT / "package" / "sqlalchemy"
    assert not sqlalchemy_dir.exists(), f"package/sqlalchemy/ 仍存在，请删除"


def test_internal_extension_deleted():
    """internal/extension/ 目录已删除（旧的，internal/extensions/ 复数保留）"""
    extension_dir = ROOT / "internal" / "extension"
    assert not extension_dir.exists(), f"internal/extension/ 仍存在，请删除"
    # 确认复数 extensions 仍存在
    extensions_dir = ROOT / "internal" / "extensions"
    assert extensions_dir.exists(), "internal/extensions/（复数）应保留"
