# internal/extensions/redis.py
import redis.asyncio as aioredis
import redis as sync_redis
from redis.maint_notifications import MaintNotificationsConfig

from internal.config.settings import get_settings

redis_client: aioredis.Redis | None = None
sync_redis_client: sync_redis.Redis | None = None


def init_redis() -> aioredis.Redis:
    global redis_client, sync_redis_client
    if redis_client is not None:
        return redis_client
    s = get_settings()
    common = dict(
        host=s.redis_host, port=s.redis_port, username=s.redis_username or None,
        password=s.redis_password or None, db=s.redis_db,
        socket_timeout=s.redis_socket_timeout, socket_connect_timeout=s.redis_connect_timeout,
        ssl=s.redis_use_ssl, decode_responses=False,
        # 禁用维护通知：避免对不支持 CLIENT MAINT_NOTIFICATIONS 的旧版 Redis 报
        # "unknown subcommand 'MAINT_NOTIFICATIONS'" 告警（redis-py 8.x 默认 auto 探测）。
        maint_notifications_config=MaintNotificationsConfig(enabled=False),
    )
    redis_client = aioredis.Redis(**common)
    sync_redis_client = sync_redis.Redis(**common)
    return redis_client
