"""Structured logging.

JSON in deployed environments (parseable by a log backend), human-readable
locally. A request-scoped correlation id is bound via contextvars so every line
emitted while handling a request carries it without being threaded through
every call.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
workspace_id_var: ContextVar[str | None] = ContextVar("workspace_id", default=None)

_CONTEXT_VARS = {
    "request_id": request_id_var,
    "user_id": user_id_var,
    "workspace_id": workspace_id_var,
}


def _bind_request_context(_logger, _name, event_dict):  # type: ignore[no-untyped-def]
    for key, var in _CONTEXT_VARS.items():
        value = var.get()
        if value is not None:
            event_dict[key] = value
    return event_dict


# Paths whose next segment is a secret rather than an identifier. An
# invitation token has to travel in a URL for the link to be openable, so the
# only place it can be kept out of is the log — which is precisely where URLs
# otherwise end up, along with proxy history and error trackers.
_SECRET_PATH_SEGMENTS = (re.compile(r"^(?P<prefix>/api/v\d+/invitations/)(?P<secret>[^/]+)"),)

REDACTED = "[redacted]"


def _is_identifier(value: str) -> bool:
    """Ids are safe to log; anything else in that position is a token."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def redact_path(path: str) -> str:
    """Mask credential-bearing URL segments before they are recorded.

    Applied to every logged path and to the `instance` field of error
    responses, so a token cannot reach a log file, an error tracker, or a
    support ticket pasted from either.
    """
    for pattern in _SECRET_PATH_SEGMENTS:
        match = pattern.match(path)
        if match and not _is_identifier(match.group("secret")):
            return path[: match.start("secret")] + REDACTED + path[match.end("secret") :]
    return path


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # uvicorn duplicates access logs that our middleware already emits.
    logging.getLogger("uvicorn.access").disabled = True

    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _bind_request_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "avocado") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
