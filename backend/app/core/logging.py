from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_context(request_id: str | None = None, user_id: str | None = None) -> str:
    rid = request_id or new_request_id()
    _request_id.set(rid)
    if user_id is not None:
        _user_id.set(user_id)
    return rid


def get_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if rid := _request_id.get():
            payload["request_id"] = rid
        if uid := _user_id.get():
            payload["user_id"] = uid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.APP_ENV in ("local", "test"):
        handler.setFormatter(
            logging.Formatter("%(levelname)-7s %(name)-28s %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
