"""Structured logging for the Mesaar platform built on loguru.

Responsibilities
----------------
* Configure a single loguru sink (JSON in production, pretty in development)
  driven by application :class:`~app.core.config.Settings`.
* Intercept the standard library :mod:`logging` module and re-route every
  record (including uvicorn / gunicorn / sqlalchemy loggers) through loguru so
  that the whole process emits one consistent log stream.
* Maintain a request-id :class:`~contextvars.ContextVar` so that every log line
  emitted while handling a request is automatically annotated with the active
  request id, even across ``await`` boundaries.

Import discipline
-----------------
This module must depend ONLY on the standard library, loguru, and
:mod:`app.core.config`. It must NOT import ``app.observability.metrics`` or
``app.observability.health`` (those modules import *this* one, and the reverse
dependency would create an import cycle).
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from loguru import logger as _loguru_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids runtime import cost.
    from loguru import Logger

    from app.core.config import Settings


# ---------------------------------------------------------------------------
# Request-id context propagation.
# ---------------------------------------------------------------------------
# A ContextVar is used (rather than thread-locals) because the application runs
# on an asyncio event loop where a single OS thread serves many concurrent
# requests. ContextVars are copied per-task, giving each in-flight request its
# own isolated request id.
_request_id_ctx: ContextVar[str | None] = ContextVar("mesaar_request_id", default=None)

# Module-level guard so that ``configure_logging`` is idempotent: repeated calls
# (e.g. app factory invoked in tests) must not stack duplicate sinks.
_LOGGING_CONFIGURED: bool = False


def bind_request_id(request_id: str) -> object:
    """Bind ``request_id`` to the current execution context.

    Returns the :class:`~contextvars.Token` produced by the ContextVar so that
    the caller can later restore the previous value via :func:`reset_request_id`.
    Middleware typically binds at request start and resets in a ``finally`` block.
    """

    return _request_id_ctx.set(request_id)


def reset_request_id(token: object) -> None:
    """Restore the request-id ContextVar to its previous state.

    ``token`` must be the value returned by :func:`bind_request_id`. Any error
    while resetting is swallowed and logged, because failing to reset logging
    context must never break request handling.
    """

    try:
        _request_id_ctx.reset(token)  # type: ignore[arg-type]
    except (ValueError, LookupError) as exc:  # Token from a different context.
        # Do not raise: logging hygiene must not crash the request lifecycle.
        _loguru_logger.bind(name="mesaar").debug(
            "Failed to reset request id context: {error}", error=str(exc)
        )


def get_request_id() -> str | None:
    """Return the request id bound to the current context, if any."""

    return _request_id_ctx.get()


def _request_id_patcher(record: dict[str, Any]) -> None:
    """loguru patcher injecting the active request id into every record.

    loguru calls this for each emitted record. We populate ``record["extra"]``
    with a stable ``request_id`` key so both the JSON serializer and the pretty
    formatter can render it without each call-site needing to pass it.
    """

    extra = record["extra"]
    # Only set a default; an explicit ``logger.bind(request_id=...)`` wins.
    extra.setdefault("request_id", get_request_id())
    extra.setdefault("name", extra.get("name", "mesaar"))


class InterceptHandler(logging.Handler):
    """Standard-library logging handler that forwards records to loguru.

    Installed as the root handler so that third-party libraries which use the
    stdlib :mod:`logging` API (uvicorn, sqlalchemy, asyncio, ...) emit through
    the same loguru pipeline, preserving level, exception info, and the
    originating call-site depth.
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - see class doc.
        # Map the stdlib numeric/named level to a loguru level name; fall back
        # to the raw numeric level if loguru does not know the name.
        try:
            level: str | int = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk back up the stack to the frame that originated the log call so
        # that loguru reports the correct module/line, skipping logging
        # internals and this handler.
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


# Pretty (human-readable) format used for local development.
_PRETTY_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
    "<level>{level: <8}</level> "
    "<cyan>{extra[name]}</cyan> "
    "[<yellow>{extra[request_id]}</yellow>] "
    "<level>{message}</level>"
)


def _intercepted_logger_names() -> list[str]:
    """Return the stdlib logger names we explicitly re-route through loguru."""

    return [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
        "gunicorn",
        "gunicorn.error",
        "gunicorn.access",
        "fastapi",
        "asyncio",
        "sqlalchemy",
        "sqlalchemy.engine",
        "celery",
    ]


def configure_logging(settings: "Settings") -> None:
    """Configure process-wide logging from ``settings``. Idempotent.

    * Removes loguru's default sink and installs a single sink writing to
      ``stdout`` -- JSON when ``settings.log_json`` is true, otherwise the
      colorized :data:`_PRETTY_FORMAT`.
    * Routes the stdlib root logger (and known third-party loggers) through
      :class:`InterceptHandler`.
    * Patches every record with the active request id.

    Calling this more than once is safe: subsequent calls are no-ops, which
    matters because the FastAPI app factory may run repeatedly in tests.
    """

    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        # Idempotency guard: never stack duplicate sinks / handlers.
        return

    log_level = (settings.log_level or "INFO").upper()

    # Patch records so request_id/name are always present in ``record.extra``.
    _loguru_logger.configure(patcher=_request_id_patcher)

    # Replace the default loguru handler with our configured sink.
    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stdout,
        level=log_level,
        # ``serialize=True`` makes loguru emit one JSON object per line, which is
        # what log shippers (Loki/ELK/CloudWatch) expect in production.
        serialize=bool(settings.log_json),
        format=_PRETTY_FORMAT,
        backtrace=not settings.is_production,
        diagnose=not settings.is_production,
        enqueue=True,  # Thread/async-safe; offloads I/O to a background thread.
    )

    # Route the stdlib root logger through loguru. ``force=True`` clears any
    # handlers previously installed (e.g. by uvicorn) so we own the pipeline.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Explicitly re-point well-known third-party loggers at the intercept
    # handler and disable propagation duplication.
    intercept_handler = InterceptHandler()
    for logger_name in _intercepted_logger_names():
        std_logger = logging.getLogger(logger_name)
        std_logger.handlers = [intercept_handler]
        std_logger.propagate = False

    _LOGGING_CONFIGURED = True

    get_logger(__name__).info(
        "Logging configured (level={level}, json={json}, production={prod})",
        level=log_level,
        json=bool(settings.log_json),
        prod=settings.is_production,
    )


def get_logger(name: str = "mesaar") -> "Logger":
    """Return a loguru logger bound with ``name``.

    The returned logger carries ``extra={"name": name}`` so the configured
    formatter / JSON serializer can render the originating module. Modules
    should call ``get_logger(__name__)`` once at import time and reuse it.
    """

    return _loguru_logger.bind(name=name)


__all__ = [
    "configure_logging",
    "get_logger",
    "bind_request_id",
    "reset_request_id",
    "get_request_id",
    "InterceptHandler",
]
