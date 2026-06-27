"""Unit tests for the event registry and version upcasting."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.events.exceptions import EventDeserializationError, UnknownEventTypeError
from app.events.registry import EventRegistry


@dataclasses.dataclass(frozen=True, slots=True)
class _OrderPlacedV1(DomainEvent):
    event_type = "OrderPlaced"
    event_version = 1
    order_id: uuid.UUID


@dataclasses.dataclass(frozen=True, slots=True)
class _OrderPlacedV2(DomainEvent):
    event_type = "OrderPlaced"
    event_version = 2
    order_id: uuid.UUID
    channel: str


@dataclasses.dataclass(frozen=True, slots=True)
class _OrderPlacedV3(DomainEvent):
    event_type = "OrderPlaced"
    event_version = 3
    order_id: uuid.UUID
    channel: str
    currency: str


def _envelope(event: DomainEvent, version: int) -> EventEnvelope:
    oid = getattr(event, "order_id")
    env = EventEnvelope.create(
        event, tenant_id=uuid.uuid4(), aggregate_id=oid, aggregate_version=1, aggregate_type="Order"
    )
    # Force the stored version to simulate an old record on disk.
    return dataclasses.replace(env, event_version=version)


def test_register_and_lookup() -> None:
    reg = EventRegistry()
    reg.register(_OrderPlacedV1)
    assert reg.is_registered("OrderPlaced")
    assert reg.current_version("OrderPlaced") == 1
    assert reg.get("OrderPlaced", 1) is _OrderPlacedV1


def test_duplicate_version_registration_rejected() -> None:
    reg = EventRegistry()
    reg.register(_OrderPlacedV1)

    @dataclasses.dataclass(frozen=True, slots=True)
    class _Other(DomainEvent):
        event_type = "OrderPlaced"
        event_version = 1
        order_id: uuid.UUID

    with pytest.raises(ValueError):
        reg.register(_Other)


def test_upcasting_chain_v1_to_v3() -> None:
    reg = EventRegistry()
    reg.register(_OrderPlacedV1)
    reg.register(_OrderPlacedV2)
    reg.register(_OrderPlacedV3)
    reg.register_upcaster("OrderPlaced", 1, lambda p: {**p, "channel": "web"})
    reg.register_upcaster("OrderPlaced", 2, lambda p: {**p, "currency": "SAR"})

    env = _envelope(_OrderPlacedV1(order_id=uuid.uuid4()), version=1)
    event = reg.deserialize(env)
    assert isinstance(event, _OrderPlacedV3)
    assert event.channel == "web" and event.currency == "SAR"


def test_missing_upcaster_is_loud() -> None:
    reg = EventRegistry()
    reg.register(_OrderPlacedV1)
    reg.register(_OrderPlacedV3)  # gap: no v2 class, no upcasters
    env = _envelope(_OrderPlacedV1(order_id=uuid.uuid4()), version=1)
    with pytest.raises(EventDeserializationError):
        reg.deserialize(env)


def test_unknown_event_type_raises() -> None:
    reg = EventRegistry()
    env = _envelope(_OrderPlacedV1(order_id=uuid.uuid4()), version=1)
    with pytest.raises(UnknownEventTypeError):
        reg.deserialize(env)
