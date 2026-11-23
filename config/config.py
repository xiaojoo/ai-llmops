#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/16 0:58
@Author : sunxiaojie
@File   : config.py
"""
import os

from config.default_config import DEFAULT_CONFIG


def _get_env(key: str):
    """从环境变量中获取配置项，如果找不到则返回默认值"""
    return os.getenv(key, DEFAULT_CONFIG.get(key))


def _get_bool_env(key: str) -> bool:
    """从环境变量中获取布尔值型配置项，如果找不到则返回默认值"""
    value: str = _get_env(key)
    return value.lower() == "true" if value is not None else False


class Config:
    def __init__(self):
        # 关闭WTF的CSRF保护
        self.WTF_CSRF_ENABLED = _get_bool_env("WTF_CSRF_ENABLED")

        # 配置数据库
        self.SQLALCHEMY_DATABASE_URI = _get_env("SQLALCHEMY_DATABASE_URI")
        self.SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": int(_get_env("SQLALCHEMY_POOL_SIZE")),
            "pool_recycle": int(_get_env("SQLALCHEMY_POOL_RECYCLE")),
        }
        self.SQLALCHEMY_ECHO = _get_bool_env("SQLALCHEMY_ECHO")

        # Weaviate向量数据库配置
        self.WEAVIATE_HTTP_HOST = _get_env("WEAVIATE_HTTP_HOST")
        self.WEAVIATE_HTTP_PORT = _get_env("WEAVIATE_HTTP_PORT")
        self.WEAVIATE_GRPC_HOST = _get_env("WEAVIATE_GRPC_HOST")
        self.WEAVIATE_GRPC_PORT = _get_env("WEAVIATE_GRPC_PORT")
        self.WEAVIATE_API_KEY = _get_env("WEAVIATE_API_KEY")

        # 配置Redis配置
        self.REDIS_HOST = _get_env("REDIS_HOST")
        self.REDIS_PORT = _get_env("REDIS_PORT")
        self.REDIS_USERNAME = _get_env("REDIS_USERNAME")
        self.REDIS_PASSWORD = _get_env("REDIS_PASSWORD")
        self.REDIS_DB = _get_env("REDIS_DB")
        self.REDIS_USE_SSL = _get_env("REDIS_USE_SSL")

        # Celery配置
        self.CELERY = {
            "broker_url": f"redis://:{_get_env('REDIS_PASSWORD')}@{self.REDIS_HOST}:{self.REDIS_PORT}/{int(_get_env('CELERY_BROKER_DB'))}",
            "result_backend": f"redis://:{_get_env('REDIS_PASSWORD')}@{self.REDIS_HOST}:{self.REDIS_PORT}/{int(_get_env('CELERY_RESULT_BACKEND_DB'))}",
            "task_ignore_result": _get_bool_env("CELERY_TASK_IGNORE_RESULT"),
            "result_expires": _get_env("CELERY_RESULT_EXPIRES"),
            "broker_connection_retry_on_startup": _get_bool_env("CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP"),
        }

        # 辅助Agent应用id标识
        self.ASSISTANT_AGENT_ID = _get_env("ASSISTANT_AGENT_ID")

        # Embedding 嵌入服务配置（local | api）
        self.EMBEDDING_PROVIDER = _get_env("EMBEDDING_PROVIDER")
        self.EMBEDDING_MODEL = _get_env("EMBEDDING_MODEL")
        self.EMBEDDING_DEVICE = _get_env("EMBEDDING_DEVICE")
        self.EMBEDDING_API_KEY = _get_env("EMBEDDING_API_KEY")
        self.EMBEDDING_API_BASE = _get_env("EMBEDDING_API_BASE")

        # Rerank 精排服务配置（local | api）
        self.RERANK_PROVIDER = _get_env("RERANK_PROVIDER")
        self.RERANK_MODEL = _get_env("RERANK_MODEL")
        self.RERANK_API_KEY = _get_env("RERANK_API_KEY")
        self.RERANK_API_BASE = _get_env("RERANK_API_BASE")

        # 查询改写模型配置
        self.QUERY_REWRITE_MODEL = _get_env("QUERY_REWRITE_MODEL")
