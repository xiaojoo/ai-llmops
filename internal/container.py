#!/usr/bin/env python
"""组合根：纯工厂（不依赖 FastAPI）。

Web 侧 Dep 薄适配层由 internal/server/ 实现：
    async def get_account_service(session: SessionLike = Depends(get_db)):
        return create_account_service(session)
后台线程/Celery 直接 create_*_service(session)（session 来自 worker_run）。
深依赖（retrieval_service/memory_provider_resolver/
attachment_service/cos_service/redis_client）由调用方传入。
"""
from redis import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from package.database import RequestSessionProxy

# handler 工厂经 RequestSessionProxy（Web 请求期解析）或真实 AsyncSession（worker_run/测试）
# 调用——标注统一为 SessionLike，避免鸭子类型标注失真。
SessionLike = AsyncSession | RequestSessionProxy

from internal.core.language_model import LanguageModelManager
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.core.tools.builtin_tools.categories import BuiltinCategoryManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.core.builtin_apps import BuiltinAppManager
from internal.service.account_service import AccountService
from internal.service.api_key_service import ApiKeyService
from internal.service.app_config_service import AppConfigService
from internal.service.app_service import AppService
from internal.service.attachment_service import AttachmentService
from internal.service.chat_runner import ChatRunner
from internal.service.choice_service import ChoiceService
from internal.service.conversation_service import ConversationService
from internal.service.cos_service import CosService
from internal.service.jwt_service import JwtService
from internal.service.language_model_service import LanguageModelService
from internal.service.memory_provider import MemoryProviderResolver
from internal.service.oauth_service import OAuthService
from internal.service.open_api_service import OpenAPIService
from internal.service.procedural_memory_service import ProceduralMemoryService
from internal.service.reflection_service import ReflectionService
from internal.service.retrieval_service import RetrievalService
from internal.service.system_config_service import SystemConfigService
from internal.service.web_app_service import WebAppService
from internal.service.dataset_service import DatasetService
from internal.service.document_service import DocumentService
from internal.service.indexing_service import IndexingService
from internal.service.segment_service import SegmentService
from internal.service.keyword_table_service import KeywordTableService
from internal.service.upload_file_service import UploadFileService
from internal.service.minio_service import MinioService
from internal.service.embeddings_service import EmbeddingsService
from internal.service.ltp_service import LtpService
from internal.service.vector_database_service import VectorDatabaseService
from internal.service.weaviate_vector_service import WeaviateVectorService

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 类型检查/IDE 专用：handler/service 类在下方工厂函数内局部导入（防循环依赖），
    # 此处声明让字符串注解 -> "XxxHandler" / "XxxService" 可被 PyCharm/类型检查解析。
    from internal.handler.app_handler import AppHandler
    from internal.handler.account_handler import AccountHandler
    from internal.handler.auth_handler import AuthHandler
    from internal.handler.ai_handler import AIHandler
    from internal.handler.api_key_handler import ApiKeyHandler
    from internal.handler.api_tool_handler import ApiToolHandler
    from internal.handler.analysis_handler import AnalysisHandler
    from internal.handler.assistant_agent_handler import AssistantAgentHandler
    from internal.handler.audio_handler import AudioHandler
    from internal.handler.builtin_app_handler import BuiltinAppHandler
    from internal.handler.builtin_tool_handler import BuiltinToolHandler
    from internal.handler.chroma_file_handler import ChromaFileHandler
    from internal.handler.chroma_vector_handler import ChromaVectorHandler
    from internal.handler.conversation_handler import ConversationHandler
    from internal.handler.custom_llm_model_handler import CustomLlmModelHandler
    from internal.handler.dataset_handler import DatasetHandler
    from internal.handler.document_handler import DocumentHandler
    from internal.handler.feishu_handler import FeishuHandler
    from internal.handler.file_proxy_handler import FileProxyHandler
    from internal.handler.language_model_handler import LanguageModelHandler
    from internal.handler.oauth_handler import OAuthHandler
    from internal.handler.open_api_handler import OpenAPIHandler
    from internal.handler.segment_handler import SegmentHandler
    from internal.handler.skill_handler import SkillHandler
    from internal.handler.system_config_handler import SystemConfigHandler
    from internal.handler.upload_file_handler import UploadFileHandler
    from internal.handler.weaviate_vector_handler import WeaviateVectorHandler
    from internal.handler.web_app_handler import WebAppHandler
    from internal.handler.workflow_handler import WorkflowHandler

    from internal.service.audio_service import AudioService
    from internal.service.skill_service import SkillService
    from internal.service.feishu_service import FeishuService
    from internal.service.ai_service import AIService
    from internal.service.api_tool_service import ApiToolService
    from internal.service.builtin_tool_service import BuiltinToolService
    from internal.service.analysis_service import AnalysisService
    from internal.service.assistant_agent_service import AssistantAgentService
    from internal.service.builtin_app_service import BuiltinAppService
    from internal.service.chroma_file_service import ChromaFileService
    from internal.service.chroma_vector_service import ChromaVectorService
    from internal.service.workflow_service import WorkflowService
from internal.service.process_rule_service import ProcessRuleService
from internal.service.user_memory_service import UserMemoryService
from internal.service.episodic_memory_service import EpisodicMemoryService
from internal.service.sub_task_service import SubTaskService
from internal.service.memory_provider.builtin_provider import BuiltinMemoryProvider
from internal.service.memory_provider.tencent_provider import TencentMemoryProvider
from internal.core.tools.memory_tools import MemoryTools

# 无 session 服务 → 模块级单例（构造一次）
jwt_service = JwtService()


def _get_sync_redis() -> Redis | None:
    """惰性获取同步 Redis 客户端（init_redis 后可用）。"""
    import internal.extensions.redis as redis_mod
    return redis_mod.sync_redis_client


def create_jwt_service() -> JwtService:
    """JwtService 无 session 依赖，返回模块级单例。"""
    return jwt_service


def create_account_service(session: SessionLike) -> AccountService:
    """账号服务工厂：db + jwt_service 单例。"""
    return AccountService(db=session, jwt_service=jwt_service)


def create_api_key_service(session: SessionLike) -> ApiKeyService:
    """API 秘钥服务工厂。"""
    return ApiKeyService(db=session)


def create_oauth_service(session: SessionLike) -> OAuthService:
    """第三方授权认证服务工厂：依赖 account_service 与 jwt_service 单例。"""
    return OAuthService(
        db=session,
        account_service=create_account_service(session),
        jwt_service=jwt_service,
    )


def create_system_config_service(session: SessionLike) -> SystemConfigService:
    """系统配置服务工厂。"""
    return SystemConfigService(db=session)


# --- 工厂 ---


def create_custom_llm_model_service(session: SessionLike) -> "CustomLlmModelService":
    """自定义 API 大语言模型服务工厂。"""
    from internal.service.custom_llm_model_service import CustomLlmModelService
    return CustomLlmModelService(db=session)


def _make_custom_model_loader(session: SessionLike):
    """构造 custom_model_loader：懒加载当前账号的自定义模型。

    loader 是异步回调 `(account_id) -> Awaitable[list[ApiLlmModel]]`，
    在 manager 构造时仅闭包绑定服务（并不立即调用）；真正调用发生在
    merge_account_custom_models / get_provider_async（异步上下文）。
    """
    svc = create_custom_llm_model_service(session)
    return lambda account_id: svc.list_models_for_account(account_id)


def create_language_model_service(session: SessionLike) -> LanguageModelService:
    """语言模型服务工厂：模型加载走线程池桥接（asyncio.to_thread）。"""
    return LanguageModelService(
        db=session,
        language_model_manager=LanguageModelManager(custom_model_loader=_make_custom_model_loader(session)),
    )


def create_app_config_service(session: SessionLike) -> AppConfigService:
    """应用配置服务工厂。"""
    language_model_manager = LanguageModelManager(custom_model_loader=_make_custom_model_loader(session))
    return AppConfigService(
        db=session,
        api_provider_manager=ApiProviderManager(),
        builtin_provider_manager=BuiltinProviderManager(),
        language_model_manager=language_model_manager,
        language_model_service=LanguageModelService(db=session, language_model_manager=language_model_manager),
    )


def create_procedural_memory_service(session: SessionLike) -> ProceduralMemoryService:
    """程序记忆服务工厂。"""
    return ProceduralMemoryService(db=session)


def create_reflection_service(
        session: SessionLike,
        *,
        language_model_service: LanguageModelService | None = None,
) -> ReflectionService:
    """反馈反思服务工厂：供 create_conversation_service 依赖。"""
    return ReflectionService(
        db=session,
        language_model_service=language_model_service or create_language_model_service(session),
        procedural_memory_service=create_procedural_memory_service(session),
    )


def create_conversation_service(session: SessionLike) -> ConversationService:
    """会话服务工厂：db + language_model_service + reflection_service。"""
    language_model_service = create_language_model_service(session)
    return ConversationService(
        db=session,
        language_model_service=language_model_service,
        reflection_service=create_reflection_service(session, language_model_service=language_model_service),
    )


def create_choice_service(redis_client: Redis) -> ChoiceService:
    """用户选择提交服务工厂：无 session，依赖同步 Redis 客户端。"""
    return ChoiceService(redis_client=redis_client)


def create_chat_runner(
        session: SessionLike,
        *,
        retrieval_service: RetrievalService,
        memory_provider_resolver: MemoryProviderResolver,
) -> ChatRunner:
    """统一对话执行器工厂：retrieval_service / memory_provider_resolver 由调用方传入。"""
    language_model_service = create_language_model_service(session)
    return ChatRunner(
        db=session,
        retrieval_service=retrieval_service,
        app_config_service=create_app_config_service(session),
        conversation_service=create_conversation_service(session),
        language_model_service=language_model_service,
        memory_provider_resolver=memory_provider_resolver,
    )


def create_open_api_service(
        session: SessionLike,
        *,
        retrieval_service: RetrievalService,
        app_service: AppService,
) -> OpenAPIService:
    """开放 API 服务工厂：retrieval_service / app_service 由调用方传入。"""
    language_model_service = create_language_model_service(session)
    return OpenAPIService(
        db=session,
        app_service=app_service,
        app_config_service=create_app_config_service(session),
        retrieval_service=retrieval_service,
        conversation_service=create_conversation_service(session),
        language_model_service=language_model_service,
    )


def create_web_app_service(
        session: SessionLike,
        *,
        retrieval_service: RetrievalService,
        memory_provider_resolver: MemoryProviderResolver,
        attachment_service: AttachmentService,
) -> WebAppService:
    """WebApp 服务工厂：retrieval_service / memory_provider_resolver / attachment_service 由调用方传入。"""
    language_model_service = create_language_model_service(session)
    redis_client = _get_sync_redis()
    return WebAppService(
        db=session,
        retrieval_service=retrieval_service,
        app_service=create_app_service(
            session,
            retrieval_service=retrieval_service,
            redis_client=redis_client,
            cos_service=create_cos_service(session),
            memory_provider_resolver=memory_provider_resolver,
            attachment_service=attachment_service,
        ),
        app_config_service=create_app_config_service(session),
        conversation_service=create_conversation_service(session),
        language_model_service=language_model_service,
        chat_runner=create_chat_runner(
            session,
            retrieval_service=retrieval_service,
            memory_provider_resolver=memory_provider_resolver,
        ),
        memory_provider_resolver=memory_provider_resolver,
        attachment_service=attachment_service,
    )


def create_app_service(
        session: SessionLike,
        *,
        retrieval_service: RetrievalService,
        redis_client: Redis,
        cos_service: CosService,
        memory_provider_resolver: MemoryProviderResolver,
        attachment_service: AttachmentService | None = None,
) -> AppService:
    """应用服务工厂：retrieval_service / cos_service / attachment_service 与
    memory_provider_resolver 由调用方传入。
    """
    language_model_manager = LanguageModelManager(custom_model_loader=_make_custom_model_loader(session))
    chat_runner = create_chat_runner(
        session,
        retrieval_service=retrieval_service,
        memory_provider_resolver=memory_provider_resolver,
    )
    return AppService(
        db=session,
        conversation_service=create_conversation_service(session),
        builtin_provider_manager=BuiltinProviderManager(),
        api_provider_manager=ApiProviderManager(),
        retrieval_service=retrieval_service,
        redis_client=redis_client,
        cos_service=cos_service,
        app_config_service=create_app_config_service(session),
        language_model_service=create_language_model_service(session),
        language_model_manager=language_model_manager,
        chat_runner=chat_runner,
        memory_provider_resolver=memory_provider_resolver,
        attachment_service=attachment_service,
    )


# --- 工厂 ---


# 模块级单例：无 session 服务（构造一次）
_ltp_service = LtpService()


def create_ltp_service() -> LtpService:
    """LTP 分词服务工厂（无 session，模块级单例）。"""
    return _ltp_service


def create_embeddings_service(redis_client: Redis) -> EmbeddingsService:
    """文本嵌入服务工厂。"""
    return EmbeddingsService(redis=redis_client)


def create_keyword_table_service(session: SessionLike, redis_client: Redis) -> KeywordTableService:
    """关键词表服务工厂。"""
    return KeywordTableService(db=session, redis_client=redis_client)


def create_vector_database_service(redis_client: Redis) -> VectorDatabaseService:
    """向量数据库服务工厂。"""
    return VectorDatabaseService(
        embeddings_service=create_embeddings_service(redis_client),
    )


def create_retrieval_service(session: SessionLike, redis_client: Redis) -> RetrievalService:
    """检索服务工厂。"""
    return RetrievalService(
        db=session,
        ltp_service=create_ltp_service(),
        vector_database_service=create_vector_database_service(redis_client),
    )


def create_dataset_service(session: SessionLike, redis_client: Redis) -> DatasetService:
    """知识库服务工厂。"""
    return DatasetService(
        db=session,
        retriever_service=create_retrieval_service(session, redis_client),
    )


def create_upload_file_service(session: SessionLike) -> UploadFileService:
    """上传文件服务工厂。"""
    return UploadFileService(db=session)


def create_cos_service(session: SessionLike) -> CosService:
    """文件存储服务工厂。"""
    return CosService(
        upload_file_service=create_upload_file_service(session),
        minio_service=MinioService(),
    )


def create_attachment_service(session: SessionLike) -> AttachmentService:
    """附件解析服务工厂。"""
    from internal.core.file_extractor.file_extractor import FileExtractor
    return AttachmentService(
        db=session,
        file_extractor=FileExtractor(),
        cos_service=create_cos_service(session),
    )


def create_weaviate_vector_service(session: SessionLike, redis_client: Redis) -> WeaviateVectorService:
    """Weaviate 向量服务工厂。"""
    return WeaviateVectorService(
        db=session,
        embeddings_service=create_embeddings_service(redis_client),
        redis_client=redis_client,
    )


def create_document_service(session: SessionLike, redis_client: Redis) -> DocumentService:
    """文档服务工厂。"""
    return DocumentService(db=session, redis_client=redis_client)


def create_indexing_service(session: SessionLike, redis_client: Redis) -> IndexingService:
    """索引构建服务工厂。"""
    from internal.core.file_extractor import FileExtractor
    return IndexingService(
        db=session,
        file_extractor=FileExtractor(),
        process_rule_service=ProcessRuleService(),
        embeddings_service=create_embeddings_service(redis_client),
        ltp_service=create_ltp_service(),
        keyword_table_service=create_keyword_table_service(session, redis_client),
        vector_database_service=create_vector_database_service(redis_client),
        redis_client=redis_client,
    )


def create_segment_service(session: SessionLike, redis_client: Redis) -> SegmentService:
    """片段服务工厂。"""
    return SegmentService(
        db=session,
        redis_client=redis_client,
        keyword_table_service=create_keyword_table_service(session, redis_client),
        vector_database_service=create_vector_database_service(redis_client),
        embeddings_service=create_embeddings_service(redis_client),
        ltp_service=create_ltp_service(),
    )


# --- 工厂 ---


def create_sub_task_service(session: SessionLike) -> SubTaskService:
    """子任务断点服务工厂。"""
    return SubTaskService(db=session)


def create_user_memory_service(session: SessionLike) -> UserMemoryService:
    """用户事实记忆服务工厂。"""
    return UserMemoryService(
        db=session,
        language_model_service=create_language_model_service(session),
    )


def create_episodic_memory_service(session: SessionLike) -> EpisodicMemoryService:
    """情景记忆服务工厂。"""
    from internal.service.embeddings_service import EmbeddingsService
    return EpisodicMemoryService(
        db=session,
        language_model_service=create_language_model_service(session),
        embeddings_service=EmbeddingsService(redis=None),
        vector_database_service=create_vector_database_service(None),
    )


def create_memory_tools(session: SessionLike) -> MemoryTools:
    """记忆工具集工厂。"""
    return MemoryTools(
        db=session,
        user_memory_service=create_user_memory_service(session),
        episodic_memory_service=create_episodic_memory_service(session),
        procedural_memory_service=create_procedural_memory_service(session),
    )


def create_builtin_memory_provider(session: SessionLike) -> BuiltinMemoryProvider:
    """内置记忆提供者工厂。"""
    return BuiltinMemoryProvider(
        user_memory_service=create_user_memory_service(session),
        episodic_memory_service=create_episodic_memory_service(session),
        procedural_memory_service=create_procedural_memory_service(session),
        memory_tools=create_memory_tools(session),
    )


def create_tencent_memory_provider(session: SessionLike) -> TencentMemoryProvider:
    """腾讯记忆提供者工厂。"""
    return TencentMemoryProvider(
        system_config_service=create_system_config_service(session),
    )


def create_memory_provider_resolver(session: SessionLike) -> MemoryProviderResolver:
    """记忆提供者解析器工厂。"""
    return MemoryProviderResolver(
        system_config_service=create_system_config_service(session),
        builtin_provider=create_builtin_memory_provider(session),
        tencent_provider=create_tencent_memory_provider(session),
    )


# --- 工厂 ---


def create_audio_service(session: SessionLike) -> "AudioService":
    """语音服务工厂。"""
    from internal.service.audio_service import AudioService
    redis_client = _get_sync_redis()
    return AudioService(
        db=session,
        app_service=create_app_service(
            session,
            retrieval_service=create_retrieval_service(session, redis_client),
            redis_client=redis_client,
            cos_service=create_cos_service(session),
            memory_provider_resolver=create_memory_provider_resolver(session),
            attachment_service=create_attachment_service(session),
        ),
    )


def create_skill_service(session: SessionLike) -> "SkillService":
    """技能服务工厂。"""
    from internal.service.skill_service import SkillService
    return SkillService(
        db=session,
        minio_service=MinioService(),
    )


def create_feishu_service() -> "FeishuService":
    """飞书服务工厂（无 session，模块级单例）。"""
    from internal.service.feishu_service import FeishuService
    return FeishuService()


def create_ai_service(session: SessionLike) -> "AIService":
    """AI 服务工厂。"""
    from internal.service.ai_service import AIService
    return AIService(
        db=session,
        conversation_service=create_conversation_service(session),
    )


def create_api_tool_service(session: SessionLike) -> "ApiToolService":
    """API 工具服务工厂。"""
    from internal.service.api_tool_service import ApiToolService
    return ApiToolService(
        db=session,
        api_provider_manager=ApiProviderManager(),
    )


def create_builtin_tool_service() -> "BuiltinToolService":
    """内置工具服务工厂（无 session）。"""
    from internal.service.builtin_tool_service import BuiltinToolService
    return BuiltinToolService(
        builtin_provider_manager=BuiltinProviderManager(),
        builtin_category_manager=BuiltinCategoryManager(),
    )


# --- 工厂 ---


def create_app_handler(session: SessionLike) -> "AppHandler":
    """应用 Handler 工厂。

    AppHandler 依赖多个服务，需要完整构造依赖链。
    """
    from internal.handler.app_handler import AppHandler
    redis_client = _get_sync_redis()
    retrieval_service = create_retrieval_service(session, redis_client)
    memory_provider_resolver = create_memory_provider_resolver(session)
    return AppHandler(
        app_service=create_app_service(
            session,
            retrieval_service=retrieval_service,
            redis_client=redis_client,
            cos_service=create_cos_service(session),
            memory_provider_resolver=memory_provider_resolver,
            attachment_service=create_attachment_service(session),
        ),
        retrieval_service=retrieval_service,
        language_model_manager=LanguageModelManager(custom_model_loader=_make_custom_model_loader(session)),
        assistant_agent_service=create_assistant_agent_service(session),
        user_memory_service=create_user_memory_service(session),
        episodic_memory_service=create_episodic_memory_service(session),
        procedural_memory_service=create_procedural_memory_service(session),
        app_config_service=create_app_config_service(session),
        tencent_provider=create_tencent_memory_provider(session),
        choice_service=create_choice_service(redis_client),
    )


def create_account_handler(session: SessionLike) -> "AccountHandler":
    """账号 Handler 工厂。"""
    from internal.handler.account_handler import AccountHandler
    return AccountHandler(
        account_service=create_account_service(session),
    )


def create_auth_handler(session: SessionLike) -> "AuthHandler":
    """认证 Handler 工厂。"""
    from internal.handler.auth_handler import AuthHandler
    return AuthHandler(
        account_service=create_account_service(session),
    )


def create_ai_handler(session: SessionLike) -> "AIHandler":
    """AI Handler 工厂。"""
    from internal.handler.ai_handler import AIHandler
    return AIHandler(
        ai_service=create_ai_service(session),
    )


def create_api_key_handler(session: SessionLike) -> "ApiKeyHandler":
    """API Key Handler 工厂。"""
    from internal.handler.api_key_handler import ApiKeyHandler
    return ApiKeyHandler(
        api_key_service=create_api_key_service(session),
    )


def create_api_tool_handler(session: SessionLike) -> "ApiToolHandler":
    """API 工具 Handler 工厂。"""
    from internal.handler.api_tool_handler import ApiToolHandler
    return ApiToolHandler(
        api_tool_service=create_api_tool_service(session),
    )


def create_analysis_service(session: SessionLike) -> "AnalysisService":
    """统计分析服务工厂。"""
    from internal.service.analysis_service import AnalysisService
    redis_client = _get_sync_redis()
    return AnalysisService(
        db=session,
        redis_client=redis_client,
        app_service=create_app_service(
            session,
            retrieval_service=create_retrieval_service(session, redis_client),
            redis_client=redis_client,
            cos_service=create_cos_service(session),
            memory_provider_resolver=create_memory_provider_resolver(session),
            attachment_service=create_attachment_service(session),
        ),
    )


def create_analysis_handler(session: SessionLike) -> "AnalysisHandler":
    """应用统计 Handler 工厂。"""
    from internal.handler.analysis_handler import AnalysisHandler
    return AnalysisHandler(
        analysis_service=create_analysis_service(session),
    )


def create_assistant_agent_service(session: SessionLike) -> "AssistantAgentService":
    """辅助智能体服务工厂。"""
    from internal.service.assistant_agent_service import AssistantAgentService
    from internal.service.chroma_service import ChromaService
    language_model_service = create_language_model_service(session)
    embeddings_service = create_embeddings_service(_get_sync_redis())
    return AssistantAgentService(
        db=session,
        chroma_service=ChromaService(embeddings_service=embeddings_service),
        conversation_service=create_conversation_service(session),
        language_model_service=language_model_service,
        attachment_service=create_attachment_service(session),
    )


def create_assistant_agent_handler(session: SessionLike) -> "AssistantAgentHandler":
    """辅助 Agent Handler 工厂。"""
    from internal.handler.assistant_agent_handler import AssistantAgentHandler
    redis_client = _get_sync_redis()
    return AssistantAgentHandler(
        assistant_agent_service=create_assistant_agent_service(session),
        choice_service=create_choice_service(redis_client),
    )


def create_audio_handler(session: SessionLike) -> "AudioHandler":
    """语音 Handler 工厂。"""
    from internal.handler.audio_handler import AudioHandler
    return AudioHandler(
        audio_service=create_audio_service(session),
    )


def create_builtin_app_service(session: SessionLike) -> "BuiltinAppService":
    """内置应用服务工厂。"""
    from internal.service.builtin_app_service import BuiltinAppService
    return BuiltinAppService(
        db=session,
        builtin_app_manager=BuiltinAppManager(),
    )


def create_builtin_app_handler(session: SessionLike) -> "BuiltinAppHandler":
    """内置应用 Handler 工厂。"""
    from internal.handler.builtin_app_handler import BuiltinAppHandler
    return BuiltinAppHandler(
        builtin_app_service=create_builtin_app_service(session),
        language_model_manager=LanguageModelManager(custom_model_loader=_make_custom_model_loader(session)),
    )


def create_builtin_tool_handler() -> "BuiltinToolHandler":
    """内置工具 Handler 工厂。"""
    from internal.handler.builtin_tool_handler import BuiltinToolHandler
    return BuiltinToolHandler(
        builtin_tool_service=create_builtin_tool_service(),
    )


def create_chroma_file_service() -> "ChromaFileService":
    """Chroma 文件服务工厂。"""
    from internal.service.chroma_file_service import ChromaFileService
    return ChromaFileService()


def create_chroma_file_handler(session: SessionLike) -> "ChromaFileHandler":
    """Chroma 文件 Handler 工厂。"""
    from internal.handler.chroma_file_handler import ChromaFileHandler
    return ChromaFileHandler(
        chroma_file_service=create_chroma_file_service(),
    )


def create_chroma_vector_service() -> "ChromaVectorService":
    """Chroma 向量服务工厂。"""
    from internal.service.chroma_vector_service import ChromaVectorService
    from internal.service.chroma_service import ChromaService
    redis_client = _get_sync_redis()
    return ChromaVectorService(chroma_service=ChromaService(embeddings_service=create_embeddings_service(redis_client)))


def create_chroma_vector_handler(session: SessionLike) -> "ChromaVectorHandler":
    """Chroma 向量 Handler 工厂。"""
    from internal.handler.chroma_vector_handler import ChromaVectorHandler
    return ChromaVectorHandler(
        chroma_vector_service=create_chroma_vector_service(),
    )


def create_conversation_handler(session: SessionLike) -> "ConversationHandler":
    """会话 Handler 工厂。"""
    from internal.handler.conversation_handler import ConversationHandler
    return ConversationHandler(
        conversation_service=create_conversation_service(session),
    )


def create_custom_llm_model_handler(session: SessionLike) -> "CustomLlmModelHandler":
    """自定义 API 大语言模型 Handler 工厂。"""
    from internal.handler.custom_llm_model_handler import CustomLlmModelHandler
    return CustomLlmModelHandler(
        custom_llm_model_service=create_custom_llm_model_service(session),
    )


def create_dataset_handler(session: SessionLike) -> "DatasetHandler":
    """知识库 Handler 工厂。"""
    from internal.handler.dataset_handler import DatasetHandler
    from internal.core.file_extractor import FileExtractor
    return DatasetHandler(
        dataset_service=create_dataset_service(session, _get_sync_redis()),
        file_extractor=FileExtractor(),
    )


def create_document_handler(session: SessionLike) -> "DocumentHandler":
    """文档 Handler 工厂。"""
    from internal.handler.document_handler import DocumentHandler
    return DocumentHandler(
        document_service=create_document_service(session, _get_sync_redis()),
    )


def create_feishu_handler() -> "FeishuHandler":
    """飞书 Handler 工厂。"""
    from internal.handler.feishu_handler import FeishuHandler
    return FeishuHandler(
        feishu_service=create_feishu_service(),
    )


def create_language_model_handler(session: SessionLike) -> "LanguageModelHandler":
    """语言模型 Handler 工厂。"""
    from internal.handler.language_model_handler import LanguageModelHandler
    return LanguageModelHandler(
        language_model_service=create_language_model_service(session),
    )


def create_oauth_handler(session: SessionLike) -> "OAuthHandler":
    """OAuth Handler 工厂。"""
    from internal.handler.oauth_handler import OAuthHandler
    return OAuthHandler(
        oauth_service=create_oauth_service(session),
    )


def create_open_api_handler(session: SessionLike) -> "OpenAPIHandler":
    """OpenAPI Handler 工厂。"""
    from internal.handler.open_api_handler import OpenAPIHandler
    redis_client = _get_sync_redis()
    return OpenAPIHandler(
        open_api_service=create_open_api_service(
            session,
            retrieval_service=create_retrieval_service(session, redis_client),
            app_service=create_app_service(
                session,
                retrieval_service=create_retrieval_service(session, redis_client),
                redis_client=redis_client,
                cos_service=create_cos_service(session),
                memory_provider_resolver=create_memory_provider_resolver(session),
                attachment_service=create_attachment_service(session),
            ),
        ),
    )


def create_segment_handler(session: SessionLike) -> "SegmentHandler":
    """片段 Handler 工厂。"""
    from internal.handler.segment_handler import SegmentHandler
    return SegmentHandler(
        segment_service=create_segment_service(session, _get_sync_redis()),
    )


def create_skill_handler(session: SessionLike) -> "SkillHandler":
    """技能 Handler 工厂。"""
    from internal.handler.skill_handler import SkillHandler
    return SkillHandler(
        skill_service=create_skill_service(session),
    )


def create_system_config_handler(session: SessionLike) -> "SystemConfigHandler":
    """系统配置 Handler 工厂。"""
    from internal.handler.system_config_handler import SystemConfigHandler
    return SystemConfigHandler(
        system_config_service=create_system_config_service(session),
    )


def create_upload_file_handler(session: SessionLike) -> "UploadFileHandler":
    """上传文件 Handler 工厂。"""
    from internal.handler.upload_file_handler import UploadFileHandler
    return UploadFileHandler(
        upload_file_service=create_upload_file_service(session),
        cos_service=create_cos_service(session),
    )


def create_file_proxy_handler() -> "FileProxyHandler":
    """文件代理 Handler 工厂（无需依赖，服务内部构造）。"""
    from internal.handler.file_proxy_handler import FileProxyHandler
    return FileProxyHandler()


def create_weaviate_vector_handler(session: SessionLike) -> "WeaviateVectorHandler":
    """Weaviate 向量 Handler 工厂。"""
    from internal.handler.weaviate_vector_handler import WeaviateVectorHandler
    return WeaviateVectorHandler(
        weaviate_vector_service=create_weaviate_vector_service(session, _get_sync_redis()),
    )


def create_web_app_handler(session: SessionLike) -> "WebAppHandler":
    """WebApp Handler 工厂。"""
    from internal.handler.web_app_handler import WebAppHandler
    redis_client = _get_sync_redis()
    return WebAppHandler(
        web_app_service=create_web_app_service(
            session,
            retrieval_service=create_retrieval_service(session, redis_client),
            memory_provider_resolver=create_memory_provider_resolver(session),
            attachment_service=create_attachment_service(session),
        ),
        choice_service=create_choice_service(redis_client),
    )


def create_workflow_service(session: SessionLike) -> "WorkflowService":
    """工作流服务工厂。"""
    from internal.service.workflow_service import WorkflowService
    return WorkflowService(
        db=session,
        builtin_provider_manager=BuiltinProviderManager(),
    )


def create_workflow_handler(session: SessionLike) -> "WorkflowHandler":
    """工作流 Handler 工厂。"""
    from internal.handler.workflow_handler import WorkflowHandler
    return WorkflowHandler(
        workflow_service=create_workflow_service(session),
    )
