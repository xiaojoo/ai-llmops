#!/usr/bin/env python
"""门禁：internal/model 层必须为纯 ORM（无 db.session / db.auto_commit / current_app / UserMixin / flask / werkzeug）。

模型内查库属性（@property 内 db.session / current_app / auto_commit）
全部上移服务层（映射登记 docs/migration/model-session-callers.md）；UserMixin 一并移除。
本文件级门禁；全量门禁见 test/migration/test_no_flask_imports.py（@pytest.mark.slow）。
"""
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[3] / "internal" / "model"

# 控制器裁定：模型文件不得包含这些令牌（grep 级断言）
FORBIDDEN_TOKENS = [
    "db.session",
    "db.auto_commit",
    "current_app",
    "UserMixin",
    "from flask",
    "from werkzeug",
    "import flask",
    "import werkzeug",
]


def test_model_layer_has_no_session_or_flask_references():
    sources = sorted(MODEL_DIR.glob("*.py"))
    assert sources, "internal/model 目录下应有模型文件"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            assert token not in text, (
                f"{path.name} 仍包含 {token!r}——模型层禁止查库/flask 依赖"
                f"（属性已上移服务层，登记 model-session-callers.md）"
            )
