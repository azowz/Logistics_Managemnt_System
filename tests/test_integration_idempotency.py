"""Idempotency tests: outbound delivery + inbound event de-duplication (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.events.envelope import EventEnvelope
from app.models.enums import IntegrationPartnerType
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


def _svc():
    return IntegrationService(_Session())


def test_replayed_source_event_creates_single_delivery():
    svc = _svc()
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                            event_types=["shipment.delivered"])
    env = EventEnvelope(event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="Shipment",
                        aggregate_id=uuid.uuid4(), aggregate_version=1, event_type="ShipmentDelivered",
                        event_version=1, payload={"shipment_id": "x"}, occurred_at=None)
    s = _Session()
    first = IntegrationService(s).create_deliveries_from_event(env)
    s.commit()
    assert len(first) == 1
    # Replay the same envelope (same event_id) → idempotent skip
    s2 = _Session()
    second = IntegrationService(s2).create_deliveries_from_event(env)
    s2.commit()
    assert second == []


def test_duplicate_inbound_idempotency_key_single_row():
    svc = _svc()
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.VENDOR)
    key, _ = svc.create_api_key(p.id, name="k")
    r1 = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="k1",
                                      event_type="e", payload={}, signature_valid=True)
    r2 = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="k1",
                                      event_type="e", payload={}, signature_valid=True)
    assert r1.id == r2.id
