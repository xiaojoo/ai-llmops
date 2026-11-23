#!/usr/bin/env python
"""AccountService async 化测试（真实 Postgres + db_session 事务回滚）。

覆盖：get_account / get_account_by_email / get_account_oauth_by_provider_name_and_openid /
create_account / update_password（is_password_set 路径）/ password_login（成功写 last_login_ip、
失败抛 FailedException）。
"""
import pytest
from sqlalchemy import select

from internal.core.request_context import RequestContext, reset_request_context, set_request_context
from internal.exception import FailedException
from internal.model import Account, AccountOAuth
from internal.service import JwtService
from internal.service.account_service import AccountService
from package.password import compare_password


def _svc(db):
    return AccountService(db=db, jwt_service=JwtService())


async def _account(db, name: str, email: str) -> Account:
    account = Account(name=name, email=email)
    db.add(account)
    await db.flush()
    return account


@pytest.mark.asyncio
async def test_get_account_found_and_missing(db_session):
    account = await _account(db_session, "u1", "u1@example.com")
    svc = _svc(db_session)

    assert (await svc.get_account(str(account.id))).id == account.id
    assert await svc.get_account("00000000-0000-0000-0000-000000000000") is None


@pytest.mark.asyncio
async def test_get_account_by_email(db_session):
    account = await _account(db_session, "u2", "u2@example.com")
    svc = _svc(db_session)

    assert (await svc.get_account_by_email("u2@example.com")).id == account.id
    assert await svc.get_account_by_email("nope@example.com") is None


@pytest.mark.asyncio
async def test_update_password_sets_hash_and_salt(db_session):
    account = await _account(db_session, "u3", "u3@example.com")
    svc = _svc(db_session)

    assert account.is_password_set is False
    result = await svc.update_password("s3cret", account)
    assert result is account
    assert account.is_password_set is True, "update_password 后 is_password_set 应为 True"
    assert account.password_salt
    assert compare_password("s3cret", account.password, account.password_salt)
    assert not compare_password("wrong", account.password, account.password_salt)


@pytest.mark.asyncio
async def test_password_login_success_records_login_ip(db_session):
    account = await _account(db_session, "u4", "u4@example.com")
    svc = _svc(db_session)
    await svc.update_password("pw-123", account)

    token = set_request_context(RequestContext(remote_addr="203.0.113.7"))
    try:
        creds = await svc.password_login("u4@example.com", "pw-123")
    finally:
        reset_request_context(token)

    assert creds["access_token"]
    payload = JwtService.parse_token(creds["access_token"])
    assert payload["sub"] == str(account.id)
    assert account.last_login_ip == "203.0.113.7", "last_login_ip 应取请求上下文 remote_addr"


@pytest.mark.asyncio
async def test_password_login_wrong_password_or_missing_account_raises(db_session):
    account = await _account(db_session, "u5", "u5@example.com")
    svc = _svc(db_session)
    await svc.update_password("pw-123", account)

    with pytest.raises(FailedException):
        await svc.password_login("u5@example.com", "wrong")
    with pytest.raises(FailedException):
        await svc.password_login("missing@example.com", "pw-123")


@pytest.mark.asyncio
async def test_create_account_and_oauth_lookup(db_session):
    svc = _svc(db_session)

    account = await svc.create_account(name="u6", email="u6@example.com")
    assert account.id is not None

    account_oauth = AccountOAuth(
        account_id=str(account.id), provider="github", openid="oid-1", encrypted_token="tok"
    )
    db_session.add(account_oauth)
    await db_session.flush()

    found = await svc.get_account_oauth_by_provider_name_and_openid("github", "oid-1")
    assert found is not None and found.id == account_oauth.id
    assert await svc.get_account_oauth_by_provider_name_and_openid("github", "nope") is None


@pytest.mark.asyncio
async def test_access_token_fixture_roundtrip(db_session, access_token):
    """access_token fixture：可解析、iss 正确、sub 指向真实库账号（空库时 fixture 现场建号）。"""
    payload = JwtService.parse_token(access_token)
    assert payload["iss"] == "llmops"
    account = (
        await db_session.execute(select(Account).where(Account.id == payload["sub"]))
    ).scalar_one()
    assert account is not None
