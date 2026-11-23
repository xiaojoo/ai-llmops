"""认证依赖 + request_context 依赖测试。

get_current_user/get_api_key_account 改用 request: Request 读取 Authorization 头。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request

from internal.exception import UnauthorizedException
from internal.model import Account, ApiKey


def _make_request(auth_header: str = "") -> Request:
    """构建带 Authorization 头的 mock Request。"""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"authorization": auth_header} if auth_header else {}
    mock_request.url = MagicMock()
    mock_request.url.scheme = "http"
    mock_request.url.netloc = "localhost:3000"
    mock_request.url.hostname = "localhost"
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    return mock_request


# ---- get_current_user ----

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_bearer_token_returns_account(self):
        """有效 Bearer token → 返回 Account"""
        from internal.server.deps import get_current_user
        mock_account = Account(name="test", email="test@test.com")
        mock_account.id = "fake-uuid"

        mock_db = AsyncMock()

        with (
            patch("internal.server.deps.JwtService") as mock_jwt_cls,
            patch("internal.server.deps.create_account_service") as mock_factory,
        ):
            mock_jwt_cls.parse_token.return_value = {"sub": "fake-uuid"}
            mock_svc = AsyncMock()
            mock_svc.get_account.return_value = mock_account
            mock_factory.return_value = mock_svc

            result = await get_current_user(request=_make_request("Bearer valid-token-123"), db=mock_db)
            assert result == mock_account
            mock_jwt_cls.parse_token.assert_called_once_with("valid-token-123")

    @pytest.mark.asyncio
    async def test_missing_authorization_raises(self):
        """无 Authorization 头 → UnauthorizedException"""
        from internal.server.deps import get_current_user
        mock_db = AsyncMock()
        with pytest.raises(UnauthorizedException) as exc_info:
            await get_current_user(request=_make_request(""), db=mock_db)
        assert "该接口需要授权才能访问，请登录后尝试" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_no_space_in_auth_raises(self):
        """Authorization 无空格分隔 → UnauthorizedException"""
        from internal.server.deps import get_current_user
        mock_db = AsyncMock()
        with pytest.raises(UnauthorizedException) as exc_info:
            await get_current_user(request=_make_request("BearerNoSpace"), db=mock_db)
        assert "验证格式失败" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_wrong_schema_raises(self):
        """非 Bearer scheme → UnauthorizedException"""
        from internal.server.deps import get_current_user
        mock_db = AsyncMock()
        with pytest.raises(UnauthorizedException) as exc_info:
            await get_current_user(request=_make_request("Basic abc123"), db=mock_db)
        assert "验证格式失败" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_account_not_found_raises(self):
        """token 有效但账号不存在 → UnauthorizedException"""
        from internal.server.deps import get_current_user
        mock_db = AsyncMock()

        with (
            patch("internal.server.deps.JwtService") as mock_jwt_cls,
            patch("internal.server.deps.create_account_service") as mock_factory,
        ):
            mock_jwt_cls.parse_token.return_value = {"sub": "nonexistent-id"}
            mock_svc = AsyncMock()
            mock_svc.get_account.return_value = None
            mock_factory.return_value = mock_svc

            with pytest.raises(UnauthorizedException):
                await get_current_user(request=_make_request("Bearer valid-but-no-account"), db=mock_db)


# ---- get_api_key_account ----

class TestGetApiKeyAccount:
    @pytest.mark.asyncio
    async def test_valid_api_key_returns_account(self):
        """有效 api_key + active → 返回 Account"""
        from internal.server.deps import get_api_key_account
        mock_account = Account(name="api-user", email="api@test.com")
        mock_api_key = ApiKey(api_key="llmops-v1/testkey", is_active=True)
        mock_api_key.account = mock_account
        mock_db = AsyncMock()

        with patch("internal.server.deps.create_api_key_service") as mock_factory:
            mock_svc = AsyncMock()
            mock_svc.get_api_by_by_credential.return_value = mock_api_key
            mock_factory.return_value = mock_svc

            result = await get_api_key_account(request=_make_request("Bearer llmops-v1/testkey"), db=mock_db)
            assert result == mock_account

    @pytest.mark.asyncio
    async def test_inactive_api_key_raises(self):
        """api_key 存在但 is_active=False → UnauthorizedException"""
        from internal.server.deps import get_api_key_account
        mock_api_key = ApiKey(api_key="llmops-v1/inactive", is_active=False)
        mock_db = AsyncMock()

        with patch("internal.server.deps.create_api_key_service") as mock_factory:
            mock_svc = AsyncMock()
            mock_svc.get_api_by_by_credential.return_value = mock_api_key
            mock_factory.return_value = mock_svc

            with pytest.raises(UnauthorizedException) as exc_info:
                await get_api_key_account(request=_make_request("Bearer llmops-v1/inactive"), db=mock_db)
            assert "该秘钥不存在或未激活" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        """api_key 不存在 → UnauthorizedException"""
        from internal.server.deps import get_api_key_account
        mock_db = AsyncMock()

        with patch("internal.server.deps.create_api_key_service") as mock_factory:
            mock_svc = AsyncMock()
            mock_svc.get_api_by_by_credential.return_value = None
            mock_factory.return_value = mock_svc

            with pytest.raises(UnauthorizedException) as exc_info:
                await get_api_key_account(request=_make_request("Bearer nonexistent-key"), db=mock_db)
            assert "该秘钥不存在或未激活" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_no_authorization_raises(self):
        """无 Authorization → UnauthorizedException"""
        from internal.server.deps import get_api_key_account
        mock_db = AsyncMock()
        with pytest.raises(UnauthorizedException) as exc_info:
            await get_api_key_account(request=_make_request(""), db=mock_db)
        assert "该接口需要授权才能访问，请登录后尝试" in str(exc_info.value.message)


# ---- request_context dependency ----

class TestRequestContext:
    @pytest.mark.asyncio
    async def test_request_context_sets_contextvar(self):
        """request_context 依赖写入 contextvar"""
        from internal.server.deps import request_context_dependency
        from internal.core.request_context import get_request_context

        mock_request = AsyncMock(spec=Request)
        mock_request.url.scheme = "https"
        mock_request.url.netloc = "example.com:8080"
        mock_request.url.hostname = "example.com"
        mock_request.client.host = "127.0.0.1"

        gen = request_context_dependency(mock_request)
        ctx = await gen.__anext__()
        assert ctx.scheme == "https"
        assert ctx.host == "example.com"
        assert ctx.remote_addr == "127.0.0.1"

        current = get_request_context()
        assert current.scheme == "https"
        assert current.host == "example.com"

        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

    @pytest.mark.asyncio
    async def test_request_context_cleans_up(self):
        """request_context 依赖 cleanup 后 contextvar 重置"""
        from internal.server.deps import request_context_dependency
        from internal.core.request_context import get_request_context

        mock_request = AsyncMock(spec=Request)
        mock_request.url.scheme = "http"
        mock_request.url.netloc = "localhost:3000"
        mock_request.url.hostname = "localhost"
        mock_request.client.host = "192.168.1.1"

        gen = request_context_dependency(mock_request)
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

        current = get_request_context()
        assert current.scheme is None or current.remote_addr is None
