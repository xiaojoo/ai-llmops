# test/internal/task/test_celery_app.py
from internal.task.celery_app import celery_app


def test_celery_config():
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.main == "llmops"
