"""Unit tests for Shipment domain events: registration, serialization, envelope."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import app.events  # noqa: F401 — ensure events are registered on import
from app.events.domain_event import to_jsonable
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry
from app.events.shipment_events import (
    ShipmentAssigned,
    ShipmentCancelled,
    ShipmentCreated,
    ShipmentDelayed,
    ShipmentDelivered,
    ShipmentStatusChanged,
    ShipmentUpdated,
)

ALL_EVENT_TYPES = [
    "ShipmentCreated",
    "ShipmentMarkedReady",
    "ShipmentAssigned",
    "ShipmentPickedUp",
    "ShipmentInTransit",
    "ShipmentDelayed",
    "ShipmentDelivered",
    "ShipmentFailed",
    "ShipmentReturned",
    "ShipmentCancelled",
    "ShipmentUpdated",
    "ShipmentDeleted",
    "ShipmentRestored",
    "ShipmentAddressChanged",
    "ShipmentCargoChanged",
    "ShipmentDriverChanged",
    "ShipmentVehicleChanged",
    "ShipmentStatusChanged",
]


@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
def test_all_events_registered(event_type):
    assert event_registry.is_registered(event_type)
    assert event_registry.current_version(event_type) == 1


def test_event_is_frozen():
    e = ShipmentDelivered(
        shipment_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        delivered_at=None,
        previous_status="in_transit",
    )
    with pytest.raises(FrozenInstanceError):
        e.shipment_id = uuid.uuid4()  # type: ignore[misc]


def test_event_declares_slots():
    # @dataclass(slots=True) defines __slots__ on the class (the base
    # DomainEvent has no __slots__, so instances may still carry __dict__).
    assert "__slots__" in ShipmentDelayed.__dict__
    assert "reason" in ShipmentDelayed.__slots__


def test_to_payload_is_json_safe_uuid_datetime():
    sid, tid, cid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = ShipmentCreated(
        shipment_id=sid,
        tenant_id=tid,
        reference_code="SHP-1",
        client_id=cid,
        origin_warehouse_id=uuid.uuid4(),
        destination_warehouse_id=uuid.uuid4(),
        order_id=None,
        status="created",
        priority="normal",
    )
    payload = e.to_payload()
    assert payload["shipment_id"] == str(sid)
    assert payload["client_id"] == str(cid)
    assert payload["order_id"] is None
    # Payload must be JSON-native (no UUID objects).
    assert all(not isinstance(v, uuid.UUID) for v in payload.values())


def test_changed_fields_decimal_and_datetime_serializable():
    changed = to_jsonable(
        {
            "weight_kg": Decimal("12.50"),
            "delivery_due_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "vehicle_id": uuid.uuid4(),
        }
    )
    e = ShipmentUpdated(
        shipment_id=uuid.uuid4(), tenant_id=uuid.uuid4(), changed_fields=changed
    )
    payload = e.to_payload()
    assert payload["changed_fields"]["weight_kg"] == "12.50"
    assert payload["changed_fields"]["delivery_due_at"].startswith("2026-01-01")


def test_round_trip_from_payload():
    sid, tid = uuid.uuid4(), uuid.uuid4()
    e = ShipmentCancelled(
        shipment_id=sid,
        tenant_id=tid,
        previous_status="assigned",
        reason="customer",
        compensation_required=True,
    )
    payload = e.to_payload()
    restored = ShipmentCancelled.from_payload(payload)
    assert restored.shipment_id == sid
    assert restored.tenant_id == tid
    assert restored.compensation_required is True
    assert restored.reason == "customer"


def test_envelope_create_and_deserialize():
    sid, tid = uuid.uuid4(), uuid.uuid4()
    e = ShipmentAssigned(
        shipment_id=sid,
        tenant_id=tid,
        driver_id=uuid.uuid4(),
        vehicle_id=None,
        previous_status="ready",
    )
    env = EventEnvelope.create(
        e,
        tenant_id=tid,
        aggregate_id=sid,
        aggregate_version=1,
        aggregate_type="Shipment",
    )
    assert env.event_type == "ShipmentAssigned"
    assert env.event_version == 1
    assert env.aggregate_type == "Shipment"
    # Registry can rebuild the current-version event from the envelope.
    rebuilt = event_registry.deserialize(env)
    assert isinstance(rebuilt, ShipmentAssigned)
    assert rebuilt.shipment_id == sid


def test_status_changed_carries_reason_optional():
    e = ShipmentStatusChanged(
        shipment_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        previous_status="created",
        new_status="ready",
        reason=None,
    )
    assert e.to_payload()["reason"] is None
