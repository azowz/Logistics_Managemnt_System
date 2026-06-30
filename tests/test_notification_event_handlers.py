"""Tests for event-driven notification creation via NotificationEventHandler."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.events.envelope import EventEnvelope
from app.events.shipment_events import ShipmentDelayed
from app.models.enums import NotificationChannel, NotificationStatus
from app.models.notification import Notification
from app.notifications.handlers import (
    NotificationEventHandler,
    TRIGGER_EVENT_TYPES,
    register_notification_handlers,
)
from app.repositories.notification_repository import NotificationRepository
from notifications_sqlite import make_engine, seed_template, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)


@pytest.fixture(autouse=True)
def ctx():
    # The handler runs inside the dispatcher's session; the outbox append is
    # patched so these tests focus on notification creation/delivery.
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
        patch("app.services.notification_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


def _envelope(event_type="ShipmentDelayed", *, user_id=_USER, event=None):
    agg = uuid.uuid4()
    evt = event or ShipmentDelayed(shipment_id=agg, tenant_id=_TENANT, previous_status="in_transit",
                                   reason="weather")
    return evt, EventEnvelope.create(evt, tenant_id=_TENANT, aggregate_id=agg, aggregate_version=1,
                                     aggregate_type="Shipment", user_id=user_id)


def test_handler_subscribes_to_all_triggers():
    h = NotificationEventHandler()
    assert h.handles("ShipmentDelayed")
    assert h.handles("InvoicePaid")
    assert not h.handles("NotificationSent")  # never re-notifies its own events
    assert len(TRIGGER_EVENT_TYPES) == 22


def test_handler_creates_in_app_notification():
    evt, env = _envelope("ShipmentDelayed")
    s = _Session()
    try:
        NotificationEventHandler().handle(evt, env, s)
        s.commit()
        repo = NotificationRepository(s)
        items, total = repo.list_notifications(event_type="ShipmentDelayed")
        mine = [n for n in items if n.event_id == env.event_id]
        assert len(mine) == 1
        n = mine[0]
        assert n.channel == NotificationChannel.IN_APP
        assert n.recipient_user_id == _USER
        assert n.status == NotificationStatus.SENT  # in-app delivered synchronously
    finally:
        s.close()


def test_handler_uses_active_template_when_present():
    seed_template(_Session, tenant_id=_TENANT, template_id=uuid.uuid4(), code="ship-delay",
                  channel="in_app", event_type="ShipmentReturned", subject="Delayed",
                  body="Shipment {aggregate_id} returned")
    from app.events.shipment_events import ShipmentReturned
    agg = uuid.uuid4()
    evt = ShipmentReturned(shipment_id=agg, tenant_id=_TENANT, previous_status="in_transit", reason="x")
    env = EventEnvelope.create(evt, tenant_id=_TENANT, aggregate_id=agg, aggregate_version=1,
                               aggregate_type="Shipment", user_id=_USER)
    s = _Session()
    try:
        NotificationEventHandler().handle(evt, env, s)
        s.commit()
        n = NotificationRepository(s).get_by_event_recipient_key(f"{env.event_id}:in_app:{_USER}")
        assert n is not None and str(agg) in n.body
    finally:
        s.close()


def test_handler_skips_when_no_actor():
    evt, env = _envelope("ShipmentDelayed", user_id=None)
    s = _Session()
    try:
        NotificationEventHandler().handle(evt, env, s)
        s.commit()
        items, _ = NotificationRepository(s).list_notifications(event_type="ShipmentDelayed")
        assert all(n.event_id != env.event_id for n in items)  # no target -> no notification
    finally:
        s.close()


def test_register_is_idempotent():
    from app.events.bus import InProcessEventBus
    bus = InProcessEventBus()
    h1 = register_notification_handlers(bus)
    h2 = register_notification_handlers(bus)
    assert h1 is h2
    assert len([x for x in bus.handlers if x.name == "notifications"]) == 1


def test_relay_registers_notification_handler_on_its_bus():
    """H1: run_outbox_relay attaches the notification consumer to the bus it publishes through."""
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from app.events.bus import InProcessEventBus
    from app.events import relay as relay_module

    fake_session = MagicMock()
    fake_session.scalar.return_value = 0

    @contextmanager
    def _scope(*_a, **_k):
        yield fake_session

    bus = InProcessEventBus()
    assert not any(h.name == "notifications" for h in bus.handlers)
    with (
        patch.object(relay_module, "session_scope", _scope),
        patch.object(relay_module, "EventStoreRepository") as MR,
    ):
        MR.return_value.fetch_unpublished.return_value = []
        relay_module.run_outbox_relay(bus=bus)
    # The relay wired the consumer onto the very bus it uses to publish.
    assert any(h.name == "notifications" for h in bus.handlers)
