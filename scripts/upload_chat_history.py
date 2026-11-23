#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : upload_chat_history.py

把生成的历史对话文档上传到指定知识库，并触发 Celery 建索引，然后做召回测试。

用法：
    python scripts/upload_chat_history.py [--dataset-id <uuid>] [--file scripts/_chat_history.md] [--query "你能安装skill吗"]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = "http://localhost:5000"
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
if not EMAIL or not PASSWORD:
    raise RuntimeError("请设置 EMAIL 和 PASSWORD 环境变量")
# 默认知识库：功能测试
DEFAULT_DATASET = "be2f9b05-805d-46d2-a01b-b2292f1b7da5"


def login() -> str:
    req = urllib.request.Request(
        f"{API}/auth/password_login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode())
    if body.get("code") != "success":
        raise RuntimeError(f"登录失败: {body}")
    return body["data"]["access_token"]


def api_request(method: str, url: str, token: str, body=None, multipart=None):
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if multipart is not None:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        parts = []
        for field, (filename, content, ctype) in multipart.items():
            header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode()
            parts.append(header)
            if isinstance(content, str):
                parts.append(content.encode("utf-8"))
            else:
                parts.append(content)
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description="上传历史对话文档到知识库")
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET)
    parser.add_argument("--file", default="scripts/_chat_history.md")
    parser.add_argument("--query", default="你能安装skill吗")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"文档不存在: {file_path}")
        sys.exit(1)

    token = login()
    print(">>> 登录成功")

    # 1、上传文件
    print(">>> 上传文件:", file_path)
    with open(file_path, "rb") as f:
        content = f.read()
    resp = api_request("POST", f"{API}/upload-files/file", token, multipart={
        "file": (file_path.name, content, "text/markdown"),
    })
    print(">>> 上传响应:", json.dumps(resp, ensure_ascii=False)[:300])
    if resp.get("code") != "success":
        print("上传失败")
        sys.exit(1)
    upload_file = resp["data"]
    upload_file_id = upload_file["id"]
    print(f">>> upload_file_id: {upload_file_id}")

    # 2、创建文档（绑定知识库）
    print(">>> 创建文档")
    resp = api_request("POST", f"{API}/datasets/{args.dataset_id}/documents", token, body={
        "upload_file_ids": [upload_file_id],
        "process_type": "automatic",
    })
    print(">>> 创建文档响应:", json.dumps(resp, ensure_ascii=False)[:400])
    if resp.get("code") != "success":
        print("创建文档失败")
        sys.exit(1)
    data = resp.get("data", {})
    documents = data.get("documents", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    doc_ids = [d["id"] for d in documents]
    batch = data.get("batch", "") if isinstance(data, dict) else (documents[0].get("batch", "") if documents else "")
    print(f">>> 文档: {doc_ids} batch={batch}")

    # 3、等待 Celery 建索引完成（轮询文档状态）
    print(">>> 等待索引构建...")
    for attempt in range(24):
        time.sleep(10)
        resp = api_request("GET", f"{API}/datasets/{args.dataset_id}/documents/batch/{batch}", token)
        docs = resp.get("data", {}).get("list", []) if isinstance(resp.get("data"), dict) else resp.get("data", [])
        if isinstance(docs, list) and docs:
            statuses = {d.get("status") for d in docs}
            print(f"  [{attempt+1}] 文档状态: {statuses}")
            if statuses == {"completed"} or all(s == "completed" for s in statuses):
                print(">>> 索引构建完成！")
                break
            if "error" in statuses:
                print(">>> 索引出错！")
                for d in docs:
                    if d.get("status") == "error":
                        print("  error:", d.get("error", "")[:200])
                break
        else:
            print(f"  [{attempt+1}] 响应: {json.dumps(resp, ensure_ascii=False)[:200]}")

    # 4、召回测试（三种策略）
    print(">>> 召回测试: query =", args.query)
    for strategy in ["semantic", "full_text", "hybrid"]:
        resp = api_request("POST", f"{API}/datasets/{args.dataset_id}/hit", token, body={
            "query": args.query,
            "retrieval_strategy": strategy,
            "k": 5,
            "score": 0.0,
        })
        data = resp.get("data", [])
        print(f"  [{strategy:<10}] {len(data)} 条")
        for d in data[:3]:
            print(f"    score={d.get('score')} doc={d.get('document', {}).get('name')} | {(d.get('content') or '')[:40]}")


if __name__ == "__main__":
    main()
