from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from pydantic import ConfigDict, Field, create_model

from internal.config.settings import get_settings
from internal.core.tools.tool_gateway import validate_http_url

logger = logging.getLogger(__name__)

_SAFE_ENV_KEYS = {
    "PATH", "PATHEXT", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "HOME", "USERPROFILE", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV",
}


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def _json_type(spec: dict[str, Any]) -> Any:
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list[Any],
        "object": dict[str, Any],
    }
    return mapping.get(spec.get("type"), Any)


def _args_model(tool_name: str, schema: dict[str, Any]) -> type:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields = {}
    for name, spec in properties.items():
        field_type = _json_type(spec)
        default = ... if name in required else spec.get("default")
        fields[name] = (field_type, Field(default=default, description=spec.get("description", "")))
    return create_model(
        f"MCP_{_safe_name(tool_name)}",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )


def _connections() -> dict[str, dict[str, Any]]:
    raw = json.loads(get_settings().mcp_servers_json or "[]")
    if isinstance(raw, list):
        return {str(item["name"]): item for item in raw}
    return raw


@asynccontextmanager
async def _with_client(config: dict[str, Any]):
    timeout = float(config.get("timeout") or get_settings().mcp_timeout_s)
    transport = config.get("transport", "stdio")
    if transport == "stdio":
        env = {key: value for key, value in os.environ.items() if key in _SAFE_ENV_KEYS}
        env.update({str(key): str(value) for key, value in (config.get("env") or {}).items()})
        params = StdioServerParameters(
            command=config["command"],
            args=list(config.get("args") or []),
            env=env,
            cwd=config.get("cwd"),
        )
        async with Client(params, read_timeout_seconds=timeout) as client:
            yield client
        return

    if transport != "streamable_http":
        raise ValueError(f"不支持的 MCP transport: {transport}")
    url = validate_http_url(config["url"])
    import httpx2

    async with httpx2.AsyncClient(
        headers=config.get("headers") or {},
        timeout=timeout,
    ) as http_client:
        async with Client(
            streamable_http_client(url, http_client=http_client),
            read_timeout_seconds=timeout,
        ) as client:
            yield client


# shortcut: MVP 每次调用新建无状态 session；有状态 MCP server 需在单事件循环内做连接池。
async def _call_tool(config: dict[str, Any], name: str, arguments: dict[str, Any]) -> Any:
    async with _with_client(config) as client:
        result = await client.call_tool(name, arguments)
        if result.is_error:
            text = "\n".join(
                block.text for block in result.content
                if isinstance(block, TextContent)
            )
            raise ToolException(text or f"MCP 工具执行失败: {name}")
        if result.structured_content is not None:
            return result.structured_content
        return "\n".join(
            block.text for block in result.content
            if isinstance(block, TextContent)
        )


class MCPClientManager:
    @classmethod
    async def discover_tools(cls, account_id: Any = None) -> list[BaseTool]:
        if not get_settings().mcp_enabled:
            return []
        allowed_accounts = {
            item.strip() for item in get_settings().mcp_allowed_account_ids.split(",")
            if item.strip()
        }
        if account_id is not None and (
            not allowed_accounts
            or ("*" not in allowed_accounts and str(account_id) not in allowed_accounts)
        ):
            logger.warning("MCP 工具未授权给账号 %s", account_id)
            return []
        tools: list[BaseTool] = []
        for server_name, config in _connections().items():
            try:
                async with _with_client(config) as client:
                    cursor = None
                    while True:
                        result = await client.list_tools(cursor=cursor)
                        for remote in result.tools:
                            tool_name = f"mcp__{_safe_name(server_name)}__{_safe_name(remote.name)}"

                            async def invoke(_config=config, _name=remote.name, **kwargs):
                                arguments = {key: value for key, value in kwargs.items() if value is not None}
                                return await _call_tool(_config, _name, arguments)

                            tools.append(StructuredTool.from_function(
                                coroutine=invoke,
                                name=tool_name,
                                description=remote.description or f"MCP tool {remote.name}",
                                args_schema=_args_model(tool_name, remote.input_schema),
                            ))
                        cursor = getattr(result, "next_cursor", None)
                        if not cursor:
                            break
            except Exception:
                logger.exception("MCP 工具发现失败 server=%s", server_name)
        return tools
