"""Integration tests for the /integrations API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.integrations import router as integrations_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from integrations_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_engine = make_engine()
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)
_ROLE = {"role": UserRole.ADMIN}


def _sess() -> Iterator:
    s = _TestSession()
    try:
        yield s
    finally:
        s.close()


def _user():
    return types.SimpleNamespace(id=_USER, tenant_id=_TENANT, role=_ROLE["role"], is_active=True)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_TestSession, tenant_id=_TENANT, user_id=_USER)


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(integrations_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _ctx():
    with patch("app.services.integration_service.get_current_tenant", return_value=_TENANT), \
         patch("app.services.integration_service.get_current_user_id", return_value=_USER):
        yield


def _make_partner(client, name=None):
    r = client.post("/integrations/partners",
                    json={"name": name or f"P-{uuid.uuid4().hex[:8]}", "partner_type": "carrier"})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_get_partner(client):
    p = _make_partner(client)
    assert p["status"] == "active"
    r = client.get(f"/integrations/partners/{p['id']}")
    assert r.status_code == 200 and r.json()["id"] == p["id"]


def test_list_and_search_partners(client):
    _make_partner(client)
    assert client.get("/integrations/partners").status_code == 200
    assert client.get("/integrations/partners/search?q=P-").status_code == 200


def test_create_api_key_returns_plaintext_once_no_hash(client):
    p = _make_partner(client)
    r = client.post(f"/integrations/partners/{p['id']}/api-keys", json={"name": "primary"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key"].startswith("mesaar_")
    assert "key_hash" not in body
    # listing keys never returns plaintext or hash
    lst = client.get(f"/integrations/partners/{p['id']}/api-keys").json()
    assert lst and "key_hash" not in lst[0] and "api_key" not in lst[0]


def test_create_subscription_returns_secret_once_no_secret_on_read(client):
    p = _make_partner(client)
    r = client.post("/integrations/webhooks/subscriptions", json={
        "partner_id": p["id"], "name": "s", "target_url": "https://ex.test/hook",
        "event_types": ["shipment.delivered"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["secret"].startswith("whsec_")
    assert "encrypted_secret" not in body
    got = client.get(f"/integrations/webhooks/subscriptions/{body['id']}").json()
    assert "secret" not in got and "encrypted_secret" not in got


def test_subscription_http_url_rejected(client):
    p = _make_partner(client)
    r = client.post("/integrations/webhooks/subscriptions", json={
        "partner_id": p["id"], "name": "s", "target_url": "http://ex.test/hook",
        "event_types": ["shipment.delivered"]})
    assert r.status_code in (400, 422)


def test_deliveries_listing_ok(client):
    assert client.get("/integrations/webhooks/deliveries").status_code == 200


def test_rbac_client_forbidden(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/integrations/partners").status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_manager_can_manage_but_not_revoke(client):
    p = _make_partner(client)
    key = client.post(f"/integrations/partners/{p['id']}/api-keys", json={"name": "k"}).json()
    _ROLE["role"] = UserRole.MANAGER
    try:
        # manager can list partners
        assert client.get("/integrations/partners").status_code == 200
        # but cannot revoke a key (ADMIN-only)
        assert client.post(f"/integrations/api-keys/{key['id']}/revoke").status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_admin_can_revoke_key(client):
    p = _make_partner(client)
    key = client.post(f"/integrations/partners/{p['id']}/api-keys", json={"name": "k"}).json()
    r = client.post(f"/integrations/api-keys/{key['id']}/revoke")
    assert r.status_code == 200 and r.json()["status"] == "revoked"


# --- inbound endpoint (partner API-key auth overridden) + auth dependency ---


def _seed_partner_key():
    """Create a partner + api key directly for inbound auth tests; returns (partner_id, key_id, plaintext)."""
    from unittest.mock import patch as _p
    with _p("app.services.integration_service.get_current_tenant", return_value=_TENANT), \
         _p("app.services.integration_service.get_current_user_id", return_value=_USER):
        from app.services.integration_service import IntegrationService
        from app.models.enums import IntegrationPartnerType
        svc = IntegrationService(_TestSession())
        p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.VENDOR)
        key, plaintext = svc.create_api_key(p.id, name="k")
        return p.id, key.id, plaintext


def test_inbound_event_valid_and_invalid_signature(client):
    from app.integrations import crypto
    from app.integrations.auth import AuthenticatedPartner, get_current_api_key_partner
    from app.services.integration_service import ApiKeyAuthContext

    partner_id, key_id, plaintext = _seed_partner_key()
    principal = AuthenticatedPartner(
        context=ApiKeyAuthContext(api_key_id=key_id, partner_id=partner_id, tenant_id=_TENANT),
        api_key=plaintext)
    client.app.dependency_overrides[get_current_api_key_partner] = lambda: principal
    try:
        body = '{"idempotency_key":"evt-1","event_type":"order.updated","payload":{"x":1}}'
        sig = crypto.compute_signature(plaintext, body)
        r = client.post("/integrations/inbound/events", content=body,
                        headers={"X-Mesaar-Signature": sig, "Content-Type": "application/json"})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "accepted" and r.json()["signature_valid"] is True

        # bad signature → rejected (still 201, audited)
        body2 = '{"idempotency_key":"evt-2","event_type":"order.updated","payload":{}}'
        r2 = client.post("/integrations/inbound/events", content=body2,
                         headers={"X-Mesaar-Signature": "sha256=bad", "Content-Type": "application/json"})
        assert r2.status_code == 201 and r2.json()["status"] == "rejected"
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)


def test_auth_dependency_extract_and_reject():
    from unittest.mock import patch
    from fastapi import HTTPException
    import app.integrations.auth as authmod
    from app.services.integration_service import ApiKeyAuthContext

    # malformed / missing header → 401
    for bad in (None, "Token abc", "Bearer "):
        try:
            authmod.get_current_api_key_partner(authorization=bad)
            assert False, "expected 401"
        except HTTPException as e:
            assert e.status_code == 401

    class _Ctx:
        def __enter__(self): return "s"
        def __exit__(self, *a): return False

    ctx = ApiKeyAuthContext(api_key_id=uuid.uuid4(), partner_id=uuid.uuid4(), tenant_id=_TENANT)

    class _StubSvc:
        def __init__(self, _s): pass
        def authenticate_api_key(self, key): return ctx if key == "mesaar_x_good" else None

    # The dependency intentionally binds tenant context (middleware resets it in prod);
    # in a direct unit call we restore it ourselves so no state leaks to other tests.
    from app.db.tenant import set_current_tenant, set_current_user_id
    with patch.object(authmod, "session_scope", lambda *_a, **_k: _Ctx()), \
         patch.object(authmod, "IntegrationService", _StubSvc):
        out = authmod.get_current_api_key_partner(authorization="Bearer mesaar_x_good")
        assert out.context is ctx and out.api_key == "mesaar_x_good"
        try:
            authmod.get_current_api_key_partner(authorization="Bearer mesaar_x_bad")
            assert False
        except HTTPException as e:
            assert e.status_code == 401
    # restore default (unauthenticated) context so unrelated tests see a clean slate
    set_current_tenant(None)
    set_current_user_id(None)


def test_inbound_malformed_body_is_client_error(client):
    from app.integrations.auth import AuthenticatedPartner, get_current_api_key_partner
    from app.services.integration_service import ApiKeyAuthContext
    partner_id, key_id, plaintext = _seed_partner_key()
    principal = AuthenticatedPartner(
        context=ApiKeyAuthContext(api_key_id=key_id, partner_id=partner_id, tenant_id=_TENANT),
        api_key=plaintext)
    client.app.dependency_overrides[get_current_api_key_partner] = lambda: principal
    try:
        # invalid JSON
        r1 = client.post("/integrations/inbound/events", content="{not json",
                         headers={"Content-Type": "application/json"})
        assert r1.status_code in (400, 422)
        # valid JSON but missing required idempotency_key
        r2 = client.post("/integrations/inbound/events", content='{"event_type":"e"}',
                         headers={"Content-Type": "application/json"})
        assert r2.status_code in (400, 422)
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)
