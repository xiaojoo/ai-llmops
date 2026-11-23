"""冻结前采集旧 Flask 应用的响应结构样例（契约基线）。"""
import json
from pathlib import Path

import requests

BASE = "http://127.0.0.1:5000"
OUT = Path("docs/migration/golden")
OUT.mkdir(parents=True, exist_ok=True)


def dump(name: str, resp: requests.Response) -> None:
    payload = {"status_code": resp.status_code, "headers": dict(resp.headers), "body": resp.text}
    (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{name}: status={resp.status_code} body={resp.text[:200]}")


def main() -> None:
    dump("401-shape", requests.get(f"{BASE}/apps"))            # 无 token，认证中间件拦截
    dump("ping", requests.get(f"{BASE}/ping"))                 # 健康检查
    dump("default-app-icon", requests.get(f"{BASE}/default-app-icon"))


if __name__ == "__main__":
    main()
