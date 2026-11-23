# internal/extensions/weaviate.py
"""Weaviate 客户端模块级单例。"""
import weaviate

from internal.config.settings import get_settings

weaviate_client: weaviate.WeaviateClient | None = None


def init_weaviate() -> weaviate.WeaviateClient:
    global weaviate_client
    if weaviate_client is not None:
        return weaviate_client
    s = get_settings()
    auth = weaviate.auth.AuthApiKey(s.weaviate_api_key) if s.weaviate_api_key else None
    weaviate_client = weaviate.connect_to_custom(
        http_host=s.weaviate_http_host, http_port=s.weaviate_http_port,
        http_secure=False, grpc_secure=False,
        grpc_host=s.weaviate_grpc_host, grpc_port=s.weaviate_grpc_port,
        auth_credentials=auth, skip_init_checks=True,
    )
    return weaviate_client


def get_weaviate_client() -> weaviate.WeaviateClient:
    """集中获取 Weaviate 客户端：模块单例（惰性 init）。"""
    return weaviate_client if weaviate_client is not None else init_weaviate()
