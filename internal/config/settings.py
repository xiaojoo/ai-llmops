from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置单例（读取 .env，字段名与旧 config/default_config.py 对齐）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 空环境变量不覆盖默认值：.env 中"留空表示用默认"（如 COS_BASE_URL=、BROWSER_LLM_BASE_URL=）
        env_ignore_empty=True,
    )

    # 项目根目录：internal/config/settings.py 的 parents[2]。
    # 注意：pyinstaller/打包环境下 __file__ 位于临时解包目录，此推导失效——
    # 打包部署需显式设置 PROJECT_ROOT 环境变量覆盖。
    project_root: Path = Path(__file__).resolve().parents[2]

    # SQLAlchemy
    sqlalchemy_database_uri: str = ""
    sqlalchemy_pool_size: int = 30
    sqlalchemy_pool_recycle: int = 3600
    sqlalchemy_echo: bool = False

    # Weaviate
    # http host/port 兼容双命名：docker-compose 用 WEAVIATE_HTTP_HOST/PORT，
    # 本地 .env / flask_weaviate 遗留用 WEAVIATE_HOST/PORT（前者优先）
    weaviate_http_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("WEAVIATE_HTTP_HOST", "WEAVIATE_HOST"),
    )
    weaviate_http_port: int = Field(
        default=8080,
        validation_alias=AliasChoices("WEAVIATE_HTTP_PORT", "WEAVIATE_PORT"),
    )
    weaviate_grpc_host: str = "localhost"
    weaviate_grpc_port: int = 50051
    weaviate_api_key: str = ""

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_username: str = ""
    redis_password: str = ""
    redis_db: int = 0
    redis_use_ssl: bool = False
    redis_socket_timeout: float = 5.0
    redis_connect_timeout: float = 5.0

    # Celery
    celery_broker_db: int = 1
    celery_result_backend_db: int = 1
    celery_task_ignore_result: bool = False
    celery_result_expires: int = 3600
    celery_broker_connection_retry_on_startup: bool = True

    # 业务
    assistant_agent_id: str = "dd2d4f79-4a46-4393-947e-afd078fb85a7"
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh"
    embedding_device: str = "cpu"
    embedding_api_key: str = ""
    embedding_api_base: str = ""
    rerank_provider: str = "local"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = "cpu"  # 推理设备（cpu | cuda | mps），与 embedding_device 并列
    rerank_api_key: str = ""
    rerank_api_base: str = ""
    query_rewrite_model: str = "deepseek-v4-flash"
    storage_provider: str = "cos"
    minio_api_url: str = "http://localhost:9001"
    minio_timeout: int = 60
    mode: str = ""  # api | celery | local（对齐旧 MODE 环境变量）

    # 语音服务（ASR 音频转写 / TTS 文字转语音）
    cos_base_url: str = "https://llmops-1253662435.cos.ap-guangzhou.myqcloud.com/"
    dashscope_base_http_api_url: str = "https://dashscope.aliyuncs.com/api/v1"

    # 第三方集成 / 内置工具端点（默认值可被 .env 覆盖）
    browser_llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    gaode_api_domain: str = "https://restapi.amap.com/v3"
    feishu_open_api_base: str = "https://open.feishu.cn/open-apis"
    github_oauth_base_url: str = "https://github.com"
    github_api_base_url: str = "https://api.github.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
