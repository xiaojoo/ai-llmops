from __future__ import annotations

import logging
import threading
from contextlib import AbstractContextManager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from internal.config.settings import get_settings

logger = logging.getLogger(__name__)

_store: "CheckpointStore | None" = None
_lock = threading.Lock()


class CheckpointStore:
    def __init__(self, saver, manager: AbstractContextManager):
        self.saver = saver
        self._manager = manager

    def delete_thread(self, thread_id: str) -> None:
        self.saver.delete_thread(thread_id)

    def close(self) -> None:
        self._manager.__exit__(None, None, None)


def _conn_string() -> str:
    raw = get_settings().sqlalchemy_database_uri
    parts = urlsplit(raw)
    query = urlencode(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit(parts._replace(scheme="postgresql", query=query))


def init_checkpoint_store() -> "CheckpointStore | None":
    global _store
    if _store is not None:
        return _store
    with _lock:
        if _store is not None:
            return _store
        raw = get_settings().sqlalchemy_database_uri
        if not raw.startswith("postgresql"):
            return None
        from langgraph.checkpoint.postgres import PostgresSaver

        manager = PostgresSaver.from_conn_string(_conn_string(), pipeline=False)
        saver = manager.__enter__()
        try:
            with saver.conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(20261124, 1)")
                try:
                    saver.setup()
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(20261124, 1)")
        except Exception:
            manager.__exit__(None, None, None)
            raise
        _store = CheckpointStore(saver, manager)
        logger.info("LangGraph Postgres checkpointer 已就绪")
        return _store


def get_checkpoint_store() -> "CheckpointStore | None":
    return _store


def close_checkpoint_store() -> None:
    global _store
    with _lock:
        if _store is not None:
            _store.close()
            _store = None
