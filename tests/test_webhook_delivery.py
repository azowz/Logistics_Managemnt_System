"""Outbound webhook delivery tests: consumer fan-out + attempt/retry/cancel (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.events.envelope import EventEnvelope
from app.integrations.delivery import WebhookSendResult
from app.models.enums import IntegrationPartnerType, WebhookDeliveryStatus
from app.services.exceptions import ValidationError
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


class _FakeProvider:
    name = "fake"

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = []

    def send(self, *, target_url, body, headers, timeout_seconds):
        self.calls.append({"url": target_url, "body": body, "headers": headers})
        if self.succeed:
            return WebhookSendResult(succeeded=True, http_status_code=200, response_body="ok", duration_ms=3)
        return WebhookSendResult(succeeded=False, http_status_code=500, error_code="http_error",
                                 error_message="boom", duration_ms=3)


def _svc():
    return IntegrationService(_Session())


def _subscribed_partner(events=("shipment.delivered",), max_retries=2):
    svc = _svc()
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    sub, secret = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                          event_types=list(events), max_retries=max_retries)
    return p, sub, secret


def _envelope(event_type="ShipmentDelivered", payload=None):
    return EventEnvelope(
        event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="Shipment", aggregate_id=uuid.uuid4(),
        aggregate_version=1, event_type=event_type, event_version=1,
        payload=payload or {"shipment_id": "s1", "status": "delivered", "tenant_id": str(_TENANT)},
        occurred_at=None,
    )


def _create_delivery():
    _p, sub, _secret = _subscribed_partner()
    s = _Session()
    svc = IntegrationService(s)
    created = svc.create_deliveries_from_event(_envelope())
    s.commit()
    s.close()
    # The in-memory DB accumulates subscriptions across tests; isolate ours.
    mine = [d for d in created if d.subscription_id == sub.id]
    assert len(mine) == 1
    return mine[0].id


def test_consumer_creates_sanitized_signed_delivery():
    _p, sub, secret = _subscribed_partner()
    s = _Session()
    created = IntegrationService(s).create_deliveries_from_event(_envelope())
    s.commit()
    d = next(x for x in created if x.subscription_id == sub.id)
    assert d.status == WebhookDeliveryStatus.PENDING
    assert d.external_event_type == "shipment.delivered"
    # payload is sanitized: internal tenant_id stripped, whitelisted data kept
    assert "tenant_id" not in d.payload["data"]
    assert d.payload["data"]["shipment_id"] == "s1"
    assert d.signature.startswith("sha256=")
    s.close()


def test_unmapped_event_creates_nothing():
    _subscribed_partner()
    s = _Session()
    created = IntegrationService(s).create_deliveries_from_event(_envelope("SomethingInternal"))
    s.commit()
    assert created == []
    s.close()


def test_inactive_subscription_receives_nothing():
    svc = _svc()
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    sub, _ = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                     event_types=["shipment.delivered"])
    svc.deactivate_subscription(sub.id)
    s = _Session()
    created = IntegrationService(s).create_deliveries_from_event(_envelope())
    s.commit()
    # the deactivated subscription must not receive a delivery (others may)
    assert not any(d.subscription_id == sub.id for d in created)
    s.close()


def test_attempt_delivery_success():
    did = _create_delivery()
    provider = _FakeProvider(succeed=True)
    d = _svc().attempt_delivery(did, provider=provider)
    assert d.status == WebhookDeliveryStatus.DELIVERED
    assert d.delivered_at is not None and d.attempt_count == 1
    assert len(provider.calls) == 1
    assert provider.calls[0]["headers"]["X-Mesaar-Signature"].startswith("sha256=")


def test_attempt_delivery_failure_then_retry_success():
    did = _create_delivery()
    d = _svc().attempt_delivery(did, provider=_FakeProvider(succeed=False))
    assert d.status == WebhookDeliveryStatus.FAILED and d.last_error
    # retry with a succeeding provider
    d = _svc().retry_delivery(did, provider=_FakeProvider(succeed=True))
    assert d.status == WebhookDeliveryStatus.DELIVERED and d.attempt_count == 2
    attempts = _svc().list_delivery_attempts(did)
    assert len(attempts) == 2


def test_default_no_network_provider_never_succeeds():
    did = _create_delivery()
    d = _svc().attempt_delivery(did)  # default NoNetworkWebhookProvider
    assert d.status == WebhookDeliveryStatus.FAILED
    attempts = _svc().list_delivery_attempts(did)
    assert attempts[-1].status.value == "skipped"  # provider_not_configured → skipped attempt


def test_delivered_cannot_be_retried_or_cancelled():
    did = _create_delivery()
    _svc().attempt_delivery(did, provider=_FakeProvider(succeed=True))
    with pytest.raises(ValidationError):
        _svc().retry_delivery(did, provider=_FakeProvider(succeed=True))
    with pytest.raises(ValidationError):
        _svc().cancel_delivery(did)


def test_cancel_then_cannot_retry():
    did = _create_delivery()
    d = _svc().cancel_delivery(did)
    assert d.status == WebhookDeliveryStatus.CANCELLED
    with pytest.raises(ValidationError):
        _svc().retry_delivery(did, provider=_FakeProvider(succeed=True))
