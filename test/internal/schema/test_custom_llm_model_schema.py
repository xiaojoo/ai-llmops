import pytest
from pydantic import ValidationError

from internal.schema.custom_llm_model_schema import (
    CreateCustomLlmModelReq,
    GetCustomLlmModelResp,
)


def test_create_valid():
    req = CreateCustomLlmModelReq(
        name="My Model",
        protocol="anthropic",
        model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-xxx",
        features=["tool_call", "agent_thought"],
        context_window=200000,
        max_output_tokens=8192,
        remark="note",
        icon="https://example.com/i.png",
    )
    assert req.protocol == "anthropic"


def test_create_invalid_protocol():
    with pytest.raises(ValidationError):
        CreateCustomLlmModelReq(name="x", protocol="gemini", model_id="g", features=[])


def test_create_invalid_feature():
    with pytest.raises(ValidationError):
        CreateCustomLlmModelReq(name="x", protocol="openai", model_id="g", features=["vision"])


def test_resp_masks_api_key():
    resp = GetCustomLlmModelResp(
        id="e08f4b44-0000-4000-8000-000000000001",
        name="m",
        protocol="openai",
        model_id="gpt-4o",
        api_key="sk-secret",
        features=["tool_call"],
        context_window=128000,
        max_output_tokens=4096,
        remark="",
        icon="",
        created_at=0,
    )
    assert resp.api_key == "********"
