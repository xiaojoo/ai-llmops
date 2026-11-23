# internal/extensions/logging.py
import atexit
import logging
import os
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

_initialized = False


def init_logging() -> None:
    global _initialized
    if _initialized:
        return
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if os.getenv("FLASK_ENV") == "development" else logging.WARNING)
    log_folder = os.path.join(os.getcwd(), "storage", "logs")
    os.makedirs(log_folder, exist_ok=True)
    handler = ConcurrentTimedRotatingFileHandler(
        os.path.join(log_folder, "app.log"), when="midnight", interval=1,
        backupCount=30, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(filename)s -> %(funcName)s line:%(lineno)d [%(levelname)s]: %(message)s",
    ))
    root.addHandler(handler)
    atexit.register(handler.close)
    if os.getenv("FLASK_ENV") == "development":
        console = logging.StreamHandler()
        console.setFormatter(handler.formatter)
        root.addHandler(console)
    _initialized = True
