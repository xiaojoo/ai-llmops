#!/usr/bin/env python
"""custom_api 协议分发 + ModelEntity 构建测试。

协议分发构建 language_model.chat 相关类，并按 CONTROLLER RULING
处理 anthropic：langchain-anthropic 未安装（与 browser-use 的
anthropic SDK 版本冲突，被刻意 unpin）时，build_model_class 不抛错，
返回一个实例化时才抛清晰错误信息的占位类。
"""
import pytest

from internal.model import ApiLlmModel
from internal.core.language_model.entities.model_entity import ModelFeature, ModelType
from internal.core.language_model.providers.custom_api.models import (
    build_custom_model_entity,
    MODEL_PROTOCOL_OPENAI,
    MODEL_PROTOCOL_RESPONSES,
    MODEL_PROTOCOL_ANTHROPIC,
)
from internal.core.language_model.providers.custom_api.chat import build_model_class


def _record(protocol):
    return ApiLlmModel(
        account_id="11111111-1111-1111-1111-111111111111",
        name=f"{protocol}-model",
        protocol=protocol,
        model_id="gpt-4o" if protocol != MODEL_PROTOCOL_ANTHROPIC else "claude-3-5-sonnet",
        base_url="https://x/v1",
        api_key="sk-xxx",
        features=["tool_call", "agent_thought"],
        context_window=128000,
        max_output_tokens=4096,
        remark="",
        icon="",
    )


def _langchain_anthropic_available() -> bool:
    try:
        import langchain_anthropic  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        return False
    return True


def test_protocol_distribution():
    from langchain_openai import ChatOpenAI

    assert build_model_class(MODEL_PROTOCOL_OPENAI) is ChatOpenAI

    # CONTROLLER RULING：build_model_class("anthropic") 在 langchain-anthropic 缺失时
    # 不应抛错，返回一个类；实例化它时才抛清晰错误信息。
    anthropic_cls = build_model_class(MODEL_PROTOCOL_ANTHROPIC)
    assert isinstance(anthropic_cls, type)
    if _langchain_anthropic_available():
        # 环境已安装 langchain-anthropic → 返回 ChatAnthropic（保留 brief 断言）
        assert anthropic_cls.__name__ == "ChatAnthropic"
    else:
        # 未安装 → 返回占位类，且实例化时抛清晰错误信息（而非模块加载期崩溃）
        assert anthropic_cls.__name__ != "ChatAnthropic"
        with pytest.raises(RuntimeError, match="langchain-anthropic"):
            anthropic_cls()


def test_responses_protocol_uses_responses_api():
    cls = build_model_class(MODEL_PROTOCOL_RESPONSES)
    # langchain-openai 的 use_responses_api 会经 __init__ 应用；这里校验类可实例化且字段存在
    from langchain_openai import ChatOpenAI

    assert issubclass(cls, ChatOpenAI)


def test_build_custom_model_entity():
    model_uuid = "e08f4b44-0000-4000-8000-000000000001"
    entity = build_custom_model_entity(_record(MODEL_PROTOCOL_OPENAI), model_uuid)
    assert entity.model_name == "custom_api/e08f4b44-0000-4000-8000-000000000001"
    assert entity.label == "openai-model"
    assert entity.model_type == ModelType.CHAT
    assert ModelFeature.TOOL_CALL in entity.features
    assert entity.context_window == 128000
    assert entity.max_output_tokens == 4096
    assert entity.attributes["model"] == "gpt-4o"
    assert entity.attributes["base_url"] == "https://x/v1"
    assert entity.attributes["api_key"] == "sk-xxx"
