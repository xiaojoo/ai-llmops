# test/internal/extensions/test_extensions.py
import logging

import internal.extensions.logging as logging_ext
import internal.extensions.redis as redis_ext


def test_logging_idempotent():
    """首次调用挂载 handler + 重复调用不重复挂载（幂等）。

    全量回归中 live_server 测试（lifespan 调 init_logging）可能已把模块级
    _initialized 置 True、root 已挂 handler——若直接断言 before/after 会顺序耦合
    （单独跑通过、全量跑失败）。此处保存并清空 root handlers + 重置初始化标志，
    独立验证契约本身，finally 恢复现场。
    """
    root = logging.getLogger()
    original_initialized = logging_ext._initialized
    original_handlers = list(root.handlers)
    try:
        root.handlers = []
        logging_ext._initialized = False
        logging_ext.init_logging()
        first = len(root.handlers)
        # 注：conftest 导入旧 Flask app 后 os.environ 被 .env 置为 FLASK_ENV=development，
        # init_logging 会挂载文件+console 两个 handler，故不断言精确数量，只断言首次有挂载。
        assert first > 0
        logging_ext.init_logging()  # 幂等：不重复挂载
        assert len(root.handlers) == first
    finally:
        root.handlers = original_handlers
        logging_ext._initialized = original_initialized


def test_redis_client_is_async_redis():
    client = redis_ext.init_redis()
    import redis.asyncio
    assert isinstance(client, redis.asyncio.Redis)
    from internal.config.settings import get_settings
    # 注：.env 覆盖 REDIS_HOST，host 断言改为与配置一致而非硬编码 localhost。
    assert client.connection_pool.connection_kwargs["host"] == get_settings().redis_host


def test_init_weaviate_passes_secure_flags(monkeypatch):
    from unittest.mock import MagicMock

    import internal.extensions.weaviate as weaviate_ext
    from internal.config.settings import get_settings

    connect_mock = MagicMock()
    monkeypatch.setattr(weaviate_ext.weaviate, "connect_to_custom", connect_mock)
    weaviate_ext.weaviate_client = None  # 重置模块级客户端，确保真正走 init 分支
    try:
        weaviate_ext.init_weaviate()
    finally:
        weaviate_ext.weaviate_client = None  # 避免污染其他测试

    s = get_settings()
    connect_mock.assert_called_once()
    kwargs = connect_mock.call_args.kwargs
    assert kwargs["http_host"] == s.weaviate_http_host
    assert kwargs["http_port"] == s.weaviate_http_port
    assert kwargs["grpc_host"] == s.weaviate_grpc_host
    assert kwargs["grpc_port"] == s.weaviate_grpc_port
    assert kwargs["http_secure"] is False
    assert kwargs["grpc_secure"] is False
    if s.weaviate_api_key:
        assert kwargs["auth_credentials"] is not None
    else:
        assert kwargs["auth_credentials"] is None


def test_init_weaviate_no_api_key_passes_none_auth(monkeypatch):
    from unittest.mock import MagicMock

    import internal.extensions.weaviate as weaviate_ext
    from internal.config.settings import get_settings

    # Settings.env_ignore_empty=True：空环境变量不覆盖 .env 值（.env 配了 WEAVIATE_API_KEY 时
    # setenv("") 无效），直接清空 settings 实例字段强制走无 key 分支
    monkeypatch.setenv("WEAVIATE_API_KEY", "")
    get_settings.cache_clear()  # 清除单例缓存，确保 init_weaviate 内部读到同一实例
    get_settings().weaviate_api_key = ""
    connect_mock = MagicMock()
    monkeypatch.setattr(weaviate_ext.weaviate, "connect_to_custom", connect_mock)
    weaviate_ext.weaviate_client = None  # 重置模块级客户端，确保真正走 init 分支
    try:
        weaviate_ext.init_weaviate()
    finally:
        weaviate_ext.weaviate_client = None  # 避免污染其他测试

    kwargs = connect_mock.call_args.kwargs
    assert kwargs["auth_credentials"] is None


def test_init_weaviate_returns_module_singleton(monkeypatch):
    """init_weaviate() 返回模块级单例；重复调用不重复建连（connect_to_custom 只调用一次）"""
    from unittest.mock import MagicMock

    import internal.extensions.weaviate as weaviate_ext

    connect_mock = MagicMock()
    monkeypatch.setattr(weaviate_ext.weaviate, "connect_to_custom", connect_mock)
    weaviate_ext.weaviate_client = None  # 重置模块级客户端，确保真正走 init 分支
    try:
        client1 = weaviate_ext.init_weaviate()
        assert weaviate_ext.weaviate_client is not None, "init 后模块级 weaviate_client 不应为 None"
        assert weaviate_ext.weaviate_client is client1, "模块级 weaviate_client 应等于 init_weaviate() 返回值"
        client2 = weaviate_ext.init_weaviate()
        assert client2 is client1, "重复 init 应返回同一单例实例"
    finally:
        weaviate_ext.weaviate_client = None  # 避免污染其他测试

    connect_mock.assert_called_once()  # 单例：只建连一次
