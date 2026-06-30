"""Integration tests for Compliance API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.compliance import router as compliance_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from compliance_sqlite import make_engine, seed_shipment_with_equipment, seed_tenant_user

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


@pytest.fixture(scope="module")
def client():
    seed_tenant_user(_TestSession, tenant_id=_TENANT, user_id=_USER)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(compliance_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_ctx():
    with (
        patch("app.services.compliance_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.compliance_service.get_current_user_id", return_value=_USER),
        patch("app.services.compliance_service.EventStoreRepository", autospec=True) as M,
    ):
        inst = M.return_value
        inst.next_aggregate_version.return_value = 1
        inst.append.return_value = None
        yield


def _create_permit(client, **ov) -> dict:
    body = {"permit_type": "oversize"}
    body.update(ov)
    r = client.post("/compliance/permits", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- permits --------------------------------------------------------------


def test_create_permit_201(client):
    body = _create_permit(client, permit_number="PMT-A1")
    assert body["permit_number"] == "PMT-A1"
    assert body["status"] == "draft"


def test_permit_duplicate_409(client):
    _create_permit(client, permit_number="PMT-DUP")
    r = client.post("/compliance/permits", json={"permit_type": "oversize", "permit_number": "PMT-DUP"})
    assert r.status_code == 409


def test_permit_lifecycle(client):
    pid = _create_permit(client)["id"]
    assert client.post(f"/compliance/permits/{pid}/submit").json()["status"] == "submitted"
    assert client.post(f"/compliance/permits/{pid}/review").json()["status"] == "under_review"
    assert client.post(f"/compliance/permits/{pid}/approve", json={}).json()["status"] == "approved"
    assert client.post(f"/compliance/permits/{pid}/activate").json()["status"] == "active"
    assert client.post(f"/compliance/permits/{pid}/expire").json()["status"] == "expired"


def test_permit_invalid_transition_409(client):
    pid = _create_permit(client)["id"]
    assert client.post(f"/compliance/permits/{pid}/activate").status_code == 409  # draft→active


def test_permit_search_before_id(client):
    _create_permit(client, permit_number="PMT-SRCH")
    r = client.get("/compliance/permits/search?q=PMT-SRCH")
    assert r.status_code == 200
    assert any(p["permit_number"] == "PMT-SRCH" for p in r.json()["items"])


def test_permit_get_and_list(client):
    pid = _create_permit(client)["id"]
    assert client.get(f"/compliance/permits/{pid}").json()["id"] == pid
    assert {"items", "total"} <= client.get("/compliance/permits").json().keys()


def test_permit_invalid_sort_422(client):
    assert client.get("/compliance/permits?sort_by=ssn").status_code == 422


# --- escorts / restrictions / certs ---------------------------------------


def test_escort_create_schedule_cancel(client):
    r = client.post("/compliance/escorts", json={"escort_type": "police_escort"})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert client.post(f"/compliance/escorts/{eid}/schedule", json={}).json()["status"] == "scheduled"
    assert client.post(f"/compliance/escorts/{eid}/cancel").json()["status"] == "cancelled"


def test_route_restriction_create_list_update(client):
    r = client.post("/compliance/route-restrictions",
                    json={"restriction_type": "height_limit", "region": "Riyadh", "max_height": 4.5})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert isinstance(client.get("/compliance/route-restrictions").json(), list)
    upd = client.patch(f"/compliance/route-restrictions/{rid}", json={"active": False})
    assert upd.status_code == 200 and upd.json()["active"] is False


def test_operator_certification(client):
    r = client.post("/compliance/operator-certifications",
                    json={"user_id": str(_USER), "certification_type": "crane"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.post(f"/compliance/operator-certifications/{cid}/expire").json()["status"] == "expired"


# --- RBAC -----------------------------------------------------------------


# --- compliance checks (evaluate / list / get / override) -----------------


def test_evaluate_list_get_override_checks(client):
    cat, eq, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed_shipment_with_equipment(
        _TestSession, tenant_id=_TENANT, client_user_id=_USER, category_id=cat,
        equipment_id=eq, shipment_id=sid, requires_permit=True, requires_escort=True,
    )
    # Evaluate → permit_required + escort_required should FAIL (none present).
    r = client.post("/compliance/checks/evaluate", json={"shipment_id": str(sid)})
    assert r.status_code == 201, r.text
    checks = r.json()
    assert any(c["check_type"] == "permit_required" and c["status"] == "failed" for c in checks)

    listing = client.get(f"/compliance/checks?shipment_id={sid}")
    assert listing.status_code == 200 and listing.json()["total"] >= 2

    failed = [c for c in checks if c["status"] == "failed"][0]
    assert client.get(f"/compliance/checks/{failed['id']}").json()["id"] == failed["id"]

    overridden = client.post(f"/compliance/checks/{failed['id']}/override", json={"reason": "ok"})
    assert overridden.status_code == 200
    assert overridden.json()["status"] == "overridden"
    assert overridden.json()["blocking"] is False


def test_override_requires_authorized_role(client):
    cat, eq, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed_shipment_with_equipment(
        _TestSession, tenant_id=_TENANT, client_user_id=_USER, category_id=cat,
        equipment_id=eq, shipment_id=sid, requires_permit=True,
    )
    checks = client.post("/compliance/checks/evaluate", json={"shipment_id": str(sid)}).json()
    failed = [c for c in checks if c["status"] == "failed"][0]
    _ROLE["role"] = UserRole.CLIENT
    try:
        r = client.post(f"/compliance/checks/{failed['id']}/override", json={"reason": "x"})
        assert r.status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_axle_profile_create(client):
    r = client.post("/compliance/axle-weight-profiles",
                    json={"axle_count": 3, "total_weight": 30000, "is_compliant": True})
    assert r.status_code == 201
    assert r.json()["axle_count"] == 3


def test_rbac_client_cannot_create_permit(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.post("/compliance/permits", json={"permit_type": "oversize"}).status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_client_can_read_permits(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/compliance/permits").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN
