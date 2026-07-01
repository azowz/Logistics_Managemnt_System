"""Repository finder tests for the integration domain (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.integration import (
    IntegrationPartner,
    PartnerApiKey,
    WebhookDelivery,
    WebhookSubscription,
)
from app.repositories.integration_repository import (
    InboundIntegrationEventRepository,
    IntegrationPartnerRepository,
    PartnerApiKeyRepository,
    WebhookDeliveryAttemptRepository,
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)
from integrations_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT)


def _partner(s, name=None, status="active"):
    p = IntegrationPartner(id=uuid.uuid4(), tenant_id=_TENANT, name=name or f"P-{uuid.uuid4().hex[:6]}",
                           partner_type="carrier", status=status)
    s.add(p)
    s.flush()
    return p


def test_partner_get_by_name_ignores_soft_deleted():
    s = _Session()
    try:
        p = _partner(s, name="Findable")
        repo = IntegrationPartnerRepository(s)
        assert repo.get_by_name("Findable").id == p.id
        p.soft_delete()
        s.flush()
        assert repo.get_by_name("Findable") is None
        assert repo.get_by_name("Findable", include_deleted=True) is not None
    finally:
        s.rollback()
        s.close()


def test_api_key_find_active_by_prefix():
    s = _Session()
    try:
        p = _partner(s)
        s.add(PartnerApiKey(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="k",
                            key_prefix="pfx001", key_hash="h", status="active"))
        s.add(PartnerApiKey(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="k2",
                            key_prefix="pfx002", key_hash="h", status="revoked"))
        s.flush()
        repo = PartnerApiKeyRepository(s)
        assert repo.find_active_by_prefix("pfx001") is not None
        assert repo.find_active_by_prefix("pfx002") is None  # revoked
        assert len(repo.list_for_partner(p.id)) == 2
    finally:
        s.rollback()
        s.close()


def test_subscription_list_active_for_event_membership():
    s = _Session()
    try:
        p = _partner(s)
        s.add(WebhookSubscription(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="a",
                                  target_url="https://x/a", event_types=["shipment.delivered", "invoice.paid"],
                                  status="active", encrypted_secret="e"))
        s.add(WebhookSubscription(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="b",
                                  target_url="https://x/b", event_types=["claim.settled"],
                                  status="active", encrypted_secret="e"))
        s.add(WebhookSubscription(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="c",
                                  target_url="https://x/c", event_types=["shipment.delivered"],
                                  status="inactive", encrypted_secret="e"))
        s.flush()
        repo = WebhookSubscriptionRepository(s)
        matched = repo.list_active_for_event("shipment.delivered")
        names = {m.name for m in matched}
        assert names == {"a"}  # 'b' doesn't subscribe, 'c' is inactive
    finally:
        s.rollback()
        s.close()


def test_delivery_find_for_source_and_attempt_numbering():
    s = _Session()
    try:
        p = _partner(s)
        sub = WebhookSubscription(id=uuid.uuid4(), tenant_id=_TENANT, partner_id=p.id, name="s",
                                  target_url="https://x/s", event_types=["shipment.delivered"],
                                  status="active", encrypted_secret="e")
        s.add(sub)
        s.flush()
        src = uuid.uuid4()
        d = WebhookDelivery(id=uuid.uuid4(), tenant_id=_TENANT, subscription_id=sub.id, partner_id=p.id,
                            source_event_id=src, source_event_type="ShipmentDelivered",
                            external_event_type="shipment.delivered", status="pending",
                            payload={}, payload_hash="h", signature="sha256=x")
        s.add(d)
        s.flush()
        drepo = WebhookDeliveryRepository(s)
        assert drepo.find_for_source(sub.id, src).id == d.id
        assert drepo.find_for_source(sub.id, uuid.uuid4()) is None
        arepo = WebhookDeliveryAttemptRepository(s)
        assert arepo.next_attempt_number(d.id) == 1
    finally:
        s.rollback()
        s.close()


def test_inbound_find_by_idempotency():
    s = _Session()
    try:
        repo = InboundIntegrationEventRepository(s)
        assert repo.find_by_idempotency(uuid.uuid4(), "nope") is None
    finally:
        s.rollback()
        s.close()
