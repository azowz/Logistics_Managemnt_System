"""Delivery retry sweep worker tests (SQLite; session_scope monkeypatched)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

import app.integrations.sweep as sweep
from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.events.envelope import EventEnvelope
from app.integrations.delivery import WebhookSendResult
from app.models.enums import IntegrationPartnerType, WebhookDeliveryStatus
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


@pytest.fixture(autouse=True)
def _patch_scope(monkeypatch):
    """Route the sweep's session_scope + tenant discovery at the SQLite test engine."""
    @contextmanager
    def _scope(tenant_id=None):
        s = _Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(sweep, "session_scope", _scope)
    monkeypatch.setattr(sweep, "_tenants_with_due_deliveries", lambda: [_TENANT])
    yield


class _FakeProvider:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = 0

    def send(self, *, target_url, body, headers, timeout_seconds):
        self.calls += 1
        if self.succeed:
            return WebhookSendResult(succeeded=True, http_status_code=200, response_body="ok", duration_ms=1)
        return WebhookSendResult(succeeded=False, http_status_code=500, error_code="http_500",
                                 error_message="err", duration_ms=1)


def _subscribe_and_emit(n_events=1, max_retries=2):
    svc = IntegrationService(_Session())
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    sub, _secret = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                           event_types=["shipment.delivered"], max_retries=max_retries)
    ids = []
    s = _Session()
    isvc = IntegrationService(s)
    for _ in range(n_events):
        created = isvc.create_deliveries_from_event(EventEnvelope(
            event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="Shipment", aggregate_id=uuid.uuid4(),
            aggregate_version=1, event_type="ShipmentDelivered", event_version=1,
            payload={"shipment_id": "x"}, occurred_at=None))
        ids += [d.id for d in created if d.subscription_id == sub.id]
    s.commit()
    s.close()
    return ids


def _status(delivery_id):
    s = _Session()
    try:
        from app.models.integration import WebhookDelivery
        return s.get(WebhookDelivery, delivery_id).status
    finally:
        s.close()


def test_sweep_delivers_due_pending_deliveries():
    ids = _subscribe_and_emit(n_events=2)
    provider = _FakeProvider(succeed=True)
    result = sweep.run_webhook_delivery_sweep(provider=provider)
    assert result.attempted >= 2 and result.delivered >= 2
    for did in ids:
        assert _status(did) == WebhookDeliveryStatus.DELIVERED


def test_sweep_marks_failed_and_schedules_retry():
    ids = _subscribe_and_emit(n_events=1, max_retries=2)
    result = sweep.run_webhook_delivery_sweep(provider=_FakeProvider(succeed=False))
    assert result.failed >= 1
    from app.models.integration import WebhookDelivery
    s = _Session()
    try:
        d = s.get(WebhookDelivery, ids[0])
        assert d.status == WebhookDeliveryStatus.FAILED
        assert d.next_attempt_at is not None  # retry scheduled (backoff)
        assert d.attempt_count == 1
    finally:
        s.close()


def test_sweep_does_not_double_send_delivered():
    ids = _subscribe_and_emit(n_events=1)
    sweep.run_webhook_delivery_sweep(provider=_FakeProvider(succeed=True))
    # second sweep: the delivered row is no longer due → not attempted again
    provider2 = _FakeProvider(succeed=True)
    result2 = sweep.run_webhook_delivery_sweep(provider=provider2)
    assert provider2.calls == 0
    assert _status(ids[0]) == WebhookDeliveryStatus.DELIVERED


def test_sweep_isolates_per_delivery_failure(monkeypatch):
    """One raising delivery must not stop the sweep from processing the rest."""
    ids = _subscribe_and_emit(n_events=2)
    real_attempt = IntegrationService.attempt_delivery
    bad = ids[0]

    def _flaky(self, delivery_id, *, provider=None):
        if delivery_id == bad:
            raise RuntimeError("boom")
        return real_attempt(self, delivery_id, provider=provider)

    monkeypatch.setattr(IntegrationService, "attempt_delivery", _flaky)
    result = sweep.run_webhook_delivery_sweep(provider=_FakeProvider(succeed=True))
    assert result.errors >= 1 and result.delivered >= 1  # the other delivery still went through
