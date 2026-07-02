"""Secret-encryption provider boundary tests (Sprint 14)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.tenant import reset_current_tenant, reset_current_user_id, set_current_tenant, set_current_user_id
from app.integrations.encryption import (
    LocalFernetSecretProvider,
    get_secret_provider,
    set_secret_provider,
)
from app.models.enums import IntegrationPartnerType
from app.models.integration import WebhookSubscription
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


def test_provider_encrypt_decrypt_roundtrip_and_metadata():
    p = LocalFernetSecretProvider()
    enc = p.encrypt("whsec_xyz")
    assert enc != "whsec_xyz"
    assert p.decrypt(enc) == "whsec_xyz"
    assert p.provider_name == "local_fernet"
    assert p.key_id.startswith("fernet:")


def test_decrypt_failure_returns_none():
    assert LocalFernetSecretProvider().decrypt("not-a-token") is None


def test_subscription_records_encryption_metadata():
    svc = IntegrationService(_Session())
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    sub, secret = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                          event_types=["shipment.delivered"])
    assert sub.encryption_provider == "local_fernet"
    assert sub.encryption_key_id and sub.encryption_key_id.startswith("fernet:")
    assert get_secret_provider().decrypt(sub.encrypted_secret) == secret


def test_rotation_updates_metadata_and_secret():
    svc = IntegrationService(_Session())
    p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
    sub, s1 = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                      event_types=["shipment.delivered"])
    sub2, s2 = svc.rotate_subscription_secret(sub.id)
    assert s2 != s1
    assert sub2.encryption_provider == "local_fernet" and sub2.encryption_key_id
    assert get_secret_provider().decrypt(sub2.encrypted_secret) == s2


def test_read_schema_never_leaks_secret_or_ciphertext():
    from app.schemas.integration import WebhookSubscriptionRead
    fields = set(WebhookSubscriptionRead.model_fields.keys())
    assert "encrypted_secret" not in fields and "secret" not in fields
    # metadata (non-secret) is fine to expose
    assert "encryption_provider" in fields and "encryption_key_id" in fields


def test_swappable_provider_boundary():
    """A custom provider can be swapped in without touching the service."""
    class _StubProvider:
        provider_name = "stub"

        @property
        def key_id(self):
            return "stub:v1"

        def encrypt(self, plaintext):
            return "ENC(" + plaintext + ")"

        def decrypt(self, ciphertext):
            return ciphertext[4:-1] if ciphertext.startswith("ENC(") else None

    original = get_secret_provider()
    set_secret_provider(_StubProvider())
    try:
        svc = IntegrationService(_Session())
        p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.CARRIER)
        sub, secret = svc.create_subscription(p.id, name="s", target_url="https://ex.test/hook",
                                              event_types=["shipment.delivered"])
        assert sub.encryption_provider == "stub" and sub.encryption_key_id == "stub:v1"
        assert sub.encrypted_secret == f"ENC({secret})"
    finally:
        set_secret_provider(original)
