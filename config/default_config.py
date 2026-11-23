#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/16 18:31
@Author : sunxiaojie
@File   : default_config.py
"""

# 应用默认配置项
DEFAULT_CONFIG = {
    # wft配置
    "WTF_CSRF_ENABLED": "False",

    # SQLAlchemy数据库配置
    "SQLALCHEMY_DATABASE_URI": "",
    "SQLALCHEMY_POOL_SIZE": 30,
    "SQLALCHEMY_POOL_RECYCLE": 3600,
    "SQLALCHEMY_ECHO": "True",

    # Weaviate向量数据库配置
    "WEAVIATE_HTTP_HOST": "localhost",
    "WEAVIATE_HTTP_PORT": 8080,
    "WEAVIATE_GRPC_HOST": "localhost",
    "WEAVIATE_GRPC_PORT": 50051,
    "WEAVIATE_API_KEY": "",

    # Redis数据库配置
    "REDIS_HOST": "localhost",
    "REDIS_PORT": 6379,
    "REDIS_USERNAME": "",
    "REDIS_PASSWORD": "",
    "REDIS_DB": 0,
    "REDIS_USE_SSL": "False",
    "REDIS_SOCKET_TIMEOUT": 5,

    # Celery配置
    "CELERY_BROKER_DB": 1,
    "CELERY_RESULT_BACKEND_DB": 1,
    "CELERY_TASK_IGNORE_RESULT": "False",
    "CELERY_RESULT_EXPIRES": 3600,
    "CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP": "True",

    # 辅助Agent应用id标识
    "ASSISTANT_AGENT_ID": "dd2d4f79-4a46-4393-947e-afd078fb85a7",

    # Embedding 嵌入服务配置（local | api）
    # 默认使用 bge-small-zh（512维），与存量向量数据兼容；
    # 若要升级模型（如 bge-m3 1024维），需重建知识库索引。
    "EMBEDDING_PROVIDER": "local",
    "EMBEDDING_MODEL": "BAAI/bge-small-zh",
    "EMBEDDING_DEVICE": "cpu",
    "EMBEDDING_API_KEY": "",
    "EMBEDDING_API_BASE": "",

    # Rerank 精排服务配置（local | api）
    "RERANK_PROVIDER": "local",
    "RERANK_MODEL": "BAAI/bge-reranker-v2-m3",
    "RERANK_API_KEY": "",
    "RERANK_API_BASE": "",

    # 查询改写模型配置
    "QUERY_REWRITE_MODEL": "deepseek-v4-flash",

    # 文件存储提供者（cos | miniio，miniio 时调用 mall-third-party 接口）
    "STORAGE_PROVIDER": "cos",
    "MINIO_API_URL": "http://localhost:9001",
    "MINIO_TIMEOUT": 60,
}
