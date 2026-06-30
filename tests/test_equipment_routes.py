"""Integration tests for Equipment API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.equipment import router as equipment_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from equipment_sqlite import make_engine, seed_prereqs

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_CAT = uuid.uuid4()
_MODEL = uuid.uuid4()
_WH = uuid.uuid4()

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
    return types.SimpleNamespace(
        id=_USER, tenant_id=_TENANT, role=_ROLE["role"], is_active=True
    )


@pytest.fixture(scope="module")
def client():
    seed_prereqs(
        _TestSession, tenant_id=_TENANT, category_id=_CAT, model_id=_MODEL, warehouse_id=_WH
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(equipment_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_ctx():
    with (
        patch("app.services.equipment_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.equipment_service.get_current_user_id", return_value=_USER),
        patch("app.services.equipment_service.EventStoreRepository", autospec=True) as M,
    ):
        inst = M.return_value
        inst.next_aggregate_version.return_value = 1
        inst.append.return_value = None
        yield


def _payload(**ov) -> dict:
    base = {"asset_tag": f"TAG-{uuid.uuid4().hex[:8]}", "category_id": str(_CAT), "name": "Excavator"}
    base.update(ov)
    return base


def _create(client, **ov) -> dict:
    r = client.post("/equipment", json=_payload(**ov))
    assert r.status_code == 201, r.text
    return r.json()


# --- create ---------------------------------------------------------------


def test_create_201(client):
    body = _create(client, equipment_code="EQP-A1")
    assert body["equipment_code"] == "EQP-A1"
    assert body["status"] == "active"
    assert body["availability_status"] == "available"


def test_create_auto_code(client):
    assert _create(client)["equipment_code"].startswith("EQP-")


def test_create_duplicate_code_409(client):
    p = _payload(equipment_code="EQP-DUP1", asset_tag="TAGX1")
    client.post("/equipment", json=p)
    p2 = _payload(equipment_code="EQP-DUP1", asset_tag="TAGX2")
    assert client.post("/equipment", json=p2).status_code == 409


def test_create_unknown_category_422(client):
    assert client.post("/equipment", json=_payload(category_id=str(uuid.uuid4()))).status_code == 422


def test_create_bad_year_422(client):
    assert client.post("/equipment", json=_payload(year=1800)).status_code == 422


def test_create_negative_weight_422(client):
    assert client.post("/equipment", json=_payload(weight_kg=-1)).status_code == 422


# --- read / list / search -------------------------------------------------


def test_get_200_404(client):
    cid = _create(client)["id"]
    assert client.get(f"/equipment/{cid}").json()["id"] == cid
    assert client.get(f"/equipment/{uuid.uuid4()}").status_code == 404


def test_list_envelope(client):
    body = client.get("/equipment").json()
    assert {"items", "total", "page", "size", "pages"} <= body.keys()


def test_list_filter_status(client):
    r = client.get("/equipment?status=active")
    assert r.status_code == 200
    assert all(i["status"] == "active" for i in r.json()["items"])


def test_invalid_sort_422(client):
    assert client.get("/equipment?sort_by=ssn").status_code == 422


def test_search_and_route_precedence(client):
    _create(client, name="Crawler Crane Pharma")
    r = client.get("/equipment/search?q=Pharma")
    assert r.status_code == 200
    assert any("Pharma" in i["name"] for i in r.json()["items"])
    assert client.get("/equipment/search").status_code == 200  # not captured by /{id}


# --- update ---------------------------------------------------------------


def test_update_200(client):
    cid = _create(client)["id"]
    r = client.patch(f"/equipment/{cid}", json={"notes": "serviced"})
    assert r.status_code == 200 and r.json()["notes"] == "serviced"


def test_update_empty_422(client):
    cid = _create(client)["id"]
    assert client.patch(f"/equipment/{cid}", json={}).status_code == 422


# --- lifecycle ------------------------------------------------------------


def test_full_lifecycle(client):
    cid = _create(client)["id"]
    assert client.post(f"/equipment/{cid}/reserve", json={"reference": "ORD-1"}).json()["status"] == "reserved"
    assert client.post(f"/equipment/{cid}/release").json()["status"] == "active"
    assert client.post(f"/equipment/{cid}/deactivate").json()["status"] == "inactive"
    assert client.post(f"/equipment/{cid}/activate").json()["status"] == "active"
    assert client.post(f"/equipment/{cid}/maintenance/start", json={"reason": "x"}).json()["status"] == "under_maintenance"
    assert client.post(f"/equipment/{cid}/maintenance/complete").json()["status"] == "active"
    assert client.post(f"/equipment/{cid}/decommission", json={}).json()["status"] == "decommissioned"


def test_reserve_unavailable_409(client):
    cid = _create(client)["id"]
    client.post(f"/equipment/{cid}/reserve", json={})
    # already reserved → availability not available → 409
    assert client.post(f"/equipment/{cid}/reserve", json={}).status_code == 409


def test_decommissioned_update_422(client):
    cid = _create(client)["id"]
    client.post(f"/equipment/{cid}/decommission", json={})
    assert client.patch(f"/equipment/{cid}", json={"notes": "x"}).status_code == 422


# --- delete / restore -----------------------------------------------------


def test_delete_hidden_twice(client):
    cid = _create(client)["id"]
    assert client.delete(f"/equipment/{cid}").status_code == 204
    assert client.get(f"/equipment/{cid}").status_code == 404
    assert client.delete(f"/equipment/{cid}").status_code == 404


def test_restore(client):
    cid = _create(client)["id"]
    client.delete(f"/equipment/{cid}")
    r = client.post(f"/equipment/{cid}/restore")
    assert r.status_code == 200 and r.json()["deleted_at"] is None


def test_restore_non_deleted_422(client):
    cid = _create(client)["id"]
    assert client.post(f"/equipment/{cid}/restore").status_code == 422


# --- tenant isolation & RBAC ----------------------------------------------


def test_tenant_isolation(client):
    for item in client.get("/equipment").json()["items"]:
        assert item["tenant_id"].replace("-", "") == str(_TENANT).replace("-", "")


def test_rbac_client_cannot_create(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.post("/equipment", json=_payload()).status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_client_can_read(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/equipment").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN


# --- categories & models --------------------------------------------------


def test_create_and_list_category(client):
    code = f"CAT-{uuid.uuid4().hex[:6]}"
    r = client.post("/equipment/categories", json={"code": code, "name": "Lifting"})
    assert r.status_code == 201, r.text
    assert r.json()["code"] == code
    assert r.json()["is_active"] is True
    listing = client.get("/equipment/categories")
    assert listing.status_code == 200
    assert any(c["code"] == code for c in listing.json())


def test_create_category_duplicate_409(client):
    code = f"CAT-DUP-{uuid.uuid4().hex[:6]}"
    client.post("/equipment/categories", json={"code": code, "name": "X"})
    assert client.post("/equipment/categories", json={"code": code, "name": "X"}).status_code == 409


def test_create_and_list_model(client):
    code = f"MOD-{uuid.uuid4().hex[:6]}"
    r = client.post(
        "/equipment/models",
        json={"code": code, "name": "Grove GMK", "category_id": str(_CAT)},
    )
    assert r.status_code == 201, r.text
    assert r.json()["category_id"] == str(_CAT)
    assert any(m["code"] == code for m in client.get("/equipment/models").json())


def test_create_model_unknown_category_422(client):
    r = client.post(
        "/equipment/models",
        json={"code": "MX", "name": "Y", "category_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422


def test_category_route_precedence_over_id(client):
    # "/equipment/categories" must resolve to the literal route, not /{uuid}.
    assert client.get("/equipment/categories").status_code == 200
    assert client.get("/equipment/models").status_code == 200


def test_rbac_client_cannot_create_category(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        r = client.post("/equipment/categories", json={"code": "Z", "name": "Z"})
        assert r.status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN
