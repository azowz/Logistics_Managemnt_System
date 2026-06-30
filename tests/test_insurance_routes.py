"""Integration tests for Insurance & Claims API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.claims import router as claims_router
from app.api.routes.insurance import router as insurance_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from insurance_sqlite import make_engine, seed_active_policy, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_POLICY = uuid.uuid4()

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


@pytest.fixture(scope="module")
def client():
    seed_tenant_user(_TestSession, tenant_id=_TENANT, user_id=_USER)
    seed_active_policy(_TestSession, tenant_id=_TENANT, policy_id=_POLICY)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(insurance_router)
    app.include_router(claims_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_ctx():
    with (
        patch("app.services.insurance_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.insurance_service.get_current_user_id", return_value=_USER),
        patch("app.services.insurance_service.EventStoreRepository", autospec=True) as M1,
        patch("app.services.claims_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.claims_service.get_current_user_id", return_value=_USER),
        patch("app.services.claims_service.EventStoreRepository", autospec=True) as M2,
    ):
        for M in (M1, M2):
            M.return_value.next_aggregate_version.return_value = 1
            M.return_value.append.return_value = None
        yield


# --- policies -------------------------------------------------------------


def _create_policy(client, **ov) -> dict:
    body = {"policy_type": "cargo", "covers_shipment": True}
    body.update(ov)
    r = client.post("/insurance/policies", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_policy_lifecycle(client):
    pid = _create_policy(client)["id"]
    assert client.post(f"/insurance/policies/{pid}/activate").json()["status"] == "active"
    assert client.post(f"/insurance/policies/{pid}/suspend").json()["status"] == "suspended"
    assert client.post(f"/insurance/policies/{pid}/cancel").json()["status"] == "cancelled"


def test_policy_invalid_transition_409(client):
    pid = _create_policy(client)["id"]
    assert client.post(f"/insurance/policies/{pid}/suspend").status_code == 409


def test_policy_search_before_id(client):
    _create_policy(client, policy_number="POL-SRCH")
    r = client.get("/insurance/policies/search?q=POL-SRCH")
    assert r.status_code == 200
    assert any(p["policy_number"] == "POL-SRCH" for p in r.json()["items"])


def test_policy_duplicate_409(client):
    _create_policy(client, policy_number="POL-DUP")
    r = client.post("/insurance/policies", json={"policy_type": "cargo", "policy_number": "POL-DUP"})
    assert r.status_code == 409


def test_coverage_rule_crud(client):
    pid = _create_policy(client)["id"]
    r = client.post("/insurance/coverage-rules", json={"policy_id": pid, "coverage_type": "shipment_loss"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert isinstance(client.get(f"/insurance/coverage-rules?policy_id={pid}").json(), list)
    upd = client.patch(f"/insurance/coverage-rules/{rid}", json={"active": False})
    assert upd.status_code == 200 and upd.json()["active"] is False


# --- claims ---------------------------------------------------------------


def _create_claim(client, **ov) -> dict:
    body = {"claim_type": "shipment_loss", "policy_id": str(_POLICY), "claimed_amount": 1000}
    body.update(ov)
    r = client.post("/claims", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_claim_full_lifecycle(client):
    cid = _create_claim(client)["id"]
    assert client.post(f"/claims/{cid}/review").json()["status"] == "under_review"
    approved = client.post(f"/claims/{cid}/approve", json={"approved_amount": 800})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert approved.json()["approved_amount"] == "800.00"
    settled = client.post(f"/claims/{cid}/settle", json={"settlement_notes": "paid in full"})
    assert settled.json()["status"] == "settled"
    assert client.post(f"/claims/{cid}/close").json()["status"] == "closed"
    assert client.post(f"/claims/{cid}/reopen", json={}).json()["status"] == "under_review"


def test_claim_reject_requires_reason_422(client):
    cid = _create_claim(client)["id"]
    client.post(f"/claims/{cid}/review")
    assert client.post(f"/claims/{cid}/reject", json={}).status_code == 422  # schema requires reason


def test_claim_reject_then_close(client):
    cid = _create_claim(client)["id"]
    client.post(f"/claims/{cid}/review")
    assert client.post(f"/claims/{cid}/reject", json={"reason": "out of coverage"}).json()["status"] == "rejected"
    assert client.post(f"/claims/{cid}/close").json()["status"] == "closed"


def test_claim_approve_exceeds_claimed_422(client):
    cid = _create_claim(client, claimed_amount=100)["id"]
    client.post(f"/claims/{cid}/review")
    assert client.post(f"/claims/{cid}/approve", json={"approved_amount": 500}).status_code == 422


def test_claim_search_before_id(client):
    _create_claim(client, claim_number="CLM-SRCH")
    r = client.get("/claims/search?q=CLM-SRCH")
    assert r.status_code == 200
    assert any(c["claim_number"] == "CLM-SRCH" for c in r.json()["items"])


def test_claim_invalid_sort_422(client):
    assert client.get("/claims?sort_by=ssn").status_code == 422


def test_damage_report_and_liability(client):
    cid = _create_claim(client)["id"]
    dr = client.post(f"/claims/{cid}/damage-reports", json={"damage_type": "cargo_damage", "severity": "high", "estimated_cost": 250})
    assert dr.status_code == 201
    assert len(client.get(f"/claims/{cid}/damage-reports").json()) == 1
    lr = client.post(f"/claims/{cid}/liability-records", json={"responsible_party_type": "carrier", "liability_percentage": 60})
    assert lr.status_code == 201
    assert len(client.get(f"/claims/{cid}/liability-records").json()) == 1


def test_liability_exceeds_100_422(client):
    cid = _create_claim(client)["id"]
    client.post(f"/claims/{cid}/liability-records", json={"responsible_party_type": "carrier", "liability_percentage": 80})
    r = client.post(f"/claims/{cid}/liability-records", json={"responsible_party_type": "driver", "liability_percentage": 40})
    assert r.status_code == 422


def test_claim_delete_restore(client):
    cid = _create_claim(client)["id"]
    assert client.delete(f"/claims/{cid}").status_code == 204
    assert client.get(f"/claims/{cid}").status_code == 404
    assert client.post(f"/claims/{cid}/restore").status_code == 200


# --- RBAC -----------------------------------------------------------------


def test_rbac_client_cannot_create_claim(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.post("/claims", json={"claim_type": "shipment_loss"}).status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_client_can_read_claims(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/claims").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN
