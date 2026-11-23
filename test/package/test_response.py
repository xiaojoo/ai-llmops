"""response 重写契约测试。

契约断言：
- Response dataclass 字段：code/message/data
- json() 返回 JSONResponse（status 200），body = {code, message, data}
- success_json / fail_json / validation_error_json / message_json 签名不变
- compact_generate_response：
  - Response → JSONResponse（status 200）
  - 元组 (Response, status_code) → JSONResponse(status_code)
  - 生成器 → StreamingResponse(media_type="text/event-stream", headers)
- HttpCode 枚举值不变
"""
import pytest
from dataclasses import asdict

from fastapi.responses import JSONResponse, StreamingResponse

from package.response import (
    HttpCode,
    Response,
    compact_generate_response,
    fail_json,
    fail_message_json,
    forbidden_message_json,
    json,
    message_json,
    not_found_message_json,
    success_json,
    success_message_json,
    unauthorized_message_json,
    validation_error_json,
)


# ---- Response dataclass ----

class TestResponseModel:
    def test_default_values(self):
        r = Response()
        assert r.code == HttpCode.SUCCESS
        assert r.message == ""
        assert r.data == {}

    def test_custom_values(self):
        r = Response(code=HttpCode.FAIL, message="err", data={"x": 1})
        assert r.code == HttpCode.FAIL
        assert r.message == "err"
        assert r.data == {"x": 1}


# ---- HttpCode 枚举 ----

class TestHttpCode:
    def test_enum_values_unchanged(self):
        assert HttpCode.SUCCESS == "success"
        assert HttpCode.FAIL == "fail"
        assert HttpCode.NOT_FOUND == "not_found"
        assert HttpCode.UNAUTHORIZED == "unauthorized"
        assert HttpCode.FORBIDDEN == "forbidden"
        assert HttpCode.VALIDATION_ERROR == "validation_error"


# ---- json() helper ----

class TestJsonHelper:
    @pytest.mark.asyncio
    async def test_json_returns_jsonresponse_200(self):
        resp = json(Response(code=HttpCode.SUCCESS, message="ok", data={"a": 1}))
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert '"code":"success"' in body
        assert '"message":"ok"' in body

    @pytest.mark.asyncio
    async def test_json_none_uses_default(self):
        resp = json()
        assert isinstance(resp, JSONResponse)
        body = resp.body.decode()
        assert '"code":"success"' in body

    @pytest.mark.asyncio
    async def test_json_custom_status_code(self):
        resp = json(Response(), status_code=201)
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 201


# ---- success_json / fail_json ----

class TestSuccessFailJson:
    @pytest.mark.asyncio
    async def test_success_json(self):
        resp = success_json({"id": 1})
        assert isinstance(resp, JSONResponse)
        body = resp.body.decode()
        assert '"code":"success"' in body
        assert '"data":{"id":1}' in body

    @pytest.mark.asyncio
    async def test_success_json_none(self):
        resp = success_json()
        body = resp.body.decode()
        assert '"code":"success"' in body
        assert '"data":null' in body or '"data":{}' in body

    @pytest.mark.asyncio
    async def test_fail_json(self):
        resp = fail_json({"error": "bad"})
        body = resp.body.decode()
        assert '"code":"fail"' in body


# ---- validation_error_json ----

class TestValidationErrJson:
    @pytest.mark.asyncio
    async def test_first_error_as_message(self):
        resp = validation_error_json({"name": "名称不能为空", "email": "邮箱格式错误"})
        body = resp.body.decode()
        assert '"code":"validation_error"' in body
        # first key's value becomes message
        assert '"message":"名称不能为空"' in body
        # errors dict preserved in data
        assert '"name":"名称不能为空"' in body


# ---- message_json family ----

class TestMessageJson:
    @pytest.mark.asyncio
    async def test_message_json(self):
        resp = message_json(HttpCode.FAIL, "oops")
        body = resp.body.decode()
        assert '"code":"fail"' in body
        assert '"message":"oops"' in body
        assert '"data":{}' in body

    @pytest.mark.asyncio
    async def test_success_message_json(self):
        resp = success_message_json("done")
        body = resp.body.decode()
        assert '"code":"success"' in body

    @pytest.mark.asyncio
    async def test_fail_message_json(self):
        resp = fail_message_json("no")
        body = resp.body.decode()
        assert '"code":"fail"' in body

    @pytest.mark.asyncio
    async def test_not_found_message_json(self):
        resp = not_found_message_json("gone")
        body = resp.body.decode()
        assert '"code":"not_found"' in body

    @pytest.mark.asyncio
    async def test_unauthorized_message_json(self):
        resp = unauthorized_message_json("auth needed")
        body = resp.body.decode()
        assert '"code":"unauthorized"' in body

    @pytest.mark.asyncio
    async def test_forbidden_message_json(self):
        resp = forbidden_message_json("no perm")
        body = resp.body.decode()
        assert '"code":"forbidden"' in body


# ---- compact_generate_response ----

class TestCompactGenerateResponse:
    @pytest.mark.asyncio
    async def test_response_to_jsonresponse(self):
        r = Response(code=HttpCode.SUCCESS, message="ok", data={"x": 1})
        resp = compact_generate_response(r)
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert '"code":"success"' in body

    @pytest.mark.asyncio
    async def test_tuple_response_with_status(self):
        r = Response(code=HttpCode.FAIL, message="err", data={})
        resp = compact_generate_response((r, 400))
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 400

    def test_generator_to_streaming_response(self):
        def gen():
            yield "data: hello\n\n"
            yield "data: world\n\n"

        resp = compact_generate_response(gen())
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"

    def test_streaming_headers(self):
        def gen():
            yield "data: test\n\n"

        resp = compact_generate_response(gen())
        # Cache-Control and X-Accel-Buffering headers set
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"
