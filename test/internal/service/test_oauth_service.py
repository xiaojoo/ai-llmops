#!/usr/bin/env python
"""OAuthService async 化测试——oauth_login 登录链路（真实 Postgres，OAuth 网络调用打桩）。

覆盖：新账号路径（建号 + 建 account_oauth + last_login_ip 取请求上下文 remote_addr）、
已有账号路径（不重复建号）、已有 account_oauth 路径（复用 + 更新 token）、未知 provider 抛 NotFound。
注意：account_oauth 查询一律按 (provider, openid) 双条件过滤——真实库可能存在历史 github 行
（如 openid=53503510），只按 provider 过滤会 MultipleResultsFound。
"""
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select

from internal.core.request_context import RequestContext, reset_request_context, set_request_context
from internal.exception import NotFoundException
from internal.model import Account, AccountOAuth
from internal.service import JwtService
from internal.service.account_service import AccountService
from internal.service.oauth_service import OAuthService
from package.oauth import OAuth, OAuthUserInfo


@dataclass
class FakeGithubOAuth(OAuth):
    """无网络 OAuth 桩：get_access_token 直接返回固定 token（绕开 GithubOAuth 的 requests 调用）。"""
    client_id: str = "id"
    client_secret: str = "secret"
    redirect_uri: str = "http://localhost/callback"
    user_info: OAuthUserInfo = field(
        default_factory=lambda: OAuthUserInfo(id="gh-1", name="gh user", email="gh@example.com")
    )

    def get_provider(self) -> str:
        return "github"

    def get_authorization_url(self) -> str:
        return "http://localhost/authorize"

    def get_access_token(self, code: str) -> str:
        return "oauth-token-1"

    def get_raw_user_info(self, token: str) -> dict:
        return {}

    def _transform_user_info(self, raw_info: dict) -> OAuthUserInfo:
        return self.user_info


def _svc(db) -> OAuthService:
    account_service = AccountService(db=db, jwt_service=JwtService())
    return OAuthService(db=db, account_service=account_service, jwt_service=JwtService())


def _patch_oauth(monkeypatch):
    fake = FakeGithubOAuth()
    monkeypatch.setattr(OAuthService, "get_oauth_by_provider_name", classmethod(lambda cls, name: fake))
    return fake


@contextmanager
def _request_context(remote_addr: str):
    """模拟请求上下文（oauth_login 写 last_login_ip 依赖它）。"""
    token = set_request_context(RequestContext(remote_addr=remote_addr))
    try:
        yield
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_oauth_login_creates_account_and_records_login_ip(db_session, monkeypatch):
    _patch_oauth(monkeypatch)
    svc = _svc(db_session)

    with _request_context("198.51.100.9"):
        creds = await svc.oauth_login("github", "code-1")

    assert creds["access_token"]
    payload = JwtService.parse_token(creds["access_token"])
    account = (
        await db_session.execute(select(Account).where(Account.email == "gh@example.com"))
    ).scalar_one()
    assert payload["sub"] == str(account.id)
    assert account.last_login_ip == "198.51.100.9", "last_login_ip 应取请求上下文 remote_addr"

    oauth_record = (
        await db_session.execute(
            select(AccountOAuth).where(
                AccountOAuth.provider == "github", AccountOAuth.openid == "gh-1"
            )
        )
    ).scalar_one()
    assert oauth_record.encrypted_token == "oauth-token-1"
    assert oauth_record.account_id == str(account.id)


@pytest.mark.asyncio
async def test_oauth_login_existing_account_does_not_duplicate(db_session, monkeypatch):
    _patch_oauth(monkeypatch)
    existing = Account(name="existing", email="gh@example.com")
    db_session.add(existing)
    await db_session.flush()
    svc = _svc(db_session)

    with _request_context("198.51.100.10"):
        creds = await svc.oauth_login("github", "code-1")
    assert creds["access_token"]

    accounts = (
        await db_session.execute(select(Account).where(Account.email == "gh@example.com"))
    ).scalars().all()
    assert len(accounts) == 1, "已有账号时不应重复创建"
    assert accounts[0].id == existing.id


@pytest.mark.asyncio
async def test_oauth_login_existing_oauth_record_reuses_and_updates_token(db_session, monkeypatch):
    _patch_oauth(monkeypatch)
    account = Account(name="linked", email="gh@example.com")
    db_session.add(account)
    await db_session.flush()
    oauth_record = AccountOAuth(
        account_id=str(account.id), provider="github", openid="gh-1", encrypted_token="old-token"
    )
    db_session.add(oauth_record)
    await db_session.flush()
    svc = _svc(db_session)

    with _request_context("198.51.100.11"):
        creds = await svc.oauth_login("github", "code-1")
    assert creds["access_token"]

    records = (
        await db_session.execute(
            select(AccountOAuth).where(
                AccountOAuth.provider == "github", AccountOAuth.openid == "gh-1"
            )
        )
    ).scalars().all()
    assert len(records) == 1, "已有 account_oauth 时应复用，不重复创建"
    assert records[0].id == oauth_record.id
    assert records[0].encrypted_token == "oauth-token-1", "登录成功应更新 encrypted_token"


@pytest.mark.asyncio
async def test_oauth_login_unknown_provider_raises(db_session, monkeypatch):
    """不 patch get_oauth_by_provider_name：真实类方法只认识 github → NotFoundException。"""
    svc = _svc(db_session)
    with pytest.raises(NotFoundException):
        await svc.oauth_login("gitlab", "code-1")
