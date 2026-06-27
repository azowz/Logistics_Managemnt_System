"""Prometheus instrumentation for the event backbone (M2 observability).

Metric families cover the lifecycle the M2 brief requires: publishing,
processing latency, failures, retries, dead-letters, outbox/queue depth, and
replay duration. All names are prefixed ``mesaar_event*`` for easy scraping.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

EVENTS_PUBLISHED = Counter(
    "mesaar_events_published_total",
    "Domain events published from the outbox to the bus.",
    ["event_type"],
)
EVENTS_PROCESSED = Counter(
    "mesaar_events_processed_total",
    "Domain events successfully processed by a consumer.",
    ["event_type", "consumer"],
)
EVENTS_SKIPPED = Counter(
    "mesaar_events_skipped_total",
    "Events skipped by a consumer as already-processed (idempotency).",
    ["event_type", "consumer"],
)
EVENTS_FAILED = Counter(
    "mesaar_events_failed_total",
    "Consumer handler invocations that raised before succeeding.",
    ["event_type", "consumer"],
)
EVENTS_RETRIED = Counter(
    "mesaar_events_retried_total",
    "Consumer handler retries attempted.",
    ["event_type", "consumer"],
)
EVENTS_DEAD_LETTERED = Counter(
    "mesaar_events_dead_lettered_total",
    "Events moved to the dead-letter queue after exhausting retries.",
    ["event_type", "consumer"],
)
PUBLISH_FAILURES = Counter(
    "mesaar_event_publish_failures_total",
    "Outbox publish attempts that failed at the transport layer.",
    ["event_type"],
)

DISPATCH_LATENCY = Histogram(
    "mesaar_event_dispatch_seconds",
    "Wall-clock seconds to dispatch an event to a single consumer.",
    ["event_type", "consumer"],
)
REPLAY_DURATION = Histogram(
    "mesaar_event_replay_seconds",
    "Wall-clock seconds to replay an event stream.",
    ["scope"],
)

OUTBOX_DEPTH = Gauge(
    "mesaar_outbox_unpublished",
    "Number of unpublished rows currently in the outbox (lag indicator).",
)

__all__ = [
    "EVENTS_PUBLISHED",
    "EVENTS_PROCESSED",
    "EVENTS_SKIPPED",
    "EVENTS_FAILED",
    "EVENTS_RETRIED",
    "EVENTS_DEAD_LETTERED",
    "PUBLISH_FAILURES",
    "DISPATCH_LATENCY",
    "REPLAY_DURATION",
    "OUTBOX_DEPTH",
]
