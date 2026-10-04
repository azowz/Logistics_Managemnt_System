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


# --- inbound endpoint: scope + replay-window + signature (Sprint 14) ---------

import time as _time
import types as _types

from app.integrations.auth import AuthenticatedPartner, SCOPE_INBOUND_WRITE, get_current_api_key_partner
from app.integrations import crypto as _crypto
from app.services.integration_service import ApiKeyAuthContext


def _seed_partner_key(scopes=None, allowed_ips=None):
    """Create a partner + api key directly; returns (partner_id, key_id, plaintext)."""
    from unittest.mock import patch as _p
    with _p("app.services.integration_service.get_current_tenant", return_value=_TENANT), \
         _p("app.services.integration_service.get_current_user_id", return_value=_USER):
        from app.services.integration_service import IntegrationService
        from app.models.enums import IntegrationPartnerType
        svc = IntegrationService(_TestSession())
        p = svc.create_partner(name=f"P-{uuid.uuid4().hex[:8]}", partner_type=IntegrationPartnerType.VENDOR)
        key, plaintext = svc.create_api_key(p.id, name="k", scopes=scopes, allowed_ips=allowed_ips)
        return p.id, key.id, plaintext


def _principal(partner_id, key_id, plaintext, *, scopes=(SCOPE_INBOUND_WRITE,)):
    return AuthenticatedPartner(
        context=ApiKeyAuthContext(api_key_id=key_id, partner_id=partner_id, tenant_id=_TENANT, scopes=tuple(scopes)),
        api_key=plaintext)


def _override(principal):
    client_fixture = None  # set by caller
    return principal


def test_inbound_event_valid_and_invalid_signature(client):
    partner_id, key_id, plaintext = _seed_partner_key(scopes=[SCOPE_INBOUND_WRITE])
    client.app.dependency_overrides[get_current_api_key_partner] = lambda: _principal(partner_id, key_id, plaintext)
    try:
        ts = str(int(_time.time()))
        body = '{"idempotency_key":"evt-1","event_type":"order.updated","payload":{"x":1}}'
        sig = _crypto.compute_signature(plaintext, body, timestamp=ts)
        r = client.post("/integrations/inbound/events", content=body,
                        headers={"X-Mesaar-Signature": sig, "X-Mesaar-Timestamp": ts, "Content-Type": "application/json"})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "accepted" and r.json()["signature_valid"] is True

        body2 = '{"idempotency_key":"evt-2","event_type":"order.updated","payload":{}}'
        r2 = client.post("/integrations/inbound/events", content=body2,
                         headers={"X-Mesaar-Signature": "sha256=bad", "X-Mesaar-Timestamp": ts,
                                  "Content-Type": "application/json"})
        assert r2.status_code == 201 and r2.json()["status"] == "rejected"
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)


def test_inbound_missing_scope_forbidden(client):
    partner_id, key_id, plaintext = _seed_partner_key(scopes=[])
    # principal without the inbound scope
    client.app.dependency_overrides[get_current_api_key_partner] = lambda: _principal(
        partner_id, key_id, plaintext, scopes=())
    try:
        ts = str(int(_time.time()))
        body = '{"idempotency_key":"ns-1","event_type":"e","payload":{}}'
        sig = _crypto.compute_signature(plaintext, body, timestamp=ts)
        r = client.post("/integrations/inbound/events", content=body,
                        headers={"X-Mesaar-Signature": sig, "X-Mesaar-Timestamp": ts})
        assert r.status_code == 403
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)


def test_inbound_replay_window(client):
    partner_id, key_id, plaintext = _seed_partner_key(scopes=[SCOPE_INBOUND_WRITE])
    client.app.dependency_overrides[get_current_api_key_partner] = lambda: _principal(partner_id, key_id, plaintext)
    try:
        body = '{"idempotency_key":"rw-1","event_type":"e","payload":{}}'
        # missing timestamp → 4xx
        assert client.post("/integrations/inbound/events", content=body,
                           headers={"X-Mesaar-Signature": "sha256=x"}).status_code in (400, 422)
        # malformed timestamp → 4xx
        assert client.post("/integrations/inbound/events", content=body,
                           headers={"X-Mesaar-Signature": "sha256=x", "X-Mesaar-Timestamp": "abc"}
                           ).status_code in (400, 422)
        # stale timestamp → 401
        old = str(int(_time.time()) - 4000)
        assert client.post("/integrations/inbound/events", content=body,
                           headers={"X-Mesaar-Signature": "sha256=x", "X-Mesaar-Timestamp": old}
                           ).status_code == 401
        # far-future timestamp → 401
        future = str(int(_time.time()) + 4000)
        assert client.post("/integrations/inbound/events", content=body,
                           headers={"X-Mesaar-Signature": "sha256=x", "X-Mesaar-Timestamp": future}
                           ).status_code == 401
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)


def test_inbound_malformed_body_is_client_error(client):
    partner_id, key_id, plaintext = _seed_partner_key(scopes=[SCOPE_INBOUND_WRITE])
    client.app.dependency_overrides[get_current_api_key_partner] = lambda: _principal(partner_id, key_id, plaintext)
    try:
        ts = str(int(_time.time()))
        h = {"X-Mesaar-Signature": "sha256=x", "X-Mesaar-Timestamp": ts, "Content-Type": "application/json"}
        assert client.post("/integrations/inbound/events", content="{not json", headers=h).status_code in (400, 422)
        assert client.post("/integrations/inbound/events", content='{"event_type":"e"}', headers=h
                           ).status_code in (400, 422)
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)


def test_inbound_rate_limit_returns_429_and_is_api_key_scoped(client):
    from app.integrations.policies import (
        InMemoryRateLimitBackend, RateLimitPolicy, get_inbound_rate_limiter, set_inbound_rate_limiter,
    )
    original = get_inbound_rate_limiter()
    set_inbound_rate_limiter(RateLimitPolicy(limit=2, window_seconds=60, backend=InMemoryRateLimitBackend()))
    partner_id, key_a, plain_a = _seed_partner_key(scopes=[SCOPE_INBOUND_WRITE])
    _pb, key_b, _plain_b = _seed_partner_key(scopes=[SCOPE_INBOUND_WRITE])

    def _post(principal, n):
        ts = str(int(_time.time()))
        body = f'{{"idempotency_key":"rl-{n}","event_type":"e","payload":{{}}}}'
        sig = _crypto.compute_signature(principal.api_key, body, timestamp=ts)
        client.app.dependency_overrides[get_current_api_key_partner] = lambda: principal
        return client.post("/integrations/inbound/events", content=body,
                           headers={"X-Mesaar-Signature": sig, "X-Mesaar-Timestamp": ts,
                                    "Content-Type": "application/json"})

    pa = _principal(partner_id, key_a, plain_a)
    pb = _principal(partner_id, key_b, "x")
    try:
        assert _post(pa, 1).status_code == 201
        assert _post(pa, 2).status_code == 201
        r = _post(pa, 3)
        assert r.status_code == 429 and "Retry-After" in r.headers
        # a different api key has its own bucket
        assert _post(pb, 99).status_code == 201
    finally:
        client.app.dependency_overrides.pop(get_current_api_key_partner, None)
        set_inbound_rate_limiter(original)


def _fake_request(host="1.2.3.4"):
    return _types.SimpleNamespace(client=_types.SimpleNamespace(host=host))


def test_auth_dependency_extract_reject_and_ip_enforcement():
    from unittest.mock import patch
    from fastapi import HTTPException
    import app.integrations.auth as authmod

    req = _fake_request()
    for bad in (None, "Token abc", "Bearer "):
        try:
            authmod.get_current_api_key_partner(req, authorization=bad)
            assert False, "expected 401"
        except HTTPException as e:
            assert e.status_code == 401

    class _Ctx:
        def __enter__(self): return "s"
        def __exit__(self, *a): return False

    good = ApiKeyAuthContext(api_key_id=uuid.uuid4(), partner_id=uuid.uuid4(), tenant_id=_TENANT,
                             scopes=(SCOPE_INBOUND_WRITE,), allowed_ips=("10.0.0.0/24",))

    class _StubSvc:
        def __init__(self, _s): pass
        def authenticate_api_key(self, key): return good if key == "mesaar_x_good" else None

    from app.db.tenant import set_current_tenant, set_current_user_id
    with patch.object(authmod, "session_scope", lambda *_a, **_k: _Ctx()), \
         patch.object(authmod, "IntegrationService", _StubSvc):
        # bad key → 401
        try:
            authmod.get_current_api_key_partner(req, authorization="Bearer mesaar_x_bad")
            assert False
        except HTTPException as e:
            assert e.status_code == 401
        # disallowed IP → 403
        try:
            authmod.get_current_api_key_partner(_fake_request("1.2.3.4"), authorization="Bearer mesaar_x_good")
            assert False
        except HTTPException as e:
            assert e.status_code == 403
        # allowed IP → ok
        out = authmod.get_current_api_key_partner(_fake_request("10.0.0.9"), authorization="Bearer mesaar_x_good")
        assert out.context is good
    set_current_tenant(None)
    set_current_user_id(None)
