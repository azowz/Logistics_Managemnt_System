"""Unit tests for the in-process event bus (fan-out, filtering, registration)."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from app.common.datetime import utcnow
from app.events.bus import BaseEventHandler, InProcessEventBus
from app.events.dispatcher import PROCESSED
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope


@dataclasses.dataclass(frozen=True, slots=True)
class _Ev(DomainEvent):
    event_type = "TypeA"
    event_version = 1
    x: int


class _FakeDispatcher:
    """Records (consumer, event_type) dispatched; always reports PROCESSED."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[str, str]] = []

    def dispatch(self, handler, envelope) -> str:
        self.dispatched.append((handler.name, envelope.event_type))
        return PROCESSED


class _HandlerA(BaseEventHandler):
    name = "only-a"
    event_types = frozenset({"TypeA"})

    def handle(self, event, envelope, session) -> None:  # pragma: no cover - not called (fake dispatcher)
        pass


class _HandlerAll(BaseEventHandler):
    name = "all"
    event_types = None  # all events

    def handle(self, event, envelope, session) -> None:  # pragma: no cover
        pass


def _env(event_type: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(), tenant_id=uuid.uuid4(), aggregate_type="X",
        aggregate_id=uuid.uuid4(), aggregate_version=1, event_type=event_type,
        event_version=1, payload={}, occurred_at=utcnow(),
    )


def test_publish_fans_out_only_to_matching_handlers() -> None:
    fake = _FakeDispatcher()
    bus = InProcessEventBus(dispatcher_factory=lambda session: fake)
    bus.register(_HandlerA())
    bus.register(_HandlerAll())

    out = bus.publish(_env("TypeA"), session=object())
    assert sorted(fake.dispatched) == [("all", "TypeA"), ("only-a", "TypeA")]
    assert out.processed == 2

    fake.dispatched.clear()
    bus.publish(_env("TypeB"), session=object())
    # Only the catch-all handler wants TypeB.
    assert fake.dispatched == [("all", "TypeB")]


def test_register_requires_name_and_rejects_duplicates() -> None:
    bus = InProcessEventBus()

    class _Nameless(BaseEventHandler):
        name = ""

        def handle(self, event, envelope, session) -> None:  # pragma: no cover
            pass

    with pytest.raises(ValueError):
        bus.register(_Nameless())

    bus.register(_HandlerAll())
    with pytest.raises(ValueError):
        bus.register(_HandlerAll())  # duplicate name


def test_inprocess_publish_requires_session() -> None:
    bus = InProcessEventBus()
    with pytest.raises(ValueError):
        bus.publish(_env("TypeA"), session=None)
