import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

print("starting backend...", flush=True)
from app.http.app import app

print("app imported, running (debug=False)...", flush=True)
# 非 debug 模式：避免 reloader 因工作区文件变化（用户正在开发 workflow）反复重启崩溃
app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
