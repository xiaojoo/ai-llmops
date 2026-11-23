#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
黄金对照：逐字段对照 golden 样例。

黄金样例位于 docs/migration/golden/：
- 401-shape.json：未授权响应（HTTP 200 + code/message/data 结构）
- ping.json：/ping 无认证 → 同 401-shape
- default-app-icon.json：200 image/png 二进制

对照要求：
- 401-shape.json / ping.json：逐字段对照 code/message/data（HTTP headers 不对照，因为 FastAPI 与 Werkzeug header 不同）
- default-app-icon.json：content-type + 二进制长度 > 0
"""
import json
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "docs" / "migration" / "golden"


def _load_golden(name: str) -> dict:
    """加载黄金样例 JSON。"""
    path = GOLDEN_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_golden_body(golden: dict) -> dict:
    """从黄金样例解析 body JSON（golden body 可能有尾部换行）。"""
    body_str = golden["body"].strip()
    return json.loads(body_str)


class TestGolden401Shape:
    """黄金对照：401-shape.json"""

    @pytest.mark.asyncio
    async def test_401_shape_body_matches_golden(self, live_client):
        """未认证访问 /account → 逐字段对照 golden 401-shape.json 的 body。"""
        golden = _load_golden("401-shape.json")
        expected_body = _parse_golden_body(golden)

        resp = await live_client.get("/account")
        assert resp.status_code == golden["status_code"], f"status: {resp.status_code} != {golden['status_code']}"

        body = resp.json()
        assert body["code"] == expected_body["code"], f"code: {body['code']} != {expected_body['code']}"
        assert body["message"] == expected_body["message"], f"message: {body['message']} != {expected_body['message']}"
        assert body["data"] == expected_body["data"], f"data: {body['data']} != {expected_body['data']}"

    @pytest.mark.asyncio
    async def test_401_shape_content_type(self, live_client):
        """未认证响应 Content-Type 为 application/json。"""
        resp = await live_client.get("/account")
        assert "application/json" in resp.headers.get("content-type", "")


class TestGoldenPing:
    """黄金对照：ping.json（/ping 无认证 → 同 401-shape）"""

    @pytest.mark.asyncio
    async def test_ping_unauthorized_matches_golden(self, live_client):
        """/ping 无认证 → 逐字段对照 golden ping.json 的 body（与 401-shape 相同）。"""
        golden = _load_golden("ping.json")
        expected_body = _parse_golden_body(golden)

        resp = await live_client.get("/ping")
        assert resp.status_code == golden["status_code"]

        body = resp.json()
        assert body["code"] == expected_body["code"]
        assert body["message"] == expected_body["message"]
        assert body["data"] == expected_body["data"]


class TestGoldenDefaultAppIcon:
    """黄金对照：default-app-icon.json（二进制 PNG）"""

    @pytest.mark.asyncio
    async def test_default_app_icon_matches_golden(self, live_client):
        """default-app-icon → 200 image/png，二进制长度 > 0。"""
        golden = _load_golden("default-app-icon.json")

        resp = await live_client.get("/default-app-icon")
        assert resp.status_code == golden["status_code"]
        assert "image/png" in resp.headers.get("content-type", "")
        # golden content-length: 1297（实际文件大小可能略有不同，只要 > 0）
        assert len(resp.content) > 0, "icon binary should not be empty"

    @pytest.mark.asyncio
    async def test_default_app_icon_is_valid_png(self, live_client):
        """icon 二进制以 PNG magic bytes 开头。"""
        resp = await live_client.get("/default-app-icon")
        # PNG magic: \x89PNG\r\n\x1a\n
        assert resp.content[:4] == b'\x89PNG', "not a valid PNG"
