from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from contextvars import ContextVar, Token
from typing import Any

import structlog

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "alpaca_api_key",
        "alpaca_secret_key",
        "openai_api_key",
        "api_key",
        "secret_key",
        "authorization",
        "apca-api-key-id",
        "apca-api-secret-key",
        "x-api-key",
        "password",
        "token",
    }
)


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {item_key: _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_secrets(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    redacted = _redact(event_dict)
    if not isinstance(redacted, MutableMapping):
        raise TypeError("Structured log event must remain a mutable mapping")
    return redacted


def add_request_context(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    request_id = request_id_context.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level, force=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        add_request_context,
        redact_secrets,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_request_id(request_id: str) -> Token[str | None]:
    return request_id_context.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    request_id_context.reset(token)
