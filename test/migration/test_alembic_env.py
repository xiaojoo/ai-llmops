import importlib
import sys


def test_env_imports_without_flask_app():
    # 移除 flask 应用上下文相关符号依赖：env.py 顶层不得再 import flask
    import internal.migrations.env as env  # noqa: F401
    source = open("internal/migrations/env.py", encoding="utf-8").read()
    assert "from flask" not in source
    assert "current_app" not in source
