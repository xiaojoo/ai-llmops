#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
custom_llm_model handler 契约测试。

使用 AsyncMock 隔离 CustomLlmModelService，不触 DB/app。
"""
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from internal.handler.custom_llm_model_handler import CustomLlmModelHandler
from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq, UpdateCustomLlmModelReq


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


def _fake_record():
    return SimpleNamespace(
        id=uuid.UUID("e08f4b44-0000-4000-8000-000000000001"),
        name="gpt",
        protocol="openai",
        model_id="gpt-4o",
        base_url="https://x/v1",
        api_key="********",
        features=["tool_call"],
        context_window=128000,
        max_output_tokens=4096,
        remark="",
        icon="",
        created_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_create_handler():
    svc = AsyncMock()
    svc.create = AsyncMock(return_value=None)
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    req = CreateCustomLlmModelReq(name="x", protocol="openai", model_id="gpt-4o", features=[])
    resp = await handler.create_custom_llm_model(FakeUser(), req)
    svc.create.assert_awaited_once()
    assert resp.status_code == 200
    assert json.loads(resp.body)["message"] == "创建自定义模型成功"


@pytest.mark.asyncio
async def test_list_handler():
    svc = AsyncMock()
    svc.list_by_account = AsyncMock(return_value=[_fake_record()])
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    resp = await handler.list_custom_llm_models(FakeUser())
    svc.list_by_account.assert_awaited_once()
    assert resp.status_code == 200
    data = json.loads(resp.body)["data"]
    assert len(data) == 1
    assert data[0]["protocol"] == "openai"
    assert data[0]["api_key"] == "********"


@pytest.mark.asyncio
async def test_get_handler():
    svc = AsyncMock()
    svc.get_by_id = AsyncMock(return_value=_fake_record())
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    resp = await handler.get_custom_llm_model(FakeUser(), uuid.UUID("e08f4b44-0000-4000-8000-000000000001"))
    svc.get_by_id.assert_awaited_once()
    assert resp.status_code == 200
    assert json.loads(resp.body)["data"]["name"] == "gpt"


@pytest.mark.asyncio
async def test_update_handler():
    svc = AsyncMock()
    svc.update_model = AsyncMock(return_value=None)
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    req = UpdateCustomLlmModelReq(name="x", protocol="openai", model_id="gpt-4o", features=[])
    resp = await handler.update_custom_llm_model(FakeUser(), uuid.UUID("e08f4b44-0000-4000-8000-000000000001"), req)
    svc.update_model.assert_awaited_once()
    assert resp.status_code == 200
    assert json.loads(resp.body)["message"] == "更新自定义模型成功"


@pytest.mark.asyncio
async def test_delete_handler():
    svc = AsyncMock()
    svc.delete_model = AsyncMock(return_value=None)
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    resp = await handler.delete_custom_llm_model(FakeUser(), uuid.UUID("e08f4b44-0000-4000-8000-000000000001"))
    svc.delete_model.assert_awaited_once()
    assert resp.status_code == 200
    assert json.loads(resp.body)["message"] == "删除自定义模型成功"


@pytest.mark.asyncio
async def test_get_handler_raises_not_found_when_missing():
    """FIX 4：get 路径在记录缺失（或非本账号）时应抛 NotFoundException，而非静默返回空。"""
    from internal.exception import NotFoundException

    svc = AsyncMock()
    svc.get_by_id = AsyncMock(return_value=None)
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    with pytest.raises(NotFoundException):
        await handler.get_custom_llm_model(FakeUser(), uuid.UUID("e08f4b44-0000-4000-8000-000000000001"))


@pytest.mark.asyncio
async def test_protocol_options_handler():
    svc = AsyncMock()
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    resp = await handler.get_custom_llm_model_protocol_options(FakeUser())
    assert resp.status_code == 200
    labels = [opt["label"] for opt in json.loads(resp.body)["data"]]
    assert labels == ["OpenAI", "Responses", "Anthropic"]
