"""Tests for Notifications domain events (Sprint 10)."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

import app.events  # noqa: F401
from app.events import notification_events as ne
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry

ALL_EVENTS = ne.__all__


@pytest.mark.parametrize("et", ALL_EVENTS)
def test_registered(et):
    assert event_registry.is_registered(et)
    assert event_registry.current_version(et) == 1


def test_event_count_is_12():
    assert len(ALL_EVENTS) == 12


def test_frozen_and_slots():
    e = ne.NotificationCreated(notification_id=uuid.uuid4(), tenant_id=uuid.uuid4(), channel="in_app",
                               status="pending", source_event_type="ShipmentDelayed", recipient_user_id=uuid.uuid4())
    with pytest.raises(FrozenInstanceError):
        e.channel = "email"  # type: ignore[misc]
    assert "__slots__" in ne.NotificationCreated.__dict__


def test_payload_json_safe():
    nid, tid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = ne.NotificationCreated(notification_id=nid, tenant_id=tid, channel="in_app", status="pending",
                               source_event_type="ClaimApproved", recipient_user_id=uid)
    p = e.to_payload()
    assert p["notification_id"] == str(nid)
    assert p["recipient_user_id"] == str(uid)
    assert all(not isinstance(v, uuid.UUID) for v in p.values())


def test_envelope_round_trip():
    nid, tid = uuid.uuid4(), uuid.uuid4()
    e = ne.NotificationSent(notification_id=nid, tenant_id=tid, channel="in_app", provider="in_app")
    env = EventEnvelope.create(e, tenant_id=tid, aggregate_id=nid, aggregate_version=1, aggregate_type="Notification")
    rebuilt = event_registry.deserialize(env)
    assert isinstance(rebuilt, ne.NotificationSent)
    assert rebuilt.provider == "in_app"


def test_delivery_attempt_event_payload():
    aid, tid, nid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e = ne.NotificationDeliveryAttemptCreated(attempt_id=aid, tenant_id=tid, notification_id=nid,
                                              channel="email", status="skipped", attempt_number=1)
    assert e.to_payload()["status"] == "skipped"
    assert e.to_payload()["attempt_number"] == 1
