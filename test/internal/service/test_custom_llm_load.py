#!/usr/bin/env python
"""custom_api 模型校验与加载路径测试。

Task 8 目标：
- get_language_models 列出 custom_api 分组（label=自定义API模型），并含 custom_api/<uuid> 模型；
- load_language_model 对 custom_api/<uuid> 按协议（openai → ChatOpenAI）构造真实实例，
  而非掉回默认模型兜底（链路 dispatch 必须真正触发）。

测试使用 fake loader（无 live DB），并先 `await manager.merge_account_custom_models(account_id)`
使 provider 已进 provider_map，验证在「已合并 manager」下 list/detail/load 均命中。
"""
import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace

from internal.core.language_model import LanguageModelManager
from internal.service.language_model_service import LanguageModelService

_ACCOUNT_ID = "11111111-1111-1111-1111-111111111111"
_MODEL_UUID = "e08f4b44-0000-4000-8000-000000000001"


async def _loader():
    from internal.model import ApiLlmModel

    async def loader(account_id):
        return [ApiLlmModel(
            id=_MODEL_UUID,
            account_id=account_id, name="gpt", protocol="openai",
            model_id="gpt-4o", base_url="https://x/v1", api_key="sk-xxx",
            features=["tool_call"], context_window=128000, max_output_tokens=4096,
            remark="", icon="", is_deleted=False,
        )]
    return loader


@pytest.mark.asyncio
async def test_get_language_models_includes_custom():
    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    await manager.merge_account_custom_models(_ACCOUNT_ID)
    models = await svc.get_language_models()
    custom = next((p for p in models if p["name"] == "custom_api"), None)
    assert custom is not None
    assert custom["label"] == "自定义API模型"
    model_names = [m["model"] for m in custom["models"]]
    assert f"custom_api/{_MODEL_UUID}" in model_names


@pytest.mark.asyncio
async def test_load_language_model_custom():
    from langchain_openai import ChatOpenAI

    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    await manager.merge_account_custom_models(_ACCOUNT_ID)
    llm = await svc.load_language_model({
        "provider": "custom_api",
        "model": f"custom_api/{_MODEL_UUID}",
        "parameters": {},
    })
    # 协议 dispatch 必须命中：openai 协议 → ChatOpenAI 实例，而非掉回默认 deepseek 兜底。
    assert isinstance(llm, ChatOpenAI)
    assert getattr(llm, "model_name", None) == "gpt-4o"


@pytest.mark.asyncio
async def test_load_language_model_custom_with_account_id_merges():
    """load_language_model 自带 account_id 时应内部完成懒合并并构造 custom/protocol 实例。

    与 test_load_language_model_custom 的区别：此处调用前**不**手动 merge_account_custom_models，
    完全依赖 load_language_model(account_id=...) 触发合并——即真实推理调用点（chat/open_api/web_app/
    assistant_agent）传 account_id 即可端到端加载 custom_api，而非掉回 deepseek。
    """
    from langchain_openai import ChatOpenAI

    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    # 不预 merge，仅靠 account_id 通道
    llm = await svc.load_language_model({
        "provider": "custom_api",
        "model": f"custom_api/{_MODEL_UUID}",
        "parameters": {},
    }, account_id=_ACCOUNT_ID)
    assert isinstance(llm, ChatOpenAI)
    assert getattr(llm, "model_name", None) == "gpt-4o"


@pytest.mark.asyncio
async def test_load_language_model_custom_without_account_id_raises():
    """无 account_id 且未合并时，custom_api 解析失败应显式抛出，而非静默兜底 deepseek。

    对应用户自选 custom_api 模型却未带账号的入口（如公共 web-app 信息/无账号入口），
    应暴露误配置，绝不静默运行默认模型。
    """
    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    with pytest.raises(Exception):
        await svc.load_language_model({
            "provider": "custom_api",
            "model": f"custom_api/{_MODEL_UUID}",
            "parameters": {},
        })


@pytest.mark.asyncio
async def test_get_language_model_detail_custom():
    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    # 未合并前 get_provider('custom_api') 会抛 NotFound；带 account_id 触发懒合并后命中。
    detail = await svc.get_language_model("custom_api", f"custom_api/{_MODEL_UUID}", account_id=_ACCOUNT_ID)
    assert detail["model"] == f"custom_api/{_MODEL_UUID}"
    assert detail["label"] == "gpt"
    assert detail["metadata"]["protocol"] == "openai"


@pytest.mark.asyncio
async def test_sync_validation_path_post_merge():
    """app_config_service._process_and_validate_model_config / app_service 校验路径：
    它们同步调用 get_provider('custom_api') + get_model_entity('custom_api/<uuid>')，
    只要 manager 已合并，同步路径即可命中（无需改动）。
    """
    from internal.service.app_config_service import AppConfigService

    manager = LanguageModelManager(custom_model_loader=await _loader())
    await manager.merge_account_custom_models(_ACCOUNT_ID)

    # 同步校验路径直接命中：get_provider + get_model_entity 返回实体。
    provider = manager.get_provider("custom_api")
    entity = provider.get_model_entity(f"custom_api/{_MODEL_UUID}")
    assert entity is not None
    assert entity.label == "gpt"

    # 走 _process_and_validate_model_config：custom_api 配置应被放行，而非回退默认。
    cfg_svc = AppConfigService(
        db=MagicMock(),
        api_provider_manager=MagicMock(),
        builtin_provider_manager=MagicMock(),
        language_model_manager=manager,
        language_model_service=MagicMock(),
    )
    validated = cfg_svc._process_and_validate_model_config({
        "provider": "custom_api",
        "model": f"custom_api/{_MODEL_UUID}",
        "parameters": {},
    })
    assert validated["provider"] == "custom_api"
    assert validated["model"] == f"custom_api/{_MODEL_UUID}"


@pytest.mark.asyncio
async def test_entity_decrypts_api_key_after_create(db_session):
    """FIX 1 round-trip：service.create() 加密 api_key 入库 → build_custom_model_entity 解密回明文。

    这是生产真实路径（ORM 记录 api_key 是 AES 密文，非明文）；build_custom_model_entity
    必须用同一主密钥解出原文，否则 load_language_model 构造的实例 auth 必失败。
    """
    from internal.core.language_model.providers.custom_api.models import build_custom_model_entity
    from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq
    from internal.service.custom_llm_model_service import CustomLlmModelService

    req = CreateCustomLlmModelReq(
        name="gpt", protocol="openai", model_id="gpt-4o",
        base_url="https://x/v1", api_key="original-plaintext",
        features=["tool_call"], context_window=128000, max_output_tokens=4096,
    )
    svc = CustomLlmModelService(db=db_session)
    record = await svc.create(req, SimpleNamespace(id=_ACCOUNT_ID))
    # 入库的是密文，不是明文
    assert record.api_key != "original-plaintext"
    # build_custom_model_entity 解出的 attributes["api_key"] 必须是原文
    entity = build_custom_model_entity(record, str(record.id))
    assert entity.attributes["api_key"] == "original-plaintext"


@pytest.mark.asyncio
async def test_get_language_models_no_empty_custom_group():
    """spec 5：无自定义记录时不出现 custom_api 分组（merge 空记录不注入 provider）。"""
    async def empty_loader(account_id):
        return []

    manager = LanguageModelManager(custom_model_loader=empty_loader)
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    models = await svc.get_language_models(account_id=_ACCOUNT_ID)
    assert all(p["name"] != "custom_api" for p in models)
