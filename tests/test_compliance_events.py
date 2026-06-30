"""Unit tests for Compliance domain events: registration, serialization, envelope."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

import app.events  # noqa: F401
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry
from app.events.compliance_events import (
    ComplianceCheckFailed,
    DispatchBlockedByCompliance,
    PermitApproved,
    PermitCreated,
)

ALL_EVENTS = [
    "PermitCreated", "PermitSubmitted", "PermitUnderReview", "PermitApproved",
    "PermitRejected", "PermitActivated", "PermitExpired", "PermitCancelled",
    "PermitDeleted", "PermitRestored", "EscortCreated", "EscortScheduled",
    "EscortCancelled", "RouteRestrictionCreated", "RouteRestrictionUpdated",
    "AxleWeightProfileCreated", "ComplianceCheckCreated", "ComplianceCheckPassed",
    "ComplianceCheckFailed", "ComplianceOverrideApplied", "OperatorCertificationCreated",
    "OperatorCertificationExpired", "DispatchBlockedByCompliance", "DispatchClearedByCompliance",
]


@pytest.mark.parametrize("et", ALL_EVENTS)
def test_registered(et):
    assert event_registry.is_registered(et)
    assert event_registry.current_version(et) == 1


def test_frozen_and_slots():
    e = PermitCreated(permit_id=uuid.uuid4(), tenant_id=uuid.uuid4(), permit_number="P1",
                      permit_type="oversize", status="draft", shipment_id=None, equipment_id=None)
    with pytest.raises(FrozenInstanceError):
        e.permit_number = "x"  # type: ignore[misc]
    assert "__slots__" in PermitCreated.__dict__


def test_payload_json_safe_and_optional_none():
    pid, tid = uuid.uuid4(), uuid.uuid4()
    e = PermitCreated(permit_id=pid, tenant_id=tid, permit_number="P1", permit_type="oversize",
                      status="draft", shipment_id=None, equipment_id=None)
    p = e.to_payload()
    assert p["permit_id"] == str(pid)
    assert p["shipment_id"] is None
    assert all(not isinstance(v, uuid.UUID) for v in p.values())


def test_failed_event_carries_reasons_list():
    e = ComplianceCheckFailed(check_id=uuid.uuid4(), tenant_id=uuid.uuid4(), shipment_id=uuid.uuid4(),
                              check_type="permit_required", failure_reasons=["no permit"])
    assert e.to_payload()["failure_reasons"] == ["no permit"]


def test_envelope_round_trip():
    pid, tid = uuid.uuid4(), uuid.uuid4()
    e = PermitApproved(permit_id=pid, tenant_id=tid, previous_status="under_review",
                       valid_from=None, valid_until=None)
    env = EventEnvelope.create(e, tenant_id=tid, aggregate_id=pid, aggregate_version=1, aggregate_type="Permit")
    rebuilt = event_registry.deserialize(env)
    assert isinstance(rebuilt, PermitApproved)
    assert rebuilt.permit_id == pid


def test_dispatch_blocked_event():
    sid, tid = uuid.uuid4(), uuid.uuid4()
    e = DispatchBlockedByCompliance(shipment_id=sid, tenant_id=tid, stage="assign", blocking_reasons=["x"])
    assert e.to_payload()["stage"] == "assign"
