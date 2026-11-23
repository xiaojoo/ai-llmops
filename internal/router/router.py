"""FastAPI 路由登记（脚本生成 + 手工核对）。

蓝图→APIRouter 映射：
- bp → llmops_router（Depends(get_current_user)）
- openapi_bp → openapi_router（Depends(get_api_key_account)）

公开路由（/webhook）挂在 openapi_router 但无认证依赖。

使用方式：
    from internal.router.router import llmops_router, openapi_router
    app.include_router(llmops_router, dependencies=[Depends(get_current_user)])
    app.include_router(openapi_router, dependencies=[Depends(get_api_key_account)])
"""
from fastapi import APIRouter, Depends

from internal.server.deps import get_current_user, get_api_key_account, request_context_dependency
from package.database import get_db

# ---- llmops 路由（bp 蓝图，认证: get_current_user） ----
# get_db 挂 router 级（而非 app 级）——业务路由需要请求会话，
# 而 app 顶层健康/静态路由（/healthz、/favicon、/docs、/webhook）不应建 DB 会话。
llmops_router = APIRouter(
    prefix="",
    dependencies=[Depends(request_context_dependency), Depends(get_db)],
    responses={404: {"description": "Not found"}},
)

# ---- openapi 路由（openapi_bp 蓝图，认证: get_api_key_account） ----
openapi_router = APIRouter(
    prefix="",
    dependencies=[Depends(request_context_dependency), Depends(get_db)],
    responses={404: {"description": "Not found"}},
)


def register_routes_from_container(app=None):
    """从 container 工厂获取 handler 实例并注册所有路由。

    Args:
        app: FastAPI 实例（可选）。传入时新建带 get_db 依赖的 router 注册路由后
             include 到 app（避免 app 级 get_db 波及健康/静态路由）；
             不传时使用模块级 llmops_router/openapi_router（向后兼容）。
    """
    from internal.container import (
        create_app_handler,
        create_account_handler,
        create_ai_handler,
        create_analysis_handler,
        create_api_key_handler,
        create_api_tool_handler,
        create_assistant_agent_handler,
        create_audio_handler,
        create_auth_handler,
        create_builtin_app_handler,
        create_builtin_tool_handler,
        create_chroma_file_handler,
        create_chroma_vector_handler,
        create_conversation_handler,
        create_custom_llm_model_handler,
        create_dataset_handler,
        create_document_handler,
        create_feishu_handler,
        create_file_proxy_handler,
        create_language_model_handler,
        create_oauth_handler,
        create_open_api_handler,
        create_segment_handler,
        create_skill_handler,
        create_system_config_handler,
        create_upload_file_handler,
        create_weaviate_vector_handler,
        create_web_app_handler,
        create_workflow_handler,
    )

    # 从 container 工厂获取 handler 实例
    # handler 持 RequestSessionProxy（请求期解析），而非 lifespan 的一次性 session
    # （注册后即关闭；请求时 handler 的 db 转发到 Depends(get_db) 的当前请求会话）。
    from package.database import RequestSessionProxy
    proxy = RequestSessionProxy()
    app_handler = create_app_handler(proxy)
    builtin_tool_handler = create_builtin_tool_handler()
    api_tool_handler = create_api_tool_handler(proxy)
    upload_file_handler = create_upload_file_handler(proxy)
    dataset_handler = create_dataset_handler(proxy)
    document_handler = create_document_handler(proxy)
    segment_handler = create_segment_handler(proxy)
    oauth_handler = create_oauth_handler(proxy)
    account_handler = create_account_handler(proxy)
    auth_handler = create_auth_handler(proxy)
    ai_handler = create_ai_handler(proxy)
    language_model_handler = create_language_model_handler(proxy)
    assistant_agent_handler = create_assistant_agent_handler(proxy)
    api_key_handler = create_api_key_handler(proxy)
    open_api_handler = create_open_api_handler(proxy)
    builtin_app_handler = create_builtin_app_handler(proxy)
    workflow_handler = create_workflow_handler(proxy)
    analysis_handler = create_analysis_handler(proxy)
    web_app_handler = create_web_app_handler(proxy)
    conversation_handler = create_conversation_handler(proxy)
    custom_llm_model_handler = create_custom_llm_model_handler(proxy)
    audio_handler = create_audio_handler(proxy)
    skill_handler = create_skill_handler(proxy)
    feishu_handler = create_feishu_handler()
    file_proxy_handler = create_file_proxy_handler()
    chroma_file_handler = create_chroma_file_handler(proxy)
    chroma_vector_handler = create_chroma_vector_handler(proxy)
    weaviate_vector_handler = create_weaviate_vector_handler(proxy)
    system_config_handler = create_system_config_handler(proxy)

    # 注册所有路由
    if app is not None:
        # 新建带 get_db 依赖的 router 注册路由后 include 到 app——
        # 业务路由需要请求会话，而 app 顶层健康/静态路由（/healthz、/favicon、
        # /docs、/webhook）不应建 DB 会话（DB 挂时健康探测语义不被污染）。
        from fastapi import APIRouter, Depends
        from internal.server.deps import request_context_dependency
        from package.database import get_db

        _llmops = APIRouter(
            dependencies=[Depends(request_context_dependency), Depends(get_db)],
        )
        _openapi = APIRouter(
            dependencies=[Depends(request_context_dependency), Depends(get_db)],
        )
        _register_routes(
            app_handler,
            builtin_tool_handler,
            api_tool_handler,
            upload_file_handler,
            dataset_handler,
            document_handler,
            segment_handler,
            oauth_handler,
            account_handler,
            auth_handler,
            ai_handler,
            language_model_handler,
            assistant_agent_handler,
            api_key_handler,
            open_api_handler,
            builtin_app_handler,
            workflow_handler,
            analysis_handler,
            web_app_handler,
            conversation_handler,
            custom_llm_model_handler,
            audio_handler,
            skill_handler,
            feishu_handler,
            file_proxy_handler,
            chroma_file_handler,
            chroma_vector_handler,
            weaviate_vector_handler,
            system_config_handler,
            target_llmops=_llmops,
            target_openapi=_openapi,
        )
        app.include_router(_llmops)
        app.include_router(_openapi)
    else:
        _register_routes(
            app_handler,
            builtin_tool_handler,
            api_tool_handler,
            upload_file_handler,
            dataset_handler,
            document_handler,
            segment_handler,
            oauth_handler,
            account_handler,
            auth_handler,
            ai_handler,
            language_model_handler,
            assistant_agent_handler,
            api_key_handler,
            open_api_handler,
            builtin_app_handler,
            workflow_handler,
            analysis_handler,
            web_app_handler,
            conversation_handler,
            custom_llm_model_handler,
            audio_handler,
            skill_handler,
            feishu_handler,
            file_proxy_handler,
            chroma_file_handler,
            chroma_vector_handler,
            weaviate_vector_handler,
            system_config_handler,
            target=None,
        )


def _register_routes(
    app_handler,
    builtin_tool_handler,
    api_tool_handler,
    upload_file_handler,
    dataset_handler,
    document_handler,
    segment_handler,
    oauth_handler,
    account_handler,
    auth_handler,
    ai_handler,
    language_model_handler,
    assistant_agent_handler,
    api_key_handler,
    open_api_handler,
    builtin_app_handler,
    workflow_handler,
    analysis_handler,
    web_app_handler,
    conversation_handler,
    custom_llm_model_handler,
    audio_handler,
    skill_handler,
    feishu_handler,
    file_proxy_handler,
    chroma_file_handler,
    chroma_vector_handler,
    weaviate_vector_handler,
    system_config_handler,
    target_llmops=None,
    target_openapi=None,
    target=None,
):
    """注册所有路由到 llmops_router/openapi_router 或直接到 target app。

    参数：
    - target_llmops/target_openapi: 显式指定 llmops/openapi 两个目标 router
      （带 get_db 依赖的新 router，注册后 include 到 app）。
    - target: 兼容旧调用——单个目标（app 或 router），llmops 与 openapi 都注册其上。
    """

    # 当 target (app) 传入时，路由直接注册到 app 而非 router
    _llmops = target_llmops if target_llmops is not None else (target if target is not None else llmops_router)
    _openapi = target_openapi if target_openapi is not None else (target if target is not None else openapi_router)

    # ---- 1. 应用模块 ----
    _llmops.add_api_route("/ping", app_handler.ping, methods=["GET"])
    _llmops.add_api_route("/apps", app_handler.create_app, methods=["POST"])
    _llmops.add_api_route("/apps", app_handler.get_apps_with_page, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/delete", app_handler.delete_app, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}", app_handler.get_app, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}", app_handler.update_app, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/copy", app_handler.copy_app, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/draft_app_config", app_handler.get_draft_app_config, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/draft_app_config", app_handler.update_draft_app_config, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/publish", app_handler.publish_draft_app_config, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/cancel_publish", app_handler.cancel_publish, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/publish_histories", app_handler.get_publish_histories_with_page, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/fallback_history", app_handler.fallback_history_to_draft, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/summary", app_handler.get_debug_conversation_summary, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/summary", app_handler.update_debug_conversation_summary, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/conversations/delete_debug_conversation", app_handler.delete_debug_conversation, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/conversations", app_handler.debug_chat, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/conversations/tasks/{task_id}/stop", app_handler.stop_debug_chat, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/conversations/tasks/{task_id}/choice", app_handler.debug_chat_choice, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/conversations/messages", app_handler.get_debug_conversation_messages_with_page, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/published_config", app_handler.get_published_config, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/published_config/regenerate_web_app_token", app_handler.regenerate_web_app_token, methods=["POST"])
    _llmops.add_api_route("/apps/{app_id}/memory/facts", app_handler.get_user_memory_facts, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/memory/facts/history", app_handler.get_user_memory_facts_history, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/memory/facts/at", app_handler.get_user_memory_facts_at, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/memory/facts/window", app_handler.get_user_memory_facts_in_window, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/memory/episodic", app_handler.get_episodic_memories, methods=["GET"])
    _llmops.add_api_route("/apps/{app_id}/memory/instructions", app_handler.get_procedural_memories, methods=["GET"])
    _llmops.add_api_route("/memory/test", app_handler.test_memory_config, methods=["POST"])

    # ---- 2. 内置插件广场模块 ----
    _llmops.add_api_route("/builtin_tools", builtin_tool_handler.get_builtin_tools, methods=["GET"])
    _llmops.add_api_route("/builtin_tools/{provider_name}/tools/{tool_name}", builtin_tool_handler.get_provider_tool, methods=["GET"])
    _llmops.add_api_route("/builtin_tools/{provider_name}/icon", builtin_tool_handler.get_provider_icon, methods=["GET"])
    _llmops.add_api_route("/builtin_tools/categories", builtin_tool_handler.get_categories, methods=["GET"])
    _llmops.add_api_route("/builtin_apps", builtin_app_handler.get_builtin_apps, methods=["GET"])
    _llmops.add_api_route("/builtin_apps/categories", builtin_app_handler.get_builtin_app_categories, methods=["GET"])
    _llmops.add_api_route("/builtin_apps/add_builtin_app_to_space", builtin_app_handler.add_builtin_app_to_space, methods=["POST"])

    # ---- 3. 自定义API插件模块 ----
    _llmops.add_api_route("/api_tools", api_tool_handler.get_api_tool_providers_with_page, methods=["GET"])
    _llmops.add_api_route("/api_tools/validate_openapi_schema", api_tool_handler.validate_openapi_schema, methods=["POST"])
    _llmops.add_api_route("/api_tools", api_tool_handler.create_api_tool, methods=["POST"])
    _llmops.add_api_route("/api_tools/{provider_id}", api_tool_handler.get_apt_tool_provider, methods=["GET"])
    _llmops.add_api_route("/api_tools/{provider_id}", api_tool_handler.update_api_tool_provider, methods=["POST"])
    _llmops.add_api_route("/api_tools/{provider_id}/tools/{tool_name}", api_tool_handler.get_api_tool, methods=["GET"])
    _llmops.add_api_route("/api_tools/{provider_id}/tools/{tool_name}/debug", api_tool_handler.debug_api_tool, methods=["POST"])
    _llmops.add_api_route("/api_tools/{provider_id}/delete", api_tool_handler.delete_api_tool_provider, methods=["POST"])

    # ---- 4. 上传文件模块 ----
    _llmops.add_api_route("/upload-files/file", upload_file_handler.upload_file, methods=["POST"])
    _llmops.add_api_route("/upload-files/image", upload_file_handler.upload_image, methods=["POST"])
    _llmops.add_api_route("/upload-files/pending", upload_file_handler.pending_upload_files, methods=["GET"])
    _llmops.add_api_route("/upload-files/{upload_file_id}/delete", upload_file_handler.delete_upload_file, methods=["POST"])
    _llmops.add_api_route("/upload-files/{upload_file_id}/url", upload_file_handler.get_file_url, methods=["GET"])
    # 文件代理：把对象存储 http 地址转同源地址，消除浏览器 insecure 提示
    _llmops.add_api_route("/files/proxy", file_proxy_handler.proxy, methods=["GET"])

    # ---- 5. 知识库模块 ----
    _llmops.add_api_route("/datasets", dataset_handler.create_dataset, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}", dataset_handler.get_dataset, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}", dataset_handler.update_dataset, methods=["POST"])
    _llmops.add_api_route("/datasets", dataset_handler.get_datasets_with_page, methods=["GET"])
    _llmops.add_api_route("/datasets/embeddings", dataset_handler.embeddings_query, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/delete", dataset_handler.delete_dataset, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}", document_handler.get_document, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/name", document_handler.update_document_name, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/enabled", document_handler.update_document_enabled, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/delete", document_handler.delete_document, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/retry", document_handler.retry_document, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/pause", document_handler.pause_document, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/resume", document_handler.resume_document, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/preview-chunks", document_handler.preview_chunks, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents", document_handler.get_document_with_page, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents", document_handler.create_document, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/batch/{batch}", document_handler.get_documents_status, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/hit", dataset_handler.hit, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/queries", dataset_handler.get_dataset_queries, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/segments", segment_handler.create_segment, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/segments", segment_handler.get_segments_with_page, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}", segment_handler.get_segment, methods=["GET"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}/delete", segment_handler.delete_segment, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}/enabled", segment_handler.update_segment_enabled, methods=["POST"])
    _llmops.add_api_route("/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}", segment_handler.update_segment, methods=["POST"])

    # ---- 6. 授权认证模块 ----
    _llmops.add_api_route("/oauth/{provider_name}", oauth_handler.provider, methods=["GET"])
    _llmops.add_api_route("/oauth/authorize/{provider_name}", oauth_handler.authorize, methods=["POST"])
    _llmops.add_api_route("/auth/password_login", auth_handler.password_login, methods=["POST"])
    _llmops.add_api_route("/auth/logout", auth_handler.logout, methods=["POST"])

    # ---- 7. 账号设置 ----
    _llmops.add_api_route("/account", account_handler.get_current_user, methods=["GET"])
    _llmops.add_api_route("/account/password", account_handler.update_password, methods=["POST"])
    _llmops.add_api_route("/account/name", account_handler.update_name, methods=["POST"])
    _llmops.add_api_route("/account/avatar", account_handler.update_avatar, methods=["POST"])

    # ---- 8. AI辅助模块 ----
    _llmops.add_api_route("/ai/optimize_prompt", ai_handler.optimize_prompt, methods=["POST"])
    _llmops.add_api_route("/ai/suggested_questions", ai_handler.generate_suggested_questions, methods=["POST"])

    # ---- 9. API秘钥模板 ----
    _llmops.add_api_route("/openapi/api_keys", api_key_handler.get_api_keys_with_page, methods=["GET"])
    _llmops.add_api_route("/openapi/api_keys", api_key_handler.create_api_key, methods=["POST"])
    _llmops.add_api_route("/openapi/api_keys/{api_key_id}", api_key_handler.update_api_key, methods=["POST"])
    _llmops.add_api_route("/openapi/api_keys/{api_key_id}/is_active", api_key_handler.update_api_key_is_active, methods=["POST"])
    _llmops.add_api_route("/openapi/api_keys/{api_key_id}/delete_api_key", api_key_handler.delete_api_key, methods=["POST"])

    # ---- 10. 系统设置 ----
    _llmops.add_api_route("/settings/config", system_config_handler.get_system_config, methods=["GET"])
    _llmops.add_api_route("/settings/config", system_config_handler.save_system_config, methods=["PUT"])

    # ---- 11. 工作流模块 ----
    _llmops.add_api_route("/workflows", workflow_handler.get_workflows_with_page, methods=["GET"])
    _llmops.add_api_route("/workflows", workflow_handler.create_workflow, methods=["POST"])
    _llmops.add_api_route("/workflows/{workflow_id}", workflow_handler.update_workflow, methods=["POST"])
    _llmops.add_api_route("/workflows/{workflow_id}/delete", workflow_handler.delete_workflow, methods=["POST"])
    _llmops.add_api_route("/workflows/{workflow_id}", workflow_handler.get_workflow, methods=["GET"])
    _llmops.add_api_route("/workflows/{workflow_id}/draft_graph", workflow_handler.update_draft_graph, methods=["POST"])
    _llmops.add_api_route("/workflows/{workflow_id}/draft_graph", workflow_handler.get_draft_graph, methods=["GET"])
    _llmops.add_api_route("/workflows/{workflow_id}/debug", workflow_handler.debug_workflow, methods=["POST"])
    _llmops.add_api_route("/workflows/{workflow_id}/publish", workflow_handler.publish_workflow, methods=["POST"])
    _llmops.add_api_route("/workflows/{workflow_id}/cancel_publish", workflow_handler.cancel_publish_workflow, methods=["POST"])

    # ---- 12. 语言模型模块 ----
    _llmops.add_api_route("/language_models", language_model_handler.get_language_models, methods=["GET"])
    # icon 路由必须先注册——`/language_models/{provider_name}/{model_name}` 会先吞掉
    # `/language_models/deepseek/icon`（model_name="icon"），导致图标请求被认证路由拦截返回
    # unauthorized（图片显示失败）。
    _llmops.add_api_route("/language_models/{provider_name}/icon", language_model_handler.get_language_model_icon, methods=["GET"])
    _llmops.add_api_route("/language_models/{provider_name}/{model_name}", language_model_handler.get_language_model, methods=["GET"])

    # ---- 13. 自定义大语言模型模块 ----
    # /protocols 必须先于 /{model_id} 注册，否则 "protocols" 会被当成 model_id 参数吞掉。
    _llmops.add_api_route("/custom_llm_models/protocols", custom_llm_model_handler.get_custom_llm_model_protocol_options, methods=["GET"])
    _llmops.add_api_route("/custom_llm_models", custom_llm_model_handler.list_custom_llm_models, methods=["GET"])
    _llmops.add_api_route("/custom_llm_models", custom_llm_model_handler.create_custom_llm_model, methods=["POST"])
    _llmops.add_api_route("/custom_llm_models/{model_id}", custom_llm_model_handler.get_custom_llm_model, methods=["GET"])
    _llmops.add_api_route("/custom_llm_models/{model_id}", custom_llm_model_handler.update_custom_llm_model, methods=["PUT"])
    _llmops.add_api_route("/custom_llm_models/{model_id}", custom_llm_model_handler.delete_custom_llm_model, methods=["DELETE"])

    # ---- 14. 辅助Agent模块 ----
    _llmops.add_api_route("/assistant_agent/chat", assistant_agent_handler.assistant_agent_chat, methods=["POST"])
    _llmops.add_api_route("/assistant_agent/chat/{task_id}/stop", assistant_agent_handler.stop_assistant_agent_chat, methods=["POST"])
    _llmops.add_api_route("/assistant_agent/chat/{task_id}/choice", assistant_agent_handler.assistant_agent_chat_choice, methods=["POST"])
    _llmops.add_api_route("/assistant_agent/messages", assistant_agent_handler.get_assistant_agent_messages_with_page, methods=["GET"])
    _llmops.add_api_route("/assistant_agent/delete_conversation", assistant_agent_handler.delete_assistant_agent_conversation, methods=["POST"])

    # ---- 15. 应用统计 ----
    _llmops.add_api_route("/analysis/{app_id}", analysis_handler.get_app_analysis, methods=["GET"])

    # ---- 16. WebApp模块 ----
    # default 必须先于 {token} 注册，否则 "default" 会被当成 token 参数吞掉
    _llmops.add_api_route("/web_apps/default", web_app_handler.get_default_web_app, methods=["GET"])
    # 插件兜底：账号无已发布应用时创建+发布一个默认应用，返回可用 token。
    # 固定前缀 plugin 多一段路径，不与 {token} 单段路由冲突。
    _llmops.add_api_route("/web_apps/plugin/bootstrap", web_app_handler.bootstrap, methods=["POST"])
    _llmops.add_api_route("/web_apps/{token}", web_app_handler.get_web_app, methods=["GET"])
    _llmops.add_api_route("/web_apps/{token}/chat", web_app_handler.web_app_chat, methods=["POST"])
    _llmops.add_api_route("/web_apps/{token}/chat/{task_id}/stop", web_app_handler.stop_web_app_chat, methods=["POST"])
    _llmops.add_api_route("/web_apps/{token}/chat/{task_id}/choice", web_app_handler.web_app_chat_choice, methods=["POST"])
    _llmops.add_api_route("/web_apps/{token}/chat/{task_id}/tool-result", web_app_handler.web_app_chat_tool_result, methods=["POST"])
    # 断流重连续传：插件携带 Last-Event-ID 重连，重放已缓冲帧后订阅该 run 实时队列
    _llmops.add_api_route(
        "/web_apps/{token}/chat/{run_id}/resume",
        web_app_handler.web_app_chat_resume,
        methods=["GET"],
    )
    _llmops.add_api_route("/web_apps/{token}/code_action", web_app_handler.code_action, methods=["POST"])
    _llmops.add_api_route("/web_apps/{token}/conversations", web_app_handler.get_conversations, methods=["GET"])
    _llmops.add_api_route("/web_apps/{token}/conversations/{conversation_id}/settings", web_app_handler.update_conversation_settings, methods=["POST"])

    # ---- 17. 会话模块 ----
    _llmops.add_api_route("/conversations/{conversation_id}/messages", conversation_handler.get_conversation_messages_with_page, methods=["GET"])
    _llmops.add_api_route("/conversations/{conversation_id}/delete", conversation_handler.delete_conversation, methods=["POST"])
    _llmops.add_api_route("/conversations/{conversation_id}/messages/{message_id}/delete", conversation_handler.delete_message, methods=["POST"])
    _llmops.add_api_route("/conversations/{conversation_id}/messages/{message_id}/feedback", conversation_handler.update_message_feedback, methods=["POST"])
    _llmops.add_api_route("/conversations/{conversation_id}/name", conversation_handler.get_conversation_name, methods=["GET"])
    _llmops.add_api_route("/conversations/{conversation_id}/name", conversation_handler.update_conversation_name, methods=["POST"])
    _llmops.add_api_route("/conversations/{conversation_id}/is_pinned", conversation_handler.update_conversation_is_pinned, methods=["POST"])

    # ---- 18. 语音转换模块 ----
    _llmops.add_api_route("/audio/audio_to_text", audio_handler.audio_to_text, methods=["POST"])
    _llmops.add_api_route("/audio/message_to_audio", audio_handler.message_to_audio, methods=["POST"])

    # ---- 19. skill模块 ----
    _llmops.add_api_route("/skill/upload", skill_handler.skill_upload, methods=["POST"])
    _llmops.add_api_route("/skill/skills", skill_handler.get_skill_list_with_page, methods=["GET"])
    _llmops.add_api_route("/skill/{skill_id}", skill_handler.get_skill, methods=["GET"])
    _llmops.add_api_route("/skill/skill_detail/{skill_id}", skill_handler.get_skill_detail, methods=["GET"])
    _llmops.add_api_route("/skill/{skill_id}/delete", skill_handler.delete_skill, methods=["POST"])
    _llmops.add_api_route("/skill/{skill_id}/visibility", skill_handler.toggle_skill_visibility, methods=["POST"])
    _llmops.add_api_route("/skill/{skill_id}/download", skill_handler.download_skill, methods=["GET"])

    # ---- 20. chroma模块 ----
    _llmops.add_api_route("/chroma/list", chroma_file_handler.list, methods=["GET"])
    _llmops.add_api_route("/chroma/upload", chroma_file_handler.upload, methods=["POST"])
    _llmops.add_api_route("/chroma/download", chroma_file_handler.download, methods=["GET"])
    _llmops.add_api_route("/chroma/delete", chroma_file_handler.delete, methods=["POST"])

    # ---- 21. chromaDB模块 ----
    _llmops.add_api_route("/chroma/vector", chroma_vector_handler.list_vectors, methods=["GET"])
    _llmops.add_api_route("/chroma/{doc_id}/vector", chroma_vector_handler.get_vector, methods=["GET"])
    _llmops.add_api_route("/chroma/vector/add_vector", chroma_vector_handler.add_vector, methods=["POST"])
    _llmops.add_api_route("/chroma/{doc_id}/update_vector", chroma_vector_handler.update_vector, methods=["POST"])
    _llmops.add_api_route("/chroma/{doc_id}/delete_vector", chroma_vector_handler.delete_vector, methods=["POST"])
    _llmops.add_api_route("/chroma/vector/clear", chroma_vector_handler.clear_vectors, methods=["POST"])
    _llmops.add_api_route("/chroma/vector/recall", chroma_vector_handler.recall_test, methods=["POST"])
    _llmops.add_api_route("/chroma/vector/sync", chroma_vector_handler.sync_documents, methods=["POST"])

    # ---- 22. weaviate 模块 ----
    _llmops.add_api_route("/weaviate/vector/recall", weaviate_vector_handler.recall_test, methods=["POST"])
    _llmops.add_api_route("/weaviate/vector/delete", weaviate_vector_handler.delete_document, methods=["POST"])
    _llmops.add_api_route("/weaviate/vector/memory/delete", weaviate_vector_handler.delete_memory, methods=["POST"])
    _llmops.add_api_route("/weaviate/vector/collections", weaviate_vector_handler.get_all_collections, methods=["GET"])
    _llmops.add_api_route("/weaviate/vector/all", weaviate_vector_handler.get_all, methods=["GET"])
    _llmops.add_api_route("/weaviate/vector/all/dataset", weaviate_vector_handler.get_all_by_dataset, methods=["GET"])
    _llmops.add_api_route("/weaviate/vector/documents", weaviate_vector_handler.get_documents_by_collection, methods=["GET"])
    _llmops.add_api_route("/weaviate/vector/segments", weaviate_vector_handler.get_segments_by_document, methods=["GET"])
    _llmops.add_api_route("/weaviate/vector/metadata", weaviate_vector_handler.get_metadata, methods=["GET"])

    # ---- openapi 路由登记 ----
    # /openapi/chat → openapi_router，认证: get_api_key_account
    _openapi.add_api_route("/openapi/chat", open_api_handler.chat, methods=["POST"])

    # /webhook → 公开路由（无认证），由 app.py 直接挂 app 顶层
