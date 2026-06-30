"""Unit tests for Equipment domain events: registration, serialization, envelope."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import app.events  # noqa: F401 — ensure registration on import
from app.events.domain_event import to_jsonable
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry
from app.events.equipment_events import (
    EquipmentAssignedToShipment,
    EquipmentCreated,
    EquipmentDecommissioned,
    EquipmentSpecificationChanged,
)

ALL_EVENTS = [
    "EquipmentCreated",
    "EquipmentUpdated",
    "EquipmentActivated",
    "EquipmentDeactivated",
    "EquipmentReserved",
    "EquipmentReleased",
    "EquipmentAssignedToShipment",
    "EquipmentInTransit",
    "EquipmentDelivered",
    "EquipmentMaintenanceStarted",
    "EquipmentMaintenanceCompleted",
    "EquipmentDecommissioned",
    "EquipmentDeleted",
    "EquipmentRestored",
    "EquipmentStatusChanged",
    "EquipmentAvailabilityChanged",
    "EquipmentLocationChanged",
    "EquipmentSpecificationChanged",
    "EquipmentCategoryCreated",
    "EquipmentModelCreated",
]


@pytest.mark.parametrize("et", ALL_EVENTS)
def test_registered(et):
    assert event_registry.is_registered(et)
    assert event_registry.current_version(et) == 1


def test_frozen():
    e = EquipmentDecommissioned(
        equipment_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        previous_status="active", reason="write-off",
    )
    with pytest.raises(FrozenInstanceError):
        e.reason = "x"  # type: ignore[misc]


def test_declares_slots():
    assert "__slots__" in EquipmentCreated.__dict__


def test_created_payload_json_safe():
    eid, tid, cid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = EquipmentCreated(
        equipment_id=eid, tenant_id=tid, equipment_code="EQP-1", asset_tag="T-1",
        category_id=cid, model_id=None, status="active",
        availability_status="available", ownership_type="owned",
    )
    p = e.to_payload()
    assert p["equipment_id"] == str(eid)
    assert p["category_id"] == str(cid)
    assert p["model_id"] is None
    assert all(not isinstance(v, uuid.UUID) for v in p.values())


def test_spec_changed_decimal_serializable():
    changed = to_jsonable(
        {"weight_kg": Decimal("12000.50"), "height_m": Decimal("4.20")}
    )
    e = EquipmentSpecificationChanged(
        equipment_id=uuid.uuid4(), tenant_id=uuid.uuid4(), changed_fields=changed
    )
    assert e.to_payload()["changed_fields"]["weight_kg"] == "12000.50"


def test_envelope_round_trip():
    eid, tid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = EquipmentAssignedToShipment(
        equipment_id=eid, tenant_id=tid, shipment_id=sid,
        previous_availability="available",
    )
    env = EventEnvelope.create(
        e, tenant_id=tid, aggregate_id=eid, aggregate_version=1,
        aggregate_type="Equipment",
    )
    assert env.event_type == "EquipmentAssignedToShipment"
    rebuilt = event_registry.deserialize(env)
    assert isinstance(rebuilt, EquipmentAssignedToShipment)
    assert rebuilt.shipment_id == sid
