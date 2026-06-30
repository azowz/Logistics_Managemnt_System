"""Tests for the analytics projection consumer + relay registration (Sprint 11)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.analytics.handlers import AnalyticsProjectionHandler, register_analytics_handlers
from app.events.bus import InProcessEventBus
from app.events.envelope import EventEnvelope
from app.repositories.projection_repository import ShipmentPerformanceProjectionRepository
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
_WHEN = datetime(2026, 6, 20, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant(_Session, tenant_id=_TENANT)


def _env(event_type, payload=None):
    return EventEnvelope(event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="Shipment",
                         aggregate_id=uuid.uuid4(), aggregate_version=1, event_type=event_type,
                         event_version=1, payload=payload or {}, occurred_at=_WHEN)


def test_handler_subscribes_to_operational_events_not_its_own():
    h = AnalyticsProjectionHandler()
    assert h.handles("ShipmentCreated") and h.handles("InvoicePaid") and h.handles("ClaimCreated")
    assert h.handles("NotificationDeliveryAttemptCreated")  # notification metrics
    # not subscribed to events it has no projection for
    assert not h.handles("NotificationTemplateCreated")
    assert h.handles("ClaimSettled")


def test_handler_applies_event():
    s = _Session()
    try:
        AnalyticsProjectionHandler().handle(None, _env("ShipmentCreated"), s)
        s.commit()
        r = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date())
        assert r.total_shipments >= 1
    finally:
        s.close()


def test_register_is_idempotent():
    bus = InProcessEventBus()
    h1 = register_analytics_handlers(bus)
    h2 = register_analytics_handlers(bus)
    assert h1 is h2
    assert len([h for h in bus.handlers if h.name == "analytics"]) == 1


def test_relay_registers_analytics_handler_on_its_bus():
    from app.events import relay as relay_module

    fake = MagicMock()
    fake.scalar.return_value = 0

    @contextmanager
    def _scope(*_a, **_k):
        yield fake

    bus = InProcessEventBus()
    with (
        patch.object(relay_module, "session_scope", _scope),
        patch.object(relay_module, "EventStoreRepository") as MR,
    ):
        MR.return_value.fetch_unpublished.return_value = []
        relay_module.run_outbox_relay(bus=bus)
    names = {h.name for h in bus.handlers}
    assert "analytics" in names and "notifications" in names
