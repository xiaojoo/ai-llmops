"""FastAPI app 集成测试。

测试内容：
- /healthz 返回 200 + {"status": "ok"}
- /docs 可访问（FastAPI 自动提供）
- /favicon.ico 返回 204
- /default-app-icon 返回 200 image/png
- 异常处理器：CustomException / ValidationError / SQLAlchemyError / Exception → 200 + {code, message, data}

lifespan 测试方式：
- ASGITransport 不自动触发 lifespan；手动进入 lifespan 上下文管理器。
"""
import io
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from internal.exception import (
    CustomException,
    FailedException,
    UnauthorizedException,
)
from package.response import HttpCode, Response as AppResponse


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _make_client(app: FastAPI) -> AsyncClient:
    """创建 httpx AsyncClient，手动进入 lifespan。"""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


class TestHealthz:
    @pytest.mark.asyncio
    async def test_healthz_returns_ok(self):
        """健康检查端点"""
        from app.http.app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


class TestFavicon:
    @pytest.mark.asyncio
    async def test_favicon_returns_204(self):
        """favicon 返回 204 No Content"""
        from app.http.app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/favicon.ico")
            assert resp.status_code == 204


class TestDefaultAppIcon:
    @pytest.mark.asyncio
    async def test_default_app_icon_returns_png(self):
        """default-app-icon 返回 200 + image/png"""
        from app.http.app import app
        # Ensure the icon file exists
        icon_path = Path(__file__).resolve().parents[2] / "internal" / "core" / "builtin_apps" / "default-user-icon.png"
        if not icon_path.exists():
            pytest.skip("default-user-icon.png not found")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/default-app-icon")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/png"
            assert len(resp.content) > 0


class TestExceptionHandlers:
    """异常处理器：逐条对照旧 _register_error_handler"""

    @pytest.mark.asyncio
    async def test_custom_exception_returns_200_with_code(self):
        """CustomException → 200 + {code, message, data}"""
        from app.http.app import app

        @app.get("/test/custom-error")
        async def _raise():
            raise FailedException("业务失败", data={"detail": "test"})

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/test/custom-error")
                assert resp.status_code == 200
                body = resp.json()
                assert body["code"] == "fail"
                assert body["message"] == "业务失败"
                assert body["data"] == {"detail": "test"}
        finally:
            # Clean up test route
            app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and r.path == "/test/custom-error")]

    @pytest.mark.asyncio
    async def test_unauthorized_exception_returns_200(self):
        """UnauthorizedException → 200 + {code: unauthorized, ...}"""
        from app.http.app import app

        @app.get("/test/unauth-error")
        async def _raise():
            raise UnauthorizedException("该接口需要授权才能访问，请登录后尝试")

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/test/unauth-error")
                assert resp.status_code == 200
                body = resp.json()
                assert body["code"] == "unauthorized"
                assert "该接口需要授权才能访问" in body["message"]
        finally:
            app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and r.path == "/test/unauth-error")]

    @pytest.mark.asyncio
    async def test_validation_error_returns_200_with_validation_code(self):
        """ValidationError → 200 + {code: validation_error, message=首个错误, data=errors}"""
        from app.http.app import app

        class FakeModel(BaseModel):
            name: str
            email: str

        @app.get("/test/validation-error")
        async def _raise():
            try:
                FakeModel.model_validate({})
            except ValidationError as e:
                raise e

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/test/validation-error")
                assert resp.status_code == 200
                body = resp.json()
                assert body["code"] == "validation_error"
                assert body["message"]  # non-empty
                assert isinstance(body["data"], dict)
        finally:
            app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and r.path == "/test/validation-error")]

    @pytest.mark.asyncio
    async def test_request_validation_error_returns_200(self):
        """FastAPI 请求体校验失败（RequestValidationError）→ 200 + {code: validation_error}（非 422）"""
        from app.http.app import app

        class FakeBody(BaseModel):
            query: str

        @app.post("/test/req-validation-error")
        async def _echo(body: FakeBody):
            return {"ok": True}

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/test/req-validation-error", json={})
                assert resp.status_code == 200, f"预期 200（契约），实际 {resp.status_code}"
                body = resp.json()
                assert body["code"] == "validation_error"
                assert body["message"]  # 首个错误文案
                assert isinstance(body["data"], dict)
                assert "query" in body["data"]
        finally:
            app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and r.path == "/test/req-validation-error")]

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_returns_200_with_fail_code(self):
        """SQLAlchemyError → 200 + {code: fail, message: 数据库操作失败, data: {}}"""
        from app.http.app import app

        @app.get("/test/db-error")
        async def _raise():
            raise SQLAlchemyError("connection failed")

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/test/db-error")
                assert resp.status_code == 200
                body = resp.json()
                assert body["code"] == "fail"
                assert body["message"] == "数据库操作失败"
                assert body["data"] == {}
        finally:
            app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and r.path == "/test/db-error")]

    @pytest.mark.asyncio
    async def test_generic_exception_returns_200_in_production(self):
        """通用异常 + 非开发模式 → 200 + {code: fail, message: str(error), data: {}}"""
        from app.http.app import app, general_exception_handler

        # Directly test the handler function with mocked environment
        mock_request = AsyncMock()
        exc = RuntimeError("something broke")

        with patch("app.http.app.os.getenv", return_value=None):
            resp = await general_exception_handler(mock_request, exc)
            assert resp.status_code == 200
            body = resp.body.decode()
            assert '"code":"fail"' in body
            assert "something broke" in body


class TestCORS:
    @pytest.mark.asyncio
    async def test_cors_headers_on_preflight(self):
        """CORS preflight 返回正确 headers"""
        from app.http.app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.options(
                "/healthz",
                headers={
                    "Origin": "http://example.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type,Authorization",
                },
            )
            # CORS middleware should respond with allow headers
            # Starlette CORSMiddleware with allow_origins=["*"] + allow_credentials=True
            # reflects the request origin (not wildcard) per CORS spec
            assert "access-control-allow-origin" in resp.headers
            assert resp.headers.get("access-control-allow-origin") == "http://example.com"


class TestDocs:
    @pytest.mark.asyncio
    async def test_docs_endpoint_accessible(self):
        """Swagger UI /docs 可访问"""
        from app.http.app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs")
            assert resp.status_code == 200
