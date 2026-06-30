"""Tests for Billing & Settlements domain events (Sprint 9)."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

import app.events  # noqa: F401  (ensures registration)
from app.events import billing_events as be
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry

ALL_EVENTS = be.__all__


@pytest.mark.parametrize("et", ALL_EVENTS)
def test_registered(et):
    assert event_registry.is_registered(et)
    assert event_registry.current_version(et) == 1


def test_event_count_is_24():
    assert len(ALL_EVENTS) == 24


def test_frozen_and_slots():
    e = be.QuoteCreated(quote_id=uuid.uuid4(), tenant_id=uuid.uuid4(), quote_number="QUO-1",
                        status="draft", total_amount="100.00")
    with pytest.raises(FrozenInstanceError):
        e.quote_number = "x"  # type: ignore[misc]
    assert "__slots__" in be.QuoteCreated.__dict__


def test_payload_json_safe():
    sid, tid, cid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = be.SettlementCreated(settlement_id=sid, tenant_id=tid, settlement_number="STL-1",
                             settlement_type="claim_payout", status="draft", amount="500.00", claim_id=cid)
    p = e.to_payload()
    assert p["settlement_id"] == str(sid)
    assert p["claim_id"] == str(cid)
    assert all(not isinstance(v, uuid.UUID) for v in p.values())


def test_envelope_round_trip():
    pid, tid, iid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = be.PaymentRecorded(payment_id=pid, tenant_id=tid, invoice_id=iid, amount="250.00", method="cash")
    env = EventEnvelope.create(e, tenant_id=tid, aggregate_id=iid, aggregate_version=1, aggregate_type="Invoice")
    rebuilt = event_registry.deserialize(env)
    assert isinstance(rebuilt, be.PaymentRecorded)
    assert rebuilt.amount == "250.00"


def test_invoice_event_payload():
    iid, tid = uuid.uuid4(), uuid.uuid4()
    e = be.InvoiceCreated(invoice_id=iid, tenant_id=tid, invoice_number="INV-1", status="draft", total_amount="0.00")
    assert e.to_payload()["invoice_number"] == "INV-1"


def test_claim_settlement_consumed_payload():
    sid, tid, cid, iid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = be.ClaimSettlementConsumed(settlement_id=sid, tenant_id=tid, claim_id=cid, amount="200.00",
                                   invoice_id=iid, adjustment_amount="200.00")
    p = e.to_payload()
    assert p["settlement_id"] == str(sid)
    assert p["claim_id"] == str(cid)
    assert p["invoice_id"] == str(iid)
    assert p["adjustment_amount"] == "200.00"
    assert all(not isinstance(v, uuid.UUID) for v in p.values())
