"""Integration policy layer (Sprint 13): URL / event-type validation + rate limiting.

Pure decision logic — no DB, no FastAPI. Validation raises
:class:`~app.services.exceptions.ValidationError`; the rate limiter returns a decision
object the caller acts on.
"""

from __future__ import annotations

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


class RateLimitPolicy:
    """Fixed-window rate limiter scoped to an arbitrary key (e.g. tenant+api_key).

    ``limit`` requests per ``window_seconds``. The clock is injectable so tests are
    deterministic and never sleep.
    """

    def __init__(self, *, limit: int = 100, window_seconds: int = 60,
                 backend: Optional[InMemoryRateLimitBackend] = None) -> None:
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


__all__ = [
    "validate_target_url",
    "validate_event_types",
    "RateLimitDecision",
    "InMemoryRateLimitBackend",
    "RateLimitPolicy",
]
