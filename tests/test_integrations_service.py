"""Behavioral tests for IntegrationService (SQLite + real tenant context)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.common.datetime import utcnow
from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.integrations import crypto
from app.models.enums import (
    ApiKeyStatus,
    IntegrationPartnerStatus,
    IntegrationPartnerType,
    WebhookSubscriptionStatus,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
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


def _partner(name=None):
    return _svc().create_partner(name=name or f"P-{uuid.uuid4().hex[:8]}",
                                 partner_type=IntegrationPartnerType.CARRIER)


# --- partners ---


def test_partner_lifecycle():
    svc = _svc()
    p = svc.create_partner(name="Acme Carrier", partner_type=IntegrationPartnerType.CARRIER,
                           contact_email="ops@acme.test")
    assert p.status == IntegrationPartnerStatus.ACTIVE
    p = svc.suspend_partner(p.id)
    assert p.status == IntegrationPartnerStatus.SUSPENDED
    p = svc.activate_partner(p.id)
    assert p.status == IntegrationPartnerStatus.ACTIVE
    p = svc.update_partner(p.id, contact_phone="+100")
    assert p.contact_phone == "+100"


def test_partner_duplicate_name_conflict():
    _svc().create_partner(name="DupPartner", partner_type=IntegrationPartnerType.VENDOR)
    with pytest.raises(ConflictError):
        _svc().create_partner(name="DupPartner", partner_type=IntegrationPartnerType.VENDOR)


def test_partner_soft_delete_hides_it():
    p = _partner()
    _svc().delete_partner(p.id)
    with pytest.raises(NotFoundError):
        _svc().get_partner(p.id)


# --- api keys ---


def test_api_key_create_returns_plaintext_once_and_stores_hash():
    p = _partner()
    key, plaintext = _svc().create_api_key(p.id, name="primary")
    assert plaintext.startswith("mesaar_")
    assert key.key_hash != plaintext
    assert crypto.verify_api_key(plaintext, key.key_hash)
    assert key.status == ApiKeyStatus.ACTIVE


def test_authenticate_api_key_success_and_failure_modes():
    p = _partner()
    key, plaintext = _svc().create_api_key(p.id, name="k")
    ctx = _svc().authenticate_api_key(plaintext)
    assert ctx is not None and ctx.partner_id == p.id and ctx.tenant_id == _TENANT
    assert _svc().authenticate_api_key("mesaar_deadbeef_bogus") is None
    assert _svc().authenticate_api_key("garbage") is None


def test_revoked_key_cannot_authenticate():
    p = _partner()
    key, plaintext = _svc().create_api_key(p.id, name="k")
    _svc().revoke_api_key(key.id)
    assert _svc().authenticate_api_key(plaintext) is None


def test_expired_key_cannot_authenticate():
    p = _partner()
    key, plaintext = _svc().create_api_key(p.id, name="k", expires_at=utcnow() - timedelta(hours=1))
    assert _svc().authenticate_api_key(plaintext) is None


def test_suspended_partner_key_cannot_authenticate():
    p = _partner()
    key, plaintext = _svc().create_api_key(p.id, name="k")
    _svc().suspend_partner(p.id)
    assert _svc().authenticate_api_key(plaintext) is None


def test_rotate_api_key_revokes_old_issues_new():
    p = _partner()
    key, old_plain = _svc().create_api_key(p.id, name="k")
    new, new_plain = _svc().rotate_api_key(key.id)
    assert new.id != key.id and new_plain != old_plain
    # old no longer authenticates; new does
    assert _svc().authenticate_api_key(old_plain) is None
    assert _svc().authenticate_api_key(new_plain) is not None


# --- subscriptions ---


def test_subscription_create_returns_secret_once_and_encrypts_at_rest():
    p = _partner()
    sub, secret = _svc().create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                             event_types=["shipment.delivered"])
    assert secret.startswith("whsec_")
    assert sub.encrypted_secret != secret
    assert crypto.decrypt_secret(sub.encrypted_secret) == secret
    assert sub.status == WebhookSubscriptionStatus.ACTIVE


def test_subscription_rejects_http_and_unknown_event():
    p = _partner()
    with pytest.raises(ValidationError):
        _svc().create_subscription(p.id, name="s", target_url="http://ex.test/hook",
                                   event_types=["shipment.delivered"])
    with pytest.raises(ValidationError):
        _svc().create_subscription(p.id, name="s2", target_url="https://ex.test/hook",
                                   event_types=["not.a.real.event"])


def test_subscription_rejects_empty_event_types():
    p = _partner()
    with pytest.raises(ValidationError):
        _svc().create_subscription(p.id, name="s", target_url="https://ex.test/hook", event_types=[])


def test_subscription_lifecycle_and_secret_rotation():
    p = _partner()
    sub, secret1 = _svc().create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                              event_types=["shipment.delivered"])
    sub = _svc().deactivate_subscription(sub.id)
    assert sub.status == WebhookSubscriptionStatus.INACTIVE
    sub = _svc().activate_subscription(sub.id)
    assert sub.status == WebhookSubscriptionStatus.ACTIVE
    sub2, secret2 = _svc().rotate_subscription_secret(sub.id)
    assert secret2 != secret1 and crypto.decrypt_secret(sub2.encrypted_secret) == secret2


def test_cannot_subscribe_for_suspended_partner():
    p = _partner()
    _svc().suspend_partner(p.id)
    with pytest.raises(ValidationError):
        _svc().create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                   event_types=["shipment.delivered"])


# --- policies (URL/event validation + rate limiting) ---


def test_policy_validate_target_url_and_events():
    from app.integrations.policies import validate_target_url, validate_event_types
    assert validate_target_url("https://ex.test/h") == "https://ex.test/h"
    assert validate_target_url("http://localhost/h", allow_insecure=True)
    with pytest.raises(ValidationError):
        validate_target_url("ftp://ex.test/h")
    with pytest.raises(ValidationError):
        validate_target_url("https://")  # no host
    assert validate_event_types(["shipment.delivered", "shipment.delivered"]) == ["shipment.delivered"]
    with pytest.raises(ValidationError):
        validate_event_types([])
    with pytest.raises(ValidationError):
        validate_event_types(["bogus.event"])


def test_rate_limit_policy_allows_then_blocks_then_resets():
    from app.integrations.policies import RateLimitPolicy, InMemoryRateLimitBackend
    rl = RateLimitPolicy(limit=2, window_seconds=60, backend=InMemoryRateLimitBackend())
    d1 = rl.check("tenant:key", now=1000.0)
    d2 = rl.check("tenant:key", now=1001.0)
    d3 = rl.check("tenant:key", now=1002.0)
    assert d1.allowed and d2.allowed and not d3.allowed
    assert d3.retry_after_seconds >= 1 and d3.remaining == 0
    # next window resets the counter
    assert rl.check("tenant:key", now=1061.0).allowed
    with pytest.raises(ValueError):
        RateLimitPolicy(limit=0)
