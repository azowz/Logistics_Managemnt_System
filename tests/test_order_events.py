"""Tests for Order domain events: registration, immutability, envelope wrapping."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

from app.events.envelope import EventEnvelope
from app.events.order_events import (
    OrderAddressChanged,
    OrderApproved,
    OrderAssigned,
    OrderCancelled,
    OrderCreated,
    OrderDeleted,
    OrderDelivered,
    OrderFailed,
    OrderInTransit,
    OrderPickedUp,
    OrderPriorityChanged,
    OrderRestored,
    OrderScheduled,
    OrderStatusChanged,
    OrderSubmitted,
    OrderUpdated,
)
from app.events.registry import event_registry

TENANT = uuid.uuid4()
ORDER = uuid.uuid4()
CUSTOMER = uuid.uuid4()
USER = uuid.uuid4()

ALL_EVENTS = [
    OrderCreated,
    OrderSubmitted,
    OrderApproved,
    OrderScheduled,
    OrderAssigned,
    OrderPickedUp,
    OrderInTransit,
    OrderDelivered,
    OrderCancelled,
    OrderFailed,
    OrderRestored,
    OrderUpdated,
    OrderPriorityChanged,
    OrderAddressChanged,
    OrderStatusChanged,
    OrderDeleted,
]


def _wrap(event) -> EventEnvelope:
    return EventEnvelope.create(
        event,
        tenant_id=TENANT,
        aggregate_id=ORDER,
        aggregate_version=1,
        aggregate_type="Order",
        user_id=USER,
    )


def test_sixteen_events_defined():
    assert len(ALL_EVENTS) == 16


@pytest.mark.parametrize("event_cls", ALL_EVENTS)
def test_event_registered(event_cls):
    assert event_registry.is_registered(event_cls.event_type)


@pytest.mark.parametrize("event_cls", ALL_EVENTS)
def test_event_version_is_one(event_cls):
    assert event_cls.event_version == 1


@pytest.mark.parametrize("event_cls", ALL_EVENTS)
def test_registry_resolves_class(event_cls):
    assert event_registry.get(event_cls.event_type, event_cls.event_version) is event_cls


def test_order_created_frozen():
    e = OrderCreated(
        order_id=ORDER,
        tenant_id=TENANT,
        customer_id=CUSTOMER,
        order_number="ORD-1",
        order_type="standard",
        order_source="web",
        priority="normal",
        status="draft",
    )
    with pytest.raises((FrozenInstanceError, AttributeError)):
        e.order_number = "HACK"  # type: ignore[misc]


def test_order_created_envelope_payload():
    e = OrderCreated(
        order_id=ORDER,
        tenant_id=TENANT,
        customer_id=CUSTOMER,
        order_number="ORD-1",
        order_type="express",
        order_source="api",
        priority="high",
        status="draft",
    )
    env = _wrap(e)
    assert env.event_type == "OrderCreated"
    assert env.aggregate_type == "Order"
    assert env.payload["order_number"] == "ORD-1"
    assert env.payload["order_type"] == "express"
    assert env.payload["customer_id"] == str(CUSTOMER)


def test_status_changed_envelope():
    e = OrderStatusChanged(
        order_id=ORDER,
        tenant_id=TENANT,
        previous_status="draft",
        new_status="submitted",
        reason=None,
    )
    env = _wrap(e)
    assert env.payload["previous_status"] == "draft"
    assert env.payload["new_status"] == "submitted"
    assert env.payload["reason"] is None


def test_cancelled_carries_compensation_flag():
    e = OrderCancelled(
        order_id=ORDER,
        tenant_id=TENANT,
        previous_status="in_transit",
        reason="customer request",
        compensation_required=True,
    )
    env = _wrap(e)
    assert env.payload["compensation_required"] is True
    assert env.payload["previous_status"] == "in_transit"


def test_assigned_nullable_dispatcher():
    e = OrderAssigned(
        order_id=ORDER,
        tenant_id=TENANT,
        assigned_dispatcher_id=None,
        previous_status="scheduled",
    )
    env = _wrap(e)
    assert env.payload["assigned_dispatcher_id"] is None


def test_priority_changed_payload():
    e = OrderPriorityChanged(
        order_id=ORDER,
        tenant_id=TENANT,
        previous_priority="normal",
        new_priority="urgent",
    )
    env = _wrap(e)
    assert env.payload["previous_priority"] == "normal"
    assert env.payload["new_priority"] == "urgent"


def test_address_changed_payload():
    e = OrderAddressChanged(
        order_id=ORDER,
        tenant_id=TENANT,
        changed_fields={"pickup_location": "Riyadh DC"},
    )
    env = _wrap(e)
    assert env.payload["changed_fields"]["pickup_location"] == "Riyadh DC"


def test_picked_up_payload():
    e = OrderPickedUp(
        order_id=ORDER,
        tenant_id=TENANT,
        picked_up_at="2026-06-27T10:00:00+00:00",
        previous_status="assigned",
    )
    env = _wrap(e)
    assert env.payload["picked_up_at"].startswith("2026-06-27")


def test_deleted_nullable_actor():
    e = OrderDeleted(order_id=ORDER, tenant_id=TENANT, deleted_by=None)
    env = _wrap(e)
    assert env.payload["deleted_by"] is None


def test_address_changed_decimal_payload_is_json_serializable():
    """Decimal coordinates in changed_fields must serialize (JSONB-safe)."""
    import json
    from decimal import Decimal

    e = OrderAddressChanged(
        order_id=ORDER,
        tenant_id=TENANT,
        changed_fields={"pickup_latitude": Decimal("24.774265"), "distance_km": Decimal("12.50")},
    )
    env = _wrap(e)
    # to_payload must have coerced Decimal → str (JSON has no decimal type).
    assert env.payload["changed_fields"]["pickup_latitude"] == "24.774265"
    # The whole payload must be json.dumps-able (this is what JSONB storage does).
    json.dumps(env.payload)
