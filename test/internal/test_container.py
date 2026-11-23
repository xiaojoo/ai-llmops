#!/usr/bin/env python
"""container 纯工厂冒烟测试——每个工厂用 db_session 构造，断言实例类型与依赖接线。

覆盖认证/账号簇工厂；新增会话/对话簇工厂（会话/摘要/反思/语言模型/选择提交 +
chat_runner/open_api/web_app/app_service 深依赖工厂——retrieval/memory resolver 等由调用方传入）。
"""
from unittest.mock import MagicMock

import pytest

from internal import container
from internal.service import (
    AccountService,
    ApiKeyService,
    AppService,
    ChatRunner,
    ConversationService,
    JwtService,
    LanguageModelService,
    OAuthService,
    OpenAPIService,
    ProceduralMemoryService,
    ReflectionService,
    SystemConfigService,
    WebAppService,
)
from internal.service.choice_service import ChoiceService


def test_create_jwt_service_returns_singleton():
    """无 session 服务：模块级单例，多次构造同一实例。"""
    assert container.create_jwt_service() is container.jwt_service
    assert isinstance(container.jwt_service, JwtService)


@pytest.mark.asyncio
async def test_container_factories_construct_with_db_session(db_session):
    """每个工厂用 db_session 构造成功，实例类型正确、session 正确接线。"""
    account_service = container.create_account_service(db_session)
    api_key_service = container.create_api_key_service(db_session)
    oauth_service = container.create_oauth_service(db_session)
    system_config_service = container.create_system_config_service(db_session)

    assert isinstance(account_service, AccountService)
    assert account_service.db is db_session
    assert account_service.jwt_service is container.jwt_service

    assert isinstance(api_key_service, ApiKeyService)
    assert api_key_service.db is db_session

    assert isinstance(oauth_service, OAuthService)
    assert oauth_service.db is db_session
    assert isinstance(oauth_service.account_service, AccountService)
    assert oauth_service.account_service.db is db_session
    assert oauth_service.jwt_service is container.jwt_service

    assert isinstance(system_config_service, SystemConfigService)
    assert system_config_service.db is db_session


@pytest.mark.asyncio
async def test_t6_factories_construct_with_db_session(db_session):
    """会话/对话簇工厂用 db_session 构造成功，实例类型正确、session 正确接线。"""
    language_model_service = container.create_language_model_service(db_session)
    assert isinstance(language_model_service, LanguageModelService)
    assert language_model_service.db is db_session

    conversation_service = container.create_conversation_service(db_session)
    assert isinstance(conversation_service, ConversationService)
    assert conversation_service.db is db_session
    assert isinstance(conversation_service.language_model_service, LanguageModelService)
    assert isinstance(conversation_service.reflection_service, ReflectionService)
    assert isinstance(conversation_service.reflection_service.procedural_memory_service, ProceduralMemoryService)

    assert isinstance(container.create_reflection_service(db_session), ReflectionService)
    assert isinstance(container.create_procedural_memory_service(db_session), ProceduralMemoryService)

    choice_service = container.create_choice_service(redis_client=MagicMock())
    assert isinstance(choice_service, ChoiceService)


@pytest.mark.asyncio
async def test_language_model_manager_has_callable_custom_loader(db_session):
    """FIX 4：容器构造的 LanguageModelManager 必须注入可调用的 custom_model_loader，
    否则 custom_api 懒合并（按账号）在生产路径无法触发。"""
    language_model_service = container.create_language_model_service(db_session)
    loader = language_model_service.language_model_manager.custom_model_loader
    assert callable(loader)


@pytest.mark.asyncio
async def test_t6_deep_factories_wire_dependencies(db_session):
    """chat_runner/open_api/web_app/app_service 工厂——深依赖由调用方传入，依赖接线正确。

    retrieval_service / memory_provider_resolver / attachment_service / cos_service
    以替身传入，验证工厂接线而非深依赖行为。
    """
    retrieval_service = MagicMock()
    memory_provider_resolver = MagicMock()
    attachment_service = MagicMock()

    chat_runner = container.create_chat_runner(
        db_session,
        retrieval_service=retrieval_service,
        memory_provider_resolver=memory_provider_resolver,
    )
    assert isinstance(chat_runner, ChatRunner)
    assert chat_runner.db is db_session
    assert chat_runner.retrieval_service is retrieval_service
    assert chat_runner.memory_provider_resolver is memory_provider_resolver
    assert isinstance(chat_runner.conversation_service, ConversationService)
    assert isinstance(chat_runner.app_config_service, container.AppConfigService)

    app_service = container.create_app_service(
        db_session,
        retrieval_service=retrieval_service,
        redis_client=MagicMock(),
        cos_service=MagicMock(),
        memory_provider_resolver=memory_provider_resolver,
        attachment_service=attachment_service,
    )
    assert isinstance(app_service, AppService)
    assert app_service.chat_runner is chat_runner or isinstance(app_service.chat_runner, ChatRunner)

    open_api_service = container.create_open_api_service(
        db_session,
        retrieval_service=retrieval_service,
        app_service=app_service,
    )
    assert isinstance(open_api_service, OpenAPIService)
    assert open_api_service.app_service is app_service

    web_app_service = container.create_web_app_service(
        db_session,
        retrieval_service=retrieval_service,
        memory_provider_resolver=memory_provider_resolver,
        attachment_service=attachment_service,
    )
    assert isinstance(web_app_service, WebAppService)
    assert web_app_service.attachment_service is attachment_service
