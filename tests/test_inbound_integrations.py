"""Inbound integration event tests: signature decision + lifecycle (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.models.enums import InboundEventStatus, IntegrationPartnerType
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


def _partner_with_key():
    svc = _svc()
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.VENDOR)
    key, _ = svc.create_api_key(p.id, name="k")
    return p, key


def test_valid_signature_is_accepted():
    p, key = _partner_with_key()
    row = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="i-1",
                                       event_type="order.updated", payload={"x": 1}, signature_valid=True)
    assert row.status == InboundEventStatus.ACCEPTED
    assert row.signature_valid is True and row.received_at is not None


def test_invalid_signature_is_rejected():
    p, key = _partner_with_key()
    row = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="i-2",
                                       event_type="order.updated", payload=None, signature_valid=False)
    assert row.status == InboundEventStatus.REJECTED
    assert row.rejected_at is not None and row.rejection_reason


def test_duplicate_idempotency_key_does_not_double_process():
    p, key = _partner_with_key()
    r1 = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="dup",
                                      event_type="e", payload={"a": 1}, signature_valid=True)
    r2 = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="dup",
                                      event_type="e", payload={"a": 2}, signature_valid=True)
    assert r1.id == r2.id
    assert r2.payload == {"a": 1}  # first write wins; second is a no-op read


def test_process_and_reject_transitions():
    p, key = _partner_with_key()
    row = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="i-3",
                                       event_type="e", payload={}, signature_valid=True)
    processed = _svc().process_inbound_event(row.id)
    assert processed.status == InboundEventStatus.PROCESSED and processed.processed_at is not None

    row2 = _svc().receive_inbound_event(partner_id=p.id, api_key_id=key.id, idempotency_key="i-4",
                                        event_type="e", payload={}, signature_valid=True)
    rejected = _svc().reject_inbound_event(row2.id, reason="manual")
    assert rejected.status == InboundEventStatus.REJECTED and rejected.rejection_reason == "manual"
