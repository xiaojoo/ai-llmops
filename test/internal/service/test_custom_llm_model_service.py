#!/usr/bin/env python
"""CustomLlmModelService 测试。

- create：API Key 必须 AES 加密入库（非明文），账号归属正确，且能解密回原文；
- update_model：api_key 为空时保留原密文，非空时重加密（密文变化且可解回新值）；
- delete_model：逻辑删除（is_deleted=True），且未找到/非本账号时抛 NotFoundException；
- list_models_for_account / list_by_account / get_by_id：账号隔离 + 仅返回未删除记录。

说明：仓库 pytest-asyncio 运行在 strict 模式，async 测试须显式标注
@pytest.mark.asyncio，否则协程体不会执行。此为对 brief 附件的必要修正。
"""
import uuid

import pytest

from internal.exception import NotFoundException
from internal.lib.crypto import decrypt_value
from internal.model import ApiLlmModel
from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq, UpdateCustomLlmModelReq
from internal.service.custom_llm_model_service import CustomLlmModelService, _master_key

_USER_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_ID = "22222222-2222-2222-2222-222222222222"
_MISSING_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


class FakeUser:
    id = _USER_ID


def _create_req(name="claude", api_key="sk-ant-secret") -> CreateCustomLlmModelReq:
    return CreateCustomLlmModelReq(
        name=name, protocol="anthropic", model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com", api_key=api_key,
        features=["tool_call"], context_window=200000, max_output_tokens=8192,
    )


def _update_req(api_key: str = "") -> UpdateCustomLlmModelReq:
    return UpdateCustomLlmModelReq(
        name="claude", protocol="anthropic", model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com", api_key=api_key,
        features=["tool_call"], context_window=200000, max_output_tokens=8192,
    )


@pytest.mark.asyncio
async def test_create_and_encrypt(db_session):
    svc = CustomLlmModelService(db=db_session)
    record = await svc.create(_create_req(), FakeUser())
    assert record.protocol == "anthropic"
    # api_key 已加密，不是明文；且能解密回原文
    assert record.api_key != "sk-ant-secret"
    assert decrypt_value(record.api_key, _master_key()) == "sk-ant-secret"
    assert record.account_id == FakeUser().id


@pytest.mark.asyncio
async def test_list_filters_deleted(db_session):
    svc = CustomLlmModelService(db=db_session)
    a = ApiLlmModel(account_id=_USER_ID, name="a", protocol="openai", model_id="gpt-4o", features=[])
    b = ApiLlmModel(account_id=_USER_ID, name="b", protocol="openai", model_id="gpt-4o", features=[], is_deleted=True)
    db_session.add_all([a, b])
    await db_session.commit()
    result = await svc.list_by_account(FakeUser())
    assert [r.name for r in result] == ["a"]


@pytest.mark.asyncio
async def test_get_by_id_account_isolation(db_session):
    svc = CustomLlmModelService(db=db_session)
    other = ApiLlmModel(account_id=_OTHER_ID, name="other", protocol="openai", model_id="g", features=[])
    db_session.add(other)
    await db_session.commit()
    assert await svc.get_by_id(other.id, FakeUser()) is None


@pytest.mark.asyncio
async def test_update_preserves_api_key_when_empty(db_session):
    """update_model 时 api_key 为空：保留原密文（不重加密，不丢密钥）。"""
    svc = CustomLlmModelService(db=db_session)
    record = await svc.create(_create_req(api_key="sk-original"), FakeUser())
    original_enc = record.api_key
    updated = await svc.update_model(record.id, _update_req(api_key=""), FakeUser())
    assert updated.api_key == original_enc
    assert decrypt_value(updated.api_key, _master_key()) == "sk-original"


@pytest.mark.asyncio
async def test_update_reencrypts_when_new_api_key(db_session):
    """update_model 时传入新 api_key：加密值变化，且可解密回新值。"""
    svc = CustomLlmModelService(db=db_session)
    record = await svc.create(_create_req(api_key="sk-original"), FakeUser())
    before = record.api_key  # 更新前的密文
    updated = await svc.update_model(record.id, _update_req(api_key="sk-new"), FakeUser())
    assert updated.api_key != before
    assert decrypt_value(updated.api_key, _master_key()) == "sk-new"


@pytest.mark.asyncio
async def test_delete_soft_deletes(db_session):
    """delete_model 逻辑删除：is_deleted=True，后续 get_by_id 不再可见。"""
    svc = CustomLlmModelService(db=db_session)
    record = await svc.create(_create_req(), FakeUser())
    assert record.is_deleted is False
    await svc.delete_model(record.id, FakeUser())
    assert record.is_deleted is True
    assert await svc.get_by_id(record.id, FakeUser()) is None


@pytest.mark.asyncio
async def test_list_models_for_account_filters_deleted(db_session):
    """list_models_for_account 仅返回指定账号下的未删除记录。"""
    svc = CustomLlmModelService(db=db_session)
    db_session.add_all([
        ApiLlmModel(account_id=_USER_ID, name="keep", protocol="openai", model_id="g", features=[]),
        ApiLlmModel(account_id=_USER_ID, name="gone", protocol="openai", model_id="g", features=[], is_deleted=True),
        ApiLlmModel(account_id=_OTHER_ID, name="other", protocol="openai", model_id="g", features=[]),
    ])
    await db_session.commit()
    names = [r.name for r in await svc.list_models_for_account(_USER_ID)]
    assert names == ["keep"]


@pytest.mark.asyncio
async def test_update_model_raises_when_not_found(db_session):
    svc = CustomLlmModelService(db=db_session)
    with pytest.raises(NotFoundException):
        await svc.update_model(_MISSING_ID, _update_req(), FakeUser())


@pytest.mark.asyncio
async def test_delete_model_raises_when_not_found(db_session):
    svc = CustomLlmModelService(db=db_session)
    with pytest.raises(NotFoundException):
        await svc.delete_model(_MISSING_ID, FakeUser())


@pytest.mark.asyncio
async def test_update_model_raises_when_not_owner(db_session):
    """其他账号的模型对当前账号不可见 → NotFoundException。"""
    svc = CustomLlmModelService(db=db_session)
    other = ApiLlmModel(account_id=_OTHER_ID, name="other", protocol="openai", model_id="g", features=[])
    db_session.add(other)
    await db_session.commit()
    with pytest.raises(NotFoundException):
        await svc.update_model(other.id, _update_req(), FakeUser())


@pytest.mark.asyncio
async def test_delete_model_raises_when_not_owner(db_session):
    """其他账号的模型对当前账号不可见 → NotFoundException。"""
    svc = CustomLlmModelService(db=db_session)
    other = ApiLlmModel(account_id=_OTHER_ID, name="other", protocol="openai", model_id="g", features=[])
    db_session.add(other)
    await db_session.commit()
    with pytest.raises(NotFoundException):
        await svc.delete_model(other.id, FakeUser())
