"""Structured JSON logging + per-request context propagation.

Usage
-----
Call ``setup_logging()`` once at startup. After that every ``logger.info(...)``
call emits a JSON line that includes ``request_id`` (if set in the current
async context), ``logger``, ``level``, ``ts``, and any extra fields passed as
keyword arguments.

The request_id is set by the ASGI request middleware in main.py and stored in
a ContextVar so it flows through all awaited coroutines without being threaded
through function signatures.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Holds the current request's ID; empty string when outside a request context.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get("")
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra fields passed to logger.info(..., extra={...})
        for key, val in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                payload[key] = val
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "httpx", "httpcore", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
