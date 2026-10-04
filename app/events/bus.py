"""Pluggable Event Bus abstraction (M2).

The bus decouples *publishing* an event from the concrete transport. The current
transport is in-process (:class:`InProcessEventBus`); future transports (Kafka,
RabbitMQ, NATS, Azure Service Bus) implement the same :class:`EventBus` interface
so no caller changes when the transport changes.

Handlers are small named consumers (their ``name`` is the idempotency key in
``processed_events``). Projections, audit fan-out, notifications, and analytics
are all just handlers registered on the bus.
"""

from __future__ import annotations

import abc
from typing import ClassVar, Optional, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.events.dispatcher import Dispatcher, DispatchOutcome
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.observability.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class EventHandler(Protocol):
    """A named consumer of domain events."""

    name: str

    def handles(self, event_type: str) -> bool:
        """Return True if this handler wants events of ``event_type``."""
        ...

    def handle(self, event: DomainEvent, envelope: EventEnvelope, session: Session) -> None:
        """Apply the event (e.g. update a projection). May raise to trigger retry."""
        ...


class BaseEventHandler(abc.ABC):
    """Convenience base: subclasses set ``name`` + optional ``event_types`` filter."""

    #: Unique consumer id (used as the idempotency key). Must be set by subclasses.
    name: ClassVar[str] = ""
    #: Subscribed event types; ``None`` means "all events".
    event_types: ClassVar[Optional[frozenset[str]]] = None

    def handles(self, event_type: str) -> bool:
        return self.event_types is None or event_type in self.event_types

    @abc.abstractmethod
    def handle(self, event: DomainEvent, envelope: EventEnvelope, session: Session) -> None:
        """Apply the event. Implementations should be idempotent as defense-in-depth."""
        raise NotImplementedError


class EventBus(abc.ABC):
    """Transport-agnostic event bus interface."""

    @abc.abstractmethod
    def register(self, handler: EventHandler) -> EventHandler:
        """Subscribe a handler; returns it (so it can be used as a decorator)."""

    @abc.abstractmethod
    def publish(
        self, envelope: EventEnvelope, session: Optional[Session] = None
    ) -> DispatchOutcome:
        """Publish an envelope to its subscribers.

        In-process transports dispatch synchronously and require ``session``;
        broker transports serialize the envelope to the broker (``session`` is
        ignored) and a separate consumer process performs dispatch.
        """


class InProcessEventBus(EventBus):
    """Synchronous, in-memory bus: publishes by dispatching to local handlers.

    Used by the outbox relay (which supplies its transaction's ``session``). The
    same handlers run unchanged behind a broker transport later.
    """

    def __init__(self, *, max_retries: int = 3, dispatcher_factory=None) -> None:
        self._handlers: list[EventHandler] = []
        self._max_retries = max_retries
        # Seam: tests inject a fake dispatcher; production builds one per publish.
        self._dispatcher_factory = dispatcher_factory

    def register(self, handler: EventHandler) -> EventHandler:
        # A non-empty, unique name is required: it is the idempotency key in
        # ``processed_events`` (a blank/duplicate name would corrupt dedup).
        name = getattr(handler, "name", "")
        if not name:
            raise ValueError(f"Handler {handler!r} must define a non-empty 'name'")
        if any(h.name == name for h in self._handlers):
            raise ValueError(f"A handler named {name!r} is already registered")
        self._handlers.append(handler)
        logger.debug("Registered event handler", handler=name)
        return handler

    @property
    def handlers(self) -> tuple[EventHandler, ...]:
        return tuple(self._handlers)

    def publish(
        self, envelope: EventEnvelope, session: Optional[Session] = None
    ) -> DispatchOutcome:
        from app.events import metrics  # local import avoids any import cycle at module load

        if session is None:  # pragma: no cover - misuse guard
            raise ValueError("InProcessEventBus.publish requires a Session for dispatch")

        metrics.EVENTS_PUBLISHED.labels(envelope.event_type).inc()
        dispatcher = (
            self._dispatcher_factory(session)
            if self._dispatcher_factory is not None
            else Dispatcher(session, max_retries=self._max_retries)
        )
        outcome = DispatchOutcome()
        for handler in self._handlers:
            if handler.handles(envelope.event_type):
                outcome.record(dispatcher.dispatch(handler, envelope))
        return outcome


# Process-wide default in-process bus. Handlers (projections, etc.) register here
# at startup; the relay worker publishes through it.
default_bus = InProcessEventBus()


def get_event_bus() -> EventBus:
    """Return the configured process-wide event bus (DI seam / test override)."""
    return default_bus


__all__ = [
    "EventHandler",
    "BaseEventHandler",
    "EventBus",
    "InProcessEventBus",
    "default_bus",
    "get_event_bus",
]
