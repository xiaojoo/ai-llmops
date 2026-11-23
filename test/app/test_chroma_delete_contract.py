#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
POST /chroma/delete 参数来源契约。

旧 Flask 实现：request.get_json(silent=True) 读 JSON body → {path: "..."}。
此处锁定 body 契约：

- JSON body 携带 path → service.delete_file 收到该 path（参数来自 body）
- 不带 body（或 body 缺 path）→ 200 + validation_error / 缺少文件路径参数（不落 service）
"""
import pytest

from internal.service.chroma_file_service import ChromaFileService

_UUID = "00000000-0000-0000-0000-000000000001"


class TestChromaDeleteBodyContract:
    """POST /chroma/delete 必须从 JSON body 读取 path（而非 query 参数）。"""

    @pytest.mark.asyncio
    async def test_delete_reads_path_from_body(self, live_client, live_auth_headers, monkeypatch):
        """JSON body {path: "xxx"} → delete_file 收到 body 中的 path。"""
        captured = {}

        def fake_delete_file(self, filename: str) -> None:
            captured["filename"] = filename

        monkeypatch.setattr(ChromaFileService, "delete_file", fake_delete_file)
        resp = await live_client.post(
            "/chroma/delete",
            headers=live_auth_headers,
            json={"path": "contract-check.txt"},
        )
        assert resp.status_code == 200
        assert captured.get("filename") == "contract-check.txt", (
            f"delete_file 应收到 body 中的 path，实际 {captured!r}（若为 None 说明参数来源仍是 query）"
        )
        assert resp.json()["code"] == "success"

    @pytest.mark.asyncio
    async def test_delete_query_param_not_accepted(self, live_client, live_auth_headers, monkeypatch):
        """query 参数 ?path=xxx 不再被接受：service 不落、响应为缺参/校验错误。"""
        captured = {}

        def fake_delete_file(self, filename: str) -> None:
            captured["filename"] = filename

        monkeypatch.setattr(ChromaFileService, "delete_file", fake_delete_file)
        resp = await live_client.post(
            "/chroma/delete",
            headers=live_auth_headers,
            params={"path": "query-param.txt"},
        )
        assert resp.status_code == 200
        assert "filename" not in captured, (
            f"query 参数不应触发 delete_file，实际 {captured!r}"
        )
        assert resp.json()["code"] in ("validation_error", "fail")
