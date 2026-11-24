from __future__ import annotations

from uuid import UUID

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from sqlalchemy import select

from internal.config.settings import get_settings
from internal.model import App
from internal.service import JwtService
from package.database import get_sync_session_factory


class JwtTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = JwtService.parse_token(token)
            if payload.get("iss") != "llmops":
                return None
            audience = payload.get("aud")
            if audience and get_settings().mcp_public_url not in (
                audience if isinstance(audience, list) else [audience]
            ):
                return None
            subject = str(UUID(payload["sub"]))
        except Exception:
            return None
        return AccessToken(
            token=token,
            client_id="llmops",
            scopes=["mcp:read"],
            subject=subject,
            resource=get_settings().mcp_public_url,
        )


def _account_id() -> UUID:
    token = get_access_token()
    if token is None or not token.subject:
        raise PermissionError("MCP 请求缺少有效登录态")
    return UUID(token.subject)


def create_mcp_server() -> MCPServer:
    public_url = get_settings().mcp_public_url
    if not public_url:
        raise RuntimeError("启用 MCP Server 前必须配置 MCP_PUBLIC_URL")
    server = MCPServer(
        "LLMOps",
        token_verifier=JwtTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(public_url),
            resource_server_url=AnyHttpUrl(public_url),
            required_scopes=["mcp:read"],
            validate_token_resource=True,
        ),
    )

    @server.tool()
    def list_apps() -> list[dict]:
        """列出当前账号可见的应用。"""
        account_id = _account_id()
        with get_sync_session_factory()() as db:
            rows = db.execute(
                select(App.id, App.name, App.status)
                .where(App.account_id == account_id, App.is_deleted.is_(False))
                .order_by(App.created_at.desc())
            ).all()
        return [
            {"id": str(row.id), "name": row.name, "status": row.status}
            for row in rows
        ]

    @server.tool()
    def app_summary(app_id: str) -> dict:
        """返回当前账号指定应用的脱敏摘要。"""
        account_id = _account_id()
        app_uuid = UUID(app_id)
        with get_sync_session_factory()() as db:
            app = db.execute(
                select(App).where(
                    App.id == app_uuid,
                    App.account_id == account_id,
                    App.is_deleted.is_(False),
                )
            ).scalar_one_or_none()
        if app is None:
            raise PermissionError("应用不存在或不属于当前账号")
        return {
            "id": str(app.id),
            "name": app.name,
            "status": app.status,
            "description": app.description,
        }

    return server
