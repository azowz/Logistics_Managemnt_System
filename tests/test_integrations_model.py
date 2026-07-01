"""Model/constraint tests for integration tables (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.integration import (
    IntegrationPartner,
    PartnerApiKey,
    WebhookDelivery,
    WebhookSubscription,
)
from integrations_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT)


def _partner(s):
    p = IntegrationPartner(id=uuid.uuid4(), tenant_id=_TENANT, name=f"P-{uuid.uuid4().hex[:6]}",
                           partner_type="carrier", status="active")
    s.add(p)
    s.flush()
    return p


def test_partner_soft_delete_and_audit_columns():
    s = _Session()
    try:
        p = _partner(s)
        assert p.is_deleted is False and p.version == 1
        p.soft_delete()
        assert p.is_deleted is True
    finally:
        s.rollback()
        s.close()


def test_duplicate_partner_name_per_tenant_rejected():
    s = _Session()
    try:
        s.add(IntegrationPartner(id=uuid.uuid4(), tenant_id=_TENANT, name="SameName",
                                 partner_type="vendor", status="active"))
        s.add(IntegrationPartner(id=uuid.uuid4(), tenant_id=_TENANT, name="SameName",
                                 partner_type="vendor", status="active"))
        with pytest.raises(IntegrityError):
            s.flush()
    finally:
        s.rollback()
        s.close()


def test_webhook_delivery_idempotency_unique_constraint():
    s = _Session()
    try:
        p = _partner(s)
        sub = WebhookSubscription(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="s",
                                  target_url="https://x/y", event_types=["shipment.delivered"],
                                  status="active", encrypted_secret="enc")
        s.add(sub)
        s.flush()
        src = uuid.uuid4()
        common = dict(tenant_id=_TENANT, subscription_id=sub.id, partner_id=p.id, source_event_id=src,
                      source_event_type="ShipmentDelivered", external_event_type="shipment.delivered",
                      status="pending", payload={}, payload_hash="h", signature="sha256=x")
        s.add(WebhookDelivery(id=uuid.uuid4(), **common))
        s.add(WebhookDelivery(id=uuid.uuid4(), **common))
        with pytest.raises(IntegrityError):
            s.flush()
    finally:
        s.rollback()
        s.close()


def test_api_key_prefix_unique_per_tenant():
    s = _Session()
    try:
        p = _partner(s)
        common = dict(tenant_id=_TENANT, partner_id=p.id, key_prefix="abc123", key_hash="h", status="active")
        s.add(PartnerApiKey(id=uuid.uuid4(), name="a", **common))
        s.add(PartnerApiKey(id=uuid.uuid4(), name="b", **common))
        with pytest.raises(IntegrityError):
            s.flush()
    finally:
        s.rollback()
        s.close()
