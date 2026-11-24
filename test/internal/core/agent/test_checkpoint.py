from types import SimpleNamespace
from unittest.mock import MagicMock

import internal.core.agent.checkpoint as checkpoint


def test_init_checkpoint_store_serializes_setup(monkeypatch):
    monkeypatch.setattr(checkpoint, "_store", None)
    monkeypatch.setattr(
        checkpoint,
        "get_settings",
        lambda: SimpleNamespace(sqlalchemy_database_uri="postgresql://user:pass@localhost/db"),
    )
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    saver = MagicMock()
    saver.conn.cursor.return_value = cursor
    manager = MagicMock()
    manager.__enter__.return_value = saver
    factory = MagicMock(return_value=manager)
    monkeypatch.setattr("langgraph.checkpoint.postgres.PostgresSaver.from_conn_string", factory)

    store = checkpoint.init_checkpoint_store()
    assert store.saver is saver
    saver.setup.assert_called_once()
    cursor.execute.assert_any_call("SELECT pg_advisory_lock(20261124, 1)")
    cursor.execute.assert_any_call("SELECT pg_advisory_unlock(20261124, 1)")
    assert checkpoint.init_checkpoint_store() is store

    checkpoint.close_checkpoint_store()
    manager.__exit__.assert_called_once_with(None, None, None)
    assert checkpoint.get_checkpoint_store() is None


def test_init_checkpoint_store_skips_non_postgres(monkeypatch):
    monkeypatch.setattr(checkpoint, "_store", None)
    monkeypatch.setattr(
        checkpoint,
        "get_settings",
        lambda: SimpleNamespace(sqlalchemy_database_uri="sqlite+aiosqlite:///:memory:"),
    )
    assert checkpoint.init_checkpoint_store() is None
