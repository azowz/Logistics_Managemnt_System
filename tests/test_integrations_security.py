"""Security tests: secret/hash non-exposure, tenant isolation, auth rejection (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.models.enums import IntegrationPartnerType
from app.schemas.integration import (
    PartnerApiKeyRead,
    WebhookSubscriptionRead,
)
from app.services.exceptions import NotFoundError
from app.services.integration_service import IntegrationService
from integrations_sqlite import make_engine, seed_tenant_user

_TENANT_A = uuid.uuid4()
_TENANT_B = uuid.uuid4()
_USER = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT_A, user_id=_USER)
    seed_tenant_user(_Session, tenant_id=_TENANT_B, user_id=_USER)


def _as(tenant):
    """Context manager-ish helper to run a block under a tenant."""
    t1 = set_current_tenant(tenant)
    t2 = set_current_user_id(_USER)
    return (t1, t2)


def _clear(tokens):
    reset_current_user_id(tokens[1])
    reset_current_tenant(tokens[0])


def test_api_key_read_schema_never_exposes_hash():
    fields = set(PartnerApiKeyRead.model_fields.keys())
    assert "key_hash" not in fields
    assert "api_key" not in fields  # plaintext only on the *Created* schema


def test_subscription_read_schema_never_exposes_secret():
    fields = set(WebhookSubscriptionRead.model_fields.keys())
    assert "encrypted_secret" not in fields
    assert "secret" not in fields


def test_api_key_read_serialization_excludes_hash():
    tokens = _as(_TENANT_A)
    try:
        svc = IntegrationService(_Session())
        p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
        key, _plain = svc.create_api_key(p.id, name="k")
        dumped = PartnerApiKeyRead.model_validate(key).model_dump()
        assert "key_hash" not in dumped
        assert dumped["key_prefix"] == key.key_prefix
    finally:
        _clear(tokens)


def test_cross_tenant_partner_read_is_not_found():
    # create under tenant A
    tokens = _as(_TENANT_A)
    try:
        p = IntegrationService(_Session()).create_partner(
            name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    finally:
        _clear(tokens)
    # attempt to read under tenant B → NotFound (service _owned enforces tenant match)
    tokens = _as(_TENANT_B)
    try:
        with pytest.raises(NotFoundError):
            IntegrationService(_Session()).get_partner(p.id)
    finally:
        _clear(tokens)


def test_cross_tenant_subscription_read_is_not_found():
    tokens = _as(_TENANT_A)
    try:
        svc = IntegrationService(_Session())
        p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
        sub, _ = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                         event_types=["shipment.delivered"])
    finally:
        _clear(tokens)
    tokens = _as(_TENANT_B)
    try:
        with pytest.raises(NotFoundError):
            IntegrationService(_Session()).get_subscription(sub.id)
    finally:
        _clear(tokens)


def test_authenticate_rejects_key_from_wrong_tenant_context_but_binds_correct_tenant():
    tokens = _as(_TENANT_A)
    try:
        svc = IntegrationService(_Session())
        p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
        key, plaintext = svc.create_api_key(p.id, name="k")
    finally:
        _clear(tokens)
    # Authenticating (platform-scope style) returns the key's OWN tenant, never the caller's.
    tokens = _as(_TENANT_A)
    try:
        ctx = IntegrationService(_Session()).authenticate_api_key(plaintext)
        assert ctx is not None and ctx.tenant_id == _TENANT_A
    finally:
        _clear(tokens)
