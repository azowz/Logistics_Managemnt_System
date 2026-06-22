"""Redis client provisioning for the Mesaar logistics platform.

This module exposes a cached Redis client singleton built from the
application settings (``settings.redis_url``) and a defensive ``redis_ping``
helper used by readiness/health checks.

The client uses ``decode_responses=True`` so callers always receive ``str``
values rather than raw ``bytes``, which keeps higher layers (token denylists,
caches) free of manual decoding.

Public symbols:
    * :func:`get_redis` -- cached singleton :class:`redis.Redis`.
    * :func:`redis_ping` -- best-effort health probe (logs, never raises).
"""

from __future__ import annotations

from functools import lru_cache

import redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Return a cached, process-wide :class:`redis.Redis` client.

    The client is constructed lazily from ``settings.redis_url`` and cached
    for the lifetime of the process. ``decode_responses=True`` ensures string
    values are returned. A modest socket timeout prevents requests from
    hanging indefinitely when Redis is unreachable.

    Returns:
        A configured :class:`redis.Redis` instance. Connecting is lazy; the
        first command issued will establish the underlying connection.
    """
    settings = get_settings()
    # ``from_url`` parses scheme/host/port/db from the configured URL.
    # decode_responses keeps the rest of the codebase free of byte handling.
    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        health_check_interval=30,
        retry_on_timeout=True,
    )
    logger.debug("Initialized Redis client", extra={"redis_url": settings.redis_url})
    return client


def redis_ping() -> bool:
    """Probe Redis connectivity without raising.

    Intended for readiness/health checks: any failure is logged and reported
    as ``False`` rather than propagated, so a degraded Redis never crashes the
    health endpoint.

    Returns:
        ``True`` if Redis answered ``PING`` with ``PONG``; ``False`` otherwise.
    """
    try:
        client = get_redis()
        # ``ping`` returns True on success for redis-py's high-level client.
        result = bool(client.ping())
        if not result:
            logger.warning("Redis PING returned a falsy response")
        return result
    except RedisError as exc:
        # Connection refused, timeouts, auth errors, etc. -- expected failure modes.
        logger.warning("Redis PING failed", extra={"error": str(exc)})
        return False
    except OSError as exc:
        # Lower-level socket/DNS errors that may surface before RedisError.
        logger.warning("Redis PING failed at socket level", extra={"error": str(exc)})
        return False
