import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.server import MCPServer

import internal.core.tools.mcp_client as mcp_client
from internal.core.mcp_server import JwtTokenVerifier
from internal.service import JwtService


@pytest.mark.asyncio
async def test_call_mcp_tool_with_in_memory_server(monkeypatch):
    server = MCPServer("test")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @asynccontextmanager
    async def fake_with_client(_config):
        async with Client(server) as client:
            yield client

    monkeypatch.setattr(mcp_client, "_with_client", fake_with_client)
    result = await mcp_client._call_tool({}, "add", {"a": 2, "b": 3})
    assert result == {"result": 5}


def test_mcp_args_model_uses_json_schema():
    model = mcp_client._args_model("search", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search query"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    })
    value = model.model_validate({"query": "hello"})
    assert value.query == "hello"
    assert value.limit == 5


@pytest.mark.asyncio
async def test_optional_none_arguments_are_omitted(monkeypatch):
    server = MCPServer("optional")

    @server.tool()
    def add(a: int, b: int, note: str | None = None) -> int:
        """Add two integers with an optional note."""
        return a + b

    @asynccontextmanager
    async def fake_with_client(_config):
        async with Client(server) as client:
            yield client

    captured = {}

    async def fake_call(_config, _name, arguments):
        captured.update(arguments)
        return {"result": 5}

    monkeypatch.setattr(mcp_client, "_with_client", fake_with_client)
    monkeypatch.setattr(mcp_client, "_call_tool", fake_call)
    monkeypatch.setattr(
        mcp_client,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_enabled=True,
            mcp_allowed_account_ids="*",
            mcp_servers_json='{"optional": {}}',
        ),
    )
    tools = await mcp_client.MCPClientManager.discover_tools()
    tool = next(item for item in tools if item.name.endswith("__add"))
    await tool.ainvoke({"a": 2, "b": 3})
    assert captured == {"a": 2, "b": 3}


@pytest.mark.asyncio
async def test_mcp_tools_require_account_allowlist(monkeypatch):
    monkeypatch.setattr(
        "internal.core.tools.mcp_client.get_settings",
        lambda: SimpleNamespace(mcp_enabled=True, mcp_allowed_account_ids=""),
    )
    assert await mcp_client.MCPClientManager.discover_tools(account_id=uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_jwt_token_verifier_returns_subject(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-32-characters-long-1234")
    monkeypatch.setattr(
        "internal.core.mcp_server.get_settings",
        lambda: SimpleNamespace(mcp_public_url="http://localhost:5000/mcp"),
    )
    account_id = uuid.uuid4()
    token = JwtService.generate_token({"sub": str(account_id), "iss": "llmops", "exp": 9999999999})
    access = await JwtTokenVerifier().verify_token(token)
    assert access is not None
    assert access.subject == str(account_id)
    assert await JwtTokenVerifier().verify_token("invalid") is None
    wrong_issuer = JwtService.generate_token({
        "sub": str(account_id), "iss": "other", "exp": 9999999999,
    })
    assert await JwtTokenVerifier().verify_token(wrong_issuer) is None
    wrong_audience = JwtService.generate_token({
        "sub": str(account_id), "iss": "llmops", "aud": "https://other.example/mcp",
        "exp": 9999999999,
    })
    assert await JwtTokenVerifier().verify_token(wrong_audience) is None
