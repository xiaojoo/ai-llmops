"""pilot 测试已演进为 app/http/app.py，原 pilot 删除。

本文件保留测试内容，指向新 app 入口。
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.http.app import app


@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_openapi_docs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "llmops"
