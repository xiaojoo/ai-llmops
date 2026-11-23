#!/usr/bin/env python
"""ApiKeyService async 化测试（真实 Postgres + db_session 事务回滚）。

覆盖：get_api_by_by_credential（命中/未命中）、is_active 标志存取（middleware 激活校验消费）、
create_api_key / get_api_key（权限校验 ForbiddenException）/ update / delete /
get_api_keys_with_page（原位重实现的分页语义）。
"""
from types import SimpleNamespace

import pytest

from internal.exception import ForbiddenException
from internal.model import Account, ApiKey
from internal.service.api_key_service import ApiKeyService


def _svc(db):
    return ApiKeyService(db=db)


def _create_req(is_active: bool = True, remark: str = ""):
    """CreateApiKeyReq 已转 Pydantic —— 直接用真实模型构造。"""
    from internal.schema.api_key_schema import CreateApiKeyReq
    return CreateApiKeyReq(is_active=is_active, remark=remark)


def _page_req(current_page: int = 1, page_size: int = 20):
    """PaginatorReq 已转 Pydantic —— 直接用 PaginatorReq 构造。"""
    from package.paginator import PaginatorReq
    return PaginatorReq(current_page=current_page, page_size=page_size)


async def _account(db, name: str = "ak") -> Account:
    account = Account(name=name, email=f"{name}@example.com")
    db.add(account)
    await db.flush()
    return account


@pytest.mark.asyncio
async def test_get_api_by_by_credential_found_and_missing(db_session):
    account = await _account(db_session)
    key = ApiKey(account_id=account.id, api_key="llmops-v1/secret-1", is_active=True, remark="r")
    db_session.add(key)
    await db_session.flush()
    svc = _svc(db_session)

    found = await svc.get_api_by_by_credential("llmops-v1/secret-1")
    assert found is not None and found.id == key.id
    assert await svc.get_api_by_by_credential("llmops-v1/nope") is None


@pytest.mark.asyncio
async def test_is_active_flag_preserved(db_session):
    """middleware 的「秘钥不存在或未激活」校验消费 is_active 字段——存取必须保真。"""
    account = await _account(db_session)
    inactive = ApiKey(account_id=account.id, api_key="llmops-v1/inactive", is_active=False, remark="")
    db_session.add(inactive)
    await db_session.flush()
    svc = _svc(db_session)

    found = await svc.get_api_by_by_credential("llmops-v1/inactive")
    assert found.is_active is False


@pytest.mark.asyncio
async def test_create_api_key_and_permission_check(db_session):
    account = await _account(db_session)
    other = await _account(db_session, "ak2")
    svc = _svc(db_session)

    key = await svc.create_api_key(_create_req(is_active=True, remark="my key"), account)
    assert key.id is not None
    assert key.api_key.startswith("llmops-v1/")
    assert key.is_active is True and key.remark == "my key"

    assert (await svc.get_api_key(key.id, account)).id == key.id
    with pytest.raises(ForbiddenException):
        await svc.get_api_key(key.id, other)


@pytest.mark.asyncio
async def test_update_and_delete_api_key(db_session):
    account = await _account(db_session)
    svc = _svc(db_session)
    key = await svc.create_api_key(_create_req(is_active=True, remark="before"), account)

    updated = await svc.update_api_key(key.id, account, remark="after", is_active=False)
    assert updated.remark == "after" and updated.is_active is False

    deleted = await svc.delete_api_key(key.id, account)
    assert deleted.id == key.id
    with pytest.raises(ForbiddenException):
        await svc.get_api_key(key.id, account)


@pytest.mark.asyncio
async def test_get_api_keys_with_page(db_session):
    """原位重实现的分页：total_record/total_page/current_page 与旧 Paginator 语义一致。"""
    account = await _account(db_session)
    svc = _svc(db_session)
    for i in range(3):
        await svc.create_api_key(_create_req(is_active=True, remark=f"key-{i}"), account)

    keys1, paginator1 = await svc.get_api_keys_with_page(_page_req(1, 2), account)
    assert len(keys1) == 2
    assert paginator1.total_record == 3
    assert paginator1.total_page == 2
    assert paginator1.current_page == 1

    keys2, paginator2 = await svc.get_api_keys_with_page(_page_req(2, 2), account)
    assert len(keys2) == 1
    assert paginator2.total_record == 3
