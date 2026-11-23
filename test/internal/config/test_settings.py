from pathlib import Path

from internal.config.settings import Settings, get_settings


def test_defaults(monkeypatch):
    # 根 conftest 导入 app.http.app 时 dotenv.load_dotenv() 会把 .env 写入 os.environ，
    # 仅 _env_file=None 无法隔离；此处清理被断言的字段对应环境变量，确保断言的是默认值。
    monkeypatch.delenv("SQLALCHEMY_POOL_SIZE", raising=False)
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("ASSISTANT_AGENT_ID", raising=False)
    s = Settings(_env_file=None)
    assert s.sqlalchemy_pool_size == 30
    assert s.redis_host == "localhost"
    assert s.assistant_agent_id == "dd2d4f79-4a46-4393-947e-afd078fb85a7"


def test_env_override(monkeypatch):
    monkeypatch.setenv("REDIS_PORT", "9999")
    s = Settings(_env_file=None)
    assert s.redis_port == 9999


def test_weaviate_http_host_falls_back_to_legacy_env(monkeypatch):
    # 旧 Flask/flask_weaviate 遗留命名 WEAVIATE_HOST 应映射到 weaviate_http_host（新命名缺失时）
    monkeypatch.delenv("WEAVIATE_HTTP_HOST", raising=False)
    monkeypatch.setenv("WEAVIATE_HOST", "1.2.3.4")
    s = Settings(_env_file=None)
    assert s.weaviate_http_host == "1.2.3.4"


def test_weaviate_http_host_prefers_new_env(monkeypatch):
    # 新旧命名并存时 WEAVIATE_HTTP_HOST 优先（docker-compose 命名）
    monkeypatch.setenv("WEAVIATE_HTTP_HOST", "5.6.7.8")
    monkeypatch.setenv("WEAVIATE_HOST", "1.2.3.4")
    s = Settings(_env_file=None)
    assert s.weaviate_http_host == "5.6.7.8"


def test_singleton():
    assert get_settings() is get_settings()


# --- project_root / rerank_device ---


def test_project_root_default(monkeypatch):
    """project_root 默认 = 仓库根（internal/config/settings.py 的 parents[2]）。"""
    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    import internal.config.settings as settings_module

    s = Settings(_env_file=None)
    assert s.project_root == Path(settings_module.__file__).resolve().parents[2]
    assert s.project_root == Path("internal/config/settings.py").resolve().parents[2]


def test_project_root_env_override(monkeypatch):
    """pyinstaller/打包场景：显式 PROJECT_ROOT 环境变量覆盖默认推导路径。"""
    monkeypatch.setenv("PROJECT_ROOT", "C:/pyinstaller-root")
    s = Settings(_env_file=None)
    assert s.project_root == Path("C:/pyinstaller-root")


def test_rerank_device_default(monkeypatch):
    monkeypatch.delenv("RERANK_DEVICE", raising=False)
    s = Settings(_env_file=None)
    assert s.rerank_device == "cpu"


def test_rerank_device_env_override(monkeypatch):
    monkeypatch.setenv("RERANK_DEVICE", "cuda")
    s = Settings(_env_file=None)
    assert s.rerank_device == "cuda"


def test_embedding_and_rerank_device_side_by_side(monkeypatch):
    """embedding_device 与 rerank_device 并列存在，默认均为 cpu。"""
    monkeypatch.delenv("EMBEDDING_DEVICE", raising=False)
    monkeypatch.delenv("RERANK_DEVICE", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_device == "cpu"
    assert s.rerank_device == "cpu"
