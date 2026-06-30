"""Unit tests for Insurance & Claims domain events."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

import app.events  # noqa: F401
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry
from app.events.insurance_events import ClaimApproved, ClaimCreated, InsurancePolicyCreated

ALL_EVENTS = [
    "InsurancePolicyCreated", "InsurancePolicyActivated", "InsurancePolicySuspended",
    "InsurancePolicyExpired", "InsurancePolicyCancelled", "CoverageRuleCreated",
    "CoverageRuleUpdated", "ClaimCreated", "ClaimSubmittedForReview", "ClaimApproved",
    "ClaimRejected", "ClaimSettled", "ClaimClosed", "ClaimReopened", "ClaimDeleted",
    "ClaimRestored", "DamageReportCreated", "LiabilityRecordCreated",
    "ClaimLinkedToShipment", "ClaimLinkedToEquipment",
]


@pytest.mark.parametrize("et", ALL_EVENTS)
def test_registered(et):
    assert event_registry.is_registered(et)
    assert event_registry.current_version(et) == 1


def test_frozen_and_slots():
    e = ClaimCreated(claim_id=uuid.uuid4(), tenant_id=uuid.uuid4(), claim_number="C1",
                     claim_type="shipment_loss", status="created", shipment_id=None, equipment_id=None)
    with pytest.raises(FrozenInstanceError):
        e.claim_number = "x"  # type: ignore[misc]
    assert "__slots__" in ClaimCreated.__dict__


def test_payload_json_safe():
    cid, tid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = ClaimCreated(claim_id=cid, tenant_id=tid, claim_number="C1", claim_type="shipment_loss",
                     status="created", shipment_id=sid, equipment_id=None)
    p = e.to_payload()
    assert p["claim_id"] == str(cid)
    assert p["shipment_id"] == str(sid)
    assert p["equipment_id"] is None
    assert all(not isinstance(v, uuid.UUID) for v in p.values())


def test_envelope_round_trip():
    cid, tid = uuid.uuid4(), uuid.uuid4()
    e = ClaimApproved(claim_id=cid, tenant_id=tid, previous_status="under_review", approved_amount="1000.00")
    env = EventEnvelope.create(e, tenant_id=tid, aggregate_id=cid, aggregate_version=1, aggregate_type="Claim")
    rebuilt = event_registry.deserialize(env)
    assert isinstance(rebuilt, ClaimApproved)
    assert rebuilt.approved_amount == "1000.00"


def test_policy_event():
    pid, tid = uuid.uuid4(), uuid.uuid4()
    e = InsurancePolicyCreated(policy_id=pid, tenant_id=tid, policy_number="P1",
                               policy_type="cargo", status="draft")
    assert e.to_payload()["policy_number"] == "P1"
