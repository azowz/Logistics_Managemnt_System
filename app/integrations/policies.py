"""Integration policy layer (Sprint 13): URL / event-type validation + rate limiting.

Pure decision logic — no DB, no FastAPI. Validation raises
:class:`~app.services.exceptions.ValidationError`; the rate limiter returns a decision
object the caller acts on.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from app.integrations.event_mapping import ALLOWED_EXTERNAL_EVENT_TYPES
from app.services.exceptions import ValidationError


# --- URL + event-type validation -------------------------------------------


def validate_target_url(url: str, *, allow_insecure: bool = False) -> str:
    """Validate a webhook target URL. HTTPS required unless ``allow_insecure`` (dev/test).

    Rejects non-HTTP(S) schemes and missing hosts. Returns the URL unchanged on success.
    """
    if not url or not url.strip():
        raise ValidationError("target_url is required.")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("target_url must be an http(s) URL.")
    if not parsed.netloc:
        raise ValidationError("target_url must include a host.")
    if parsed.scheme != "https" and not allow_insecure:
        raise ValidationError("target_url must use https.")
    return url.strip()


def validate_event_types(event_types) -> list:
    """Validate a subscription's external event_types: non-empty and all recognized."""
    if not event_types:
        raise ValidationError("event_types must not be empty.")
    if not isinstance(event_types, (list, tuple, set)):
        raise ValidationError("event_types must be a list.")
    normalized = []
    seen = set()
    for et in event_types:
        name = str(et).strip()
        if name in seen:
            continue
        if name not in ALLOWED_EXTERNAL_EVENT_TYPES:
            raise ValidationError(
                f"Unknown event_type '{name}'. Allowed: {', '.join(sorted(ALLOWED_EXTERNAL_EVENT_TYPES))}."
            )
        seen.add(name)
        normalized.append(name)
    return normalized


# --- API-key scopes ---------------------------------------------------------

SCOPE_INBOUND_WRITE = "integrations:inbound:write"
SCOPE_DELIVERIES_READ = "integrations:deliveries:read"
SCOPE_WEBHOOKS_READ = "integrations:webhooks:read"
SCOPE_WEBHOOKS_WRITE = "integrations:webhooks:write"

ALL_SCOPES = frozenset(
    {
        SCOPE_INBOUND_WRITE,
        SCOPE_DELIVERIES_READ,
        SCOPE_WEBHOOKS_READ,
        SCOPE_WEBHOOKS_WRITE,
    }
)


def validate_scopes(scopes) -> Optional[list]:
    """Validate/normalize requested API-key scopes against the known set. None → None."""
    if scopes is None:
        return None
    if not isinstance(scopes, (list, tuple, set)):
        raise ValidationError("scopes must be a list.")
    normalized, seen = [], set()
    for scope in scopes:
        name = str(scope).strip()
        if not name or name in seen:
            continue
        if name not in ALL_SCOPES:
            raise ValidationError(
                f"Unknown scope '{name}'. Allowed: {', '.join(sorted(ALL_SCOPES))}."
            )
        seen.add(name)
        normalized.append(name)
    return normalized or None


# --- Allowed-IP validation + matching ---------------------------------------


def validate_allowed_ips(allowed_ips) -> Optional[list]:
    """Validate a list of exact IPs / CIDR networks. ``None``/empty → allow any (None)."""
    if allowed_ips is None:
        return None
    if not isinstance(allowed_ips, (list, tuple)):
        raise ValidationError("allowed_ips must be a list of IPs or CIDR ranges.")
    normalized = []
    for entry in allowed_ips:
        text = str(entry).strip()
        if not text:
            continue
        try:
            ipaddress.ip_network(text, strict=False)
        except ValueError:
            raise ValidationError(f"Invalid IP or CIDR in allowed_ips: '{text}'.")
        normalized.append(text)
    return normalized or None


def ip_allowed(client_ip: Optional[str], allowed_ips) -> bool:
    """Whether ``client_ip`` matches ``allowed_ips`` (exact or CIDR). Empty list → allow any."""
    if not allowed_ips:
        return True
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in allowed_ips:
        try:
            if addr in ipaddress.ip_network(str(entry), strict=False):
                return True
        except ValueError:
            continue
    return False


# --- Rate limiting ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    limit: int
    retry_after_seconds: int = 0


class InMemoryRateLimitBackend:
    """Process-local fixed-window counters. Deterministic for tests (injectable clock).

    Not suitable for multi-process production enforcement — see docs/27; a Redis-backed
    backend with the same interface is the distributed path.
    """

    def __init__(self) -> None:
        self._windows: Dict[str, Tuple[int, int]] = {}  # key -> (window_start, count)

    def incr(self, key: str, window_start: int) -> int:
        prev_start, count = self._windows.get(key, (window_start, 0))
        if prev_start != window_start:
            count = 0
        count += 1
        self._windows[key] = (window_start, count)
        return count


class RedisRateLimitBackend:
    """Distributed fixed-window backend using Redis ``INCR`` + ``EXPIRE``.

    Shares the ``incr(key, window_start)`` interface with the in-memory backend. Keys are
    namespaced and window-scoped so windows expire on their own. **Fail-open (availability
    mode) by default:** on any Redis error it logs a warning and returns 0 (treated as
    under-limit) so a Redis outage never blocks partner traffic. Set ``fail_open=False`` for
    a high-security fail-closed posture (returns a value above any limit). The client is
    injectable for tests; otherwise the process-wide :func:`app.core.redis.get_redis`.
    """

    def __init__(
        self,
        *,
        client=None,
        window_seconds: int = 60,
        key_prefix: str = "ratelimit",
        fail_open: bool = True,
    ) -> None:
        self._client = client
        self._window = window_seconds
        self._prefix = key_prefix
        self._fail_open = fail_open

    def incr(self, key: str, window_start: int) -> int:
        from app.observability.logging import get_logger

        redis_key = f"{self._prefix}:{key}:{window_start}"
        try:
            client = self._client
            if client is None:
                from app.core.redis import get_redis

                client = get_redis()
            count = int(client.incr(redis_key))
            if count == 1:
                client.expire(redis_key, self._window + 5)
            return count
        except Exception:  # noqa: BLE001 - Redis outage must not hard-fail the request
            get_logger(__name__).warning(
                "Rate-limit Redis backend error; failing %s",
                "open" if self._fail_open else "closed",
                exc_info=False,
            )
            # fail-open → 0 (under limit); fail-closed → large value (over any limit)
            return 0 if self._fail_open else 10**9


class RateLimitPolicy:
    """Fixed-window rate limiter scoped to an arbitrary key (e.g. tenant+api_key).

    ``limit`` requests per ``window_seconds``. The clock is injectable so tests are
    deterministic and never sleep.
    """

    def __init__(
        self,
        *,
        limit: int = 100,
        window_seconds: int = 60,
        backend: Optional[InMemoryRateLimitBackend] = None,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive.")
        self._limit = limit
        self._window = window_seconds
        self._backend = backend or InMemoryRateLimitBackend()

    def check(self, key: str, *, now: float) -> RateLimitDecision:
        window_start = int(now) - (int(now) % self._window)
        count = self._backend.incr(key, window_start)
        remaining = max(0, self._limit - count)
        if count > self._limit:
            retry_after = self._window - (int(now) - window_start)
            return RateLimitDecision(False, 0, self._limit, max(1, retry_after))
        return RateLimitDecision(True, remaining, self._limit)


# Process-wide limiter applied to the inbound integration endpoint, scoped to
# ``tenant:api_key``. Defaults to 120 requests/minute with the in-memory backend
# (single-process). A Redis-backed backend with the same interface is the documented
# distributed-enforcement path (Sprint 14). Overridable for tests / deployment tuning.
_inbound_rate_limiter = RateLimitPolicy(limit=120, window_seconds=60)


def get_inbound_rate_limiter() -> RateLimitPolicy:
    """Return the process-wide inbound rate limiter (DI seam / test override)."""
    return _inbound_rate_limiter


def set_inbound_rate_limiter(limiter: RateLimitPolicy) -> None:
    """Override the process-wide inbound rate limiter."""
    global _inbound_rate_limiter
    _inbound_rate_limiter = limiter


__all__ = [
    "validate_target_url",
    "validate_event_types",
    "RateLimitDecision",
    "InMemoryRateLimitBackend",
    "RedisRateLimitBackend",
    "RateLimitPolicy",
    "get_inbound_rate_limiter",
    "set_inbound_rate_limiter",
    "validate_allowed_ips",
    "ip_allowed",
    "validate_scopes",
    "SCOPE_INBOUND_WRITE",
    "SCOPE_DELIVERIES_READ",
    "SCOPE_WEBHOOKS_READ",
    "SCOPE_WEBHOOKS_WRITE",
    "ALL_SCOPES",
]
