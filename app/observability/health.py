"""Health and readiness probes for the Mesaar API.

Provides lightweight, side-effect-free checks suitable for Kubernetes-style
liveness/readiness endpoints and for the unversioned ``/health`` router:

* :func:`check_database` -- runs ``SELECT 1`` through the existing
  :data:`app.db.session.SessionLocal` factory and reports latency.
* :func:`check_redis` -- pings Redis via :func:`app.core.redis.redis_ping`.
* :func:`readiness` -- aggregates the individual checks into a single document
  whose top-level ``status`` is ``"ok"`` only when *every* dependency is healthy.

Design contract: NONE of these functions ever raise. A failed dependency is
reported as ``{"status": "error", ...}`` so that the calling endpoint can decide
the HTTP status (e.g. 503) without having to wrap calls in try/except.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from app.observability.logging import get_logger

logger = get_logger(__name__)

# Status constants kept as module-level names to avoid stringly-typed typos.
_STATUS_OK = "ok"
_STATUS_ERROR = "error"


def _elapsed_ms(start: float) -> float:
    """Return milliseconds elapsed since ``start`` (perf_counter), rounded."""

    return round((time.perf_counter() - start) * 1000.0, 2)


def check_database() -> dict[str, Any]:
    """Probe database connectivity with ``SELECT 1``.

    Opens a short-lived session from :data:`app.db.session.SessionLocal`, issues
    a trivial query, and measures round-trip latency. Returns a dict with
    ``status`` of ``"ok"`` or ``"error"`` plus ``latency_ms``; on failure an
    ``error`` key carries a short description. Never raises.
    """

    # Imported lazily so importing this module never triggers engine creation as
    # a side effect (keeps test collection and tooling fast/cheap).
    from app.db.session import SessionLocal

    start = time.perf_counter()
    try:
        session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 - intentional: probes must not raise.
        latency_ms = _elapsed_ms(start)
        logger.warning(
            "Database health check failed after {ms}ms: {err}",
            ms=latency_ms,
            err=str(exc),
        )
        return {
            "status": _STATUS_ERROR,
            "latency_ms": latency_ms,
            "error": str(exc),
        }

    latency_ms = _elapsed_ms(start)
    logger.debug("Database health check ok ({ms}ms).", ms=latency_ms)
    return {"status": _STATUS_OK, "latency_ms": latency_ms}


def check_redis() -> dict[str, Any]:
    """Probe Redis connectivity via :func:`app.core.redis.redis_ping`.

    ``redis_ping`` is documented to log and never raise, returning a boolean.
    We additionally guard the import/call so that even a misconfigured or
    missing Redis module degrades gracefully to ``status="error"``. Never raises.
    """

    start = time.perf_counter()
    try:
        from app.core.redis import redis_ping

        healthy = redis_ping()
    except Exception as exc:  # noqa: BLE001 - probes must not raise.
        latency_ms = _elapsed_ms(start)
        logger.warning(
            "Redis health check raised after {ms}ms: {err}",
            ms=latency_ms,
            err=str(exc),
        )
        return {
            "status": _STATUS_ERROR,
            "latency_ms": latency_ms,
            "error": str(exc),
        }

    latency_ms = _elapsed_ms(start)
    if healthy:
        logger.debug("Redis health check ok ({ms}ms).", ms=latency_ms)
        return {"status": _STATUS_OK, "latency_ms": latency_ms}

    logger.warning("Redis health check reported unhealthy ({ms}ms).", ms=latency_ms)
    return {
        "status": _STATUS_ERROR,
        "latency_ms": latency_ms,
        "error": "redis ping returned false",
    }


def readiness() -> dict[str, Any]:
    """Aggregate dependency probes into a single readiness document.

    Returns ``{"status": "ok"|"error", "checks": {"db": ..., "redis": ...}}``.
    The top-level status is ``"ok"`` only when every sub-check is ``"ok"``; this
    lets the readiness endpoint return 503 the moment any critical dependency is
    unavailable. Never raises.
    """

    db_check = check_database()
    redis_check = check_redis()

    all_ok = db_check.get("status") == _STATUS_OK and redis_check.get("status") == _STATUS_OK
    overall = _STATUS_OK if all_ok else _STATUS_ERROR

    if not all_ok:
        logger.warning(
            "Readiness degraded (db={db}, redis={redis}).",
            db=db_check.get("status"),
            redis=redis_check.get("status"),
        )

    return {
        "status": overall,
        "checks": {
            "db": db_check,
            "redis": redis_check,
        },
    }


__all__ = ["check_database", "check_redis", "readiness"]
