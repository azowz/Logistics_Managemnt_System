"""Webhook consumer (BaseEventHandler) tests: fan-out + registration (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.events.bus import InProcessEventBus
from app.events.envelope import EventEnvelope
from app.integrations.handlers import WebhookEventHandler, register_webhook_handlers
from app.models.enums import IntegrationPartnerType
from app.repositories.integration_repository import WebhookDeliveryRepository
from app.services.integration_service import IntegrationService
from integrations_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)


@pytest.fixture(autouse=True)
def _ctx():
    t1 = set_current_tenant(_TENANT)
    t2 = set_current_user_id(_USER)
    try:
        yield
    finally:
        reset_current_user_id(t2)
        reset_current_tenant(t1)


def _subscribe():
    svc = IntegrationService(_Session())
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                            event_types=["shipment.delivered"])
    return p


def _env(event_type="ShipmentDelivered"):
    return EventEnvelope(event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="Shipment",
                         aggregate_id=uuid.uuid4(), aggregate_version=1, event_type=event_type,
                         event_version=1, payload={"shipment_id": "x", "status": "delivered"}, occurred_at=None)


def test_handler_creates_delivery_for_mapped_event():
    _subscribe()
    s = _Session()
    WebhookEventHandler().handle(None, _env(), s)
    s.commit()
    items, total = WebhookDeliveryRepository(s).list_deliveries(external_event_type="shipment.delivered")
    assert total >= 1
    s.close()


def test_handler_ignores_unmapped_event():
    _subscribe()
    s = _Session()
    WebhookEventHandler().handle(None, _env("CustomerCreated"), s)
    s.commit()
    # no delivery for an unmapped external type
    items, total = WebhookDeliveryRepository(s).list_deliveries(external_event_type="customer.created")
    assert total == 0
    s.close()


def test_registration_is_idempotent():
    bus = InProcessEventBus()
    h1 = register_webhook_handlers(bus)
    h2 = register_webhook_handlers(bus)
    assert h1 is h2
    assert sum(1 for h in bus.handlers if h.name == "webhooks") == 1
