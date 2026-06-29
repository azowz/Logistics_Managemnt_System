"""Enterprise event backbone (M2).

This package provides the transport-agnostic building blocks of the platform's
CQRS-lite + Event-Driven Architecture:

* :mod:`app.events.domain_event` — the reusable :class:`DomainEvent` abstraction
  and JSON-safe (de)serialization of event payloads.
* :mod:`app.events.envelope` — the :class:`EventEnvelope` carrying a domain event
  plus its full metadata (ids, aggregate, correlation/causation, actor, time).
* :mod:`app.events.registry` — the event-type registry and the upcasting chain
  that evolves old event versions forward without breaking history.
* :mod:`app.events.bus` — the pluggable :class:`EventBus` abstraction (in-process
  now; Kafka/NATS/RabbitMQ later) and the in-process implementation.
* :mod:`app.events.dispatcher` — idempotent handler dispatch with retry/DLQ.

Concrete domain events and projections are owned by their bounded contexts and
land with their milestones (M3+); this package is the foundation they plug into.
"""

from __future__ import annotations

from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.events.registry import EventRegistry, Upcaster, event_registry, register_event

# Concrete domain events — imported here so their @register_event decorators run
# at package import time, making the process-wide registry complete.
import app.events.customer_events  # noqa: E402, F401
import app.events.order_events  # noqa: E402, F401
import app.events.shipment_events  # noqa: E402, F401
import app.events.equipment_events  # noqa: E402, F401

__all__ = [
    "DomainEvent",
    "EventEnvelope",
    "EventRegistry",
    "Upcaster",
    "event_registry",
    "register_event",
]
