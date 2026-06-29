"""Integration tests for Shipment API routes (SQLite TestClient).

Strategy mirrors test_order_routes.py:
  * in-memory SQLite (PG-only regex CHECK stripped via shipment_sqlite helpers),
  * get_session overridden to the test session,
  * EventStoreRepository patched at the service module (no event_store writes),
  * get_current_user overridden to a stub user (bypasses JWT / sets the role),
  * tenant/user context vars patched.
"""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.shipments import router as shipment_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from shipment_sqlite import make_engine, seed_driver_and_vehicle, seed_prereqs

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_CLIENT = uuid.uuid4()
_ORIGIN = uuid.uuid4()
_DEST = uuid.uuid4()
_DRV_USER = uuid.uuid4()
_DRIVER = uuid.uuid4()
_VEHICLE = uuid.uuid4()

# Extra driver/vehicle pairs so lifecycle tests that leave a shipment in an
# active (non-terminal) state do not exhaust the shared driver's availability.
_EXTRA_PAIRS = [
    (uuid.uuid4(), uuid.uuid4(), uuid.uuid4()) for _ in range(6)
]  # (driver_user_id, driver_id, vehicle_id)
_pair_iter = iter([(_DRIVER, _VEHICLE)] + [(d, v) for _, d, v in _EXTRA_PAIRS])

_engine = make_engine()
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)

# Mutable role holder so individual tests can flip RBAC role.
_ROLE = {"role": UserRole.ADMIN}


def _create_test_session() -> Iterator:
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


def _override_current_user():
    return types.SimpleNamespace(
        id=_USER, tenant_id=_TENANT, role=_ROLE["role"], is_active=True
    )


@pytest.fixture(scope="module")
def client():
    seed_prereqs(
        _TestSession,
        tenant_id=_TENANT,
        client_id=_CLIENT,
        origin_id=_ORIGIN,
        dest_id=_DEST,
    )
    seed_driver_and_vehicle(
        _TestSession,
        tenant_id=_TENANT,
        driver_user_id=_DRV_USER,
        driver_id=_DRIVER,
        vehicle_id=_VEHICLE,
    )
    for du, d, v in _EXTRA_PAIRS:
        seed_driver_and_vehicle(
            _TestSession,
            tenant_id=_TENANT,
            driver_user_id=du,
            driver_id=d,
            vehicle_id=v,
        )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(shipment_router)
    app.dependency_overrides[get_session] = _create_test_session
    app.dependency_overrides[get_current_user] = _override_current_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_context_and_events():
    with (
        patch("app.services.shipment_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.shipment_service.get_current_user_id", return_value=_USER),
        patch(
            "app.services.shipment_service.EventStoreRepository", autospec=True
        ) as MockEvents,
    ):
        inst = MockEvents.return_value
        inst.next_aggregate_version.return_value = 1
        inst.append.return_value = None
        yield


def _payload(**ov) -> dict:
    base = {
        "client_id": str(_CLIENT),
        "origin_warehouse_id": str(_ORIGIN),
        "destination_warehouse_id": str(_DEST),
        "weight_kg": 5,
        "volume_m3": 1,
    }
    base.update(ov)
    return base


def _create(client, **ov) -> dict:
    resp = client.post("/shipments", json=_payload(**ov))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- create ---------------------------------------------------------------


def test_create_201(client):
    body = _create(client, reference_code="SHP-A1")
    assert body["reference_code"] == "SHP-A1"
    assert body["status"] == "created"
    assert body["priority"] == "normal"
    assert "id" in body


def test_create_auto_reference(client):
    resp = client.post("/shipments", json=_payload())
    assert resp.status_code == 201
    assert resp.json()["reference_code"].startswith("SHP-")


def test_create_duplicate_reference_409(client):
    p = _payload(reference_code="SHP-DUP9")
    client.post("/shipments", json=p)
    assert client.post("/shipments", json=p).status_code == 409


def test_create_unknown_client_422(client):
    resp = client.post("/shipments", json=_payload(client_id=str(uuid.uuid4())))
    assert resp.status_code == 422


def test_create_whitespace_reference_422(client):
    resp = client.post("/shipments", json=_payload(reference_code="HAS SPACE"))
    assert resp.status_code == 422


def test_create_pickup_after_delivery_422(client):
    resp = client.post(
        "/shipments",
        json=_payload(
            pickup_at="2026-07-10T10:00:00+00:00",
            delivery_due_at="2026-07-01T10:00:00+00:00",
        ),
    )
    assert resp.status_code == 422


def test_create_negative_weight_422(client):
    resp = client.post("/shipments", json=_payload(weight_kg=0))
    assert resp.status_code == 422


# --- read / list / search -------------------------------------------------


def test_get_200_and_404(client):
    cid = _create(client, reference_code="SHP-GET1")["id"]
    assert client.get(f"/shipments/{cid}").json()["id"] == cid
    assert client.get(f"/shipments/{uuid.uuid4()}").status_code == 404


def test_list_envelope(client):
    body = client.get("/shipments").json()
    assert {"items", "total", "page", "size", "pages"} <= body.keys()


def test_list_pagination(client):
    for i in range(3):
        _create(client, reference_code=f"SHP-PAG{i}")
    resp = client.get("/shipments?page=1&size=2")
    assert resp.json()["size"] == 2
    assert len(resp.json()["items"]) <= 2


def test_list_filter_status(client):
    resp = client.get("/shipments?status=created")
    assert resp.status_code == 200
    assert all(i["status"] == "created" for i in resp.json()["items"])


def test_list_invalid_sort_422(client):
    assert client.get("/shipments?sort_by=ssn").status_code == 422


def test_search_match_and_empty(client):
    _create(client, reference_code="SHP-SRCH1", cargo_type="refrigerated pharma")
    resp = client.get("/shipments/search?q=pharma")
    assert resp.status_code == 200
    assert any("pharma" in (i.get("cargo_type") or "") for i in resp.json()["items"])
    assert client.get("/shipments/search?q=ZZZNOPE").json()["total"] == 0


def test_search_route_precedence_over_id(client):
    # /shipments/search must not be captured by /shipments/{id} (uuid converter).
    assert client.get("/shipments/search").status_code == 200


# --- update ---------------------------------------------------------------


def test_update_200(client):
    cid = _create(client, reference_code="SHP-UPD1")["id"]
    resp = client.patch(f"/shipments/{cid}", json={"priority": "urgent"})
    assert resp.status_code == 200
    assert resp.json()["priority"] == "urgent"


def test_update_empty_422(client):
    cid = _create(client, reference_code="SHP-UPD2")["id"]
    assert client.patch(f"/shipments/{cid}", json={}).status_code == 422


def test_update_404(client):
    assert client.patch(f"/shipments/{uuid.uuid4()}", json={"priority": "high"}).status_code == 404


# --- lifecycle ------------------------------------------------------------


def _ready_assign(client, ref) -> str:
    driver_id, vehicle_id = next(_pair_iter)
    cid = _create(client, reference_code=ref)["id"]
    assert client.post(f"/shipments/{cid}/ready").json()["status"] == "ready"
    assigned = client.post(
        f"/shipments/{cid}/assign",
        json={"driver_id": str(driver_id), "vehicle_id": str(vehicle_id)},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "assigned"
    return cid


def test_full_lifecycle(client):
    cid = _ready_assign(client, "SHP-FLOW1")
    assert client.post(f"/shipments/{cid}/pickup").json()["status"] == "picked_up"
    assert client.post(f"/shipments/{cid}/transit").json()["status"] == "in_transit"
    delivered = client.post(f"/shipments/{cid}/deliver")
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "delivered"


def test_assign_requires_ready_409(client):
    cid = _create(client, reference_code="SHP-NOTREADY")["id"]
    resp = client.post(
        f"/shipments/{cid}/assign",
        json={"driver_id": str(_DRIVER), "vehicle_id": str(_VEHICLE)},
    )
    assert resp.status_code == 409  # created → assigned is illegal


def test_delay_then_resume(client):
    cid = _ready_assign(client, "SHP-DELAY1")
    client.post(f"/shipments/{cid}/pickup")
    client.post(f"/shipments/{cid}/transit")
    assert client.post(f"/shipments/{cid}/delay", json={"reason": "weather"}).json()[
        "status"
    ] == "delayed"
    assert client.post(f"/shipments/{cid}/transit").json()["status"] == "in_transit"


def test_fail_and_return(client):
    cid = _ready_assign(client, "SHP-FAIL1")
    client.post(f"/shipments/{cid}/pickup")
    client.post(f"/shipments/{cid}/transit")
    assert client.post(f"/shipments/{cid}/fail", json={"reason": "x"}).json()[
        "status"
    ] == "failed"
    assert client.post(f"/shipments/{cid}/return", json={"reason": "y"}).json()[
        "status"
    ] == "returned"


def test_cancel(client):
    cid = _create(client, reference_code="SHP-CAN1")["id"]
    resp = client.post(f"/shipments/{cid}/cancel", json={"reason": "mind changed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_update_terminal_422(client):
    cid = _create(client, reference_code="SHP-TERM1")["id"]
    client.post(f"/shipments/{cid}/cancel", json={})
    assert client.patch(f"/shipments/{cid}", json={"priority": "high"}).status_code == 422


# --- delete / restore -----------------------------------------------------


def test_delete_then_hidden_then_twice(client):
    cid = _create(client, reference_code="SHP-DEL1")["id"]
    assert client.delete(f"/shipments/{cid}").status_code == 204
    assert client.get(f"/shipments/{cid}").status_code == 404
    assert client.delete(f"/shipments/{cid}").status_code == 404


def test_restore(client):
    cid = _create(client, reference_code="SHP-RST1")["id"]
    client.delete(f"/shipments/{cid}")
    resp = client.post(f"/shipments/{cid}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None


def test_restore_non_deleted_422(client):
    cid = _create(client, reference_code="SHP-RST2")["id"]
    assert client.post(f"/shipments/{cid}/restore").status_code == 422


# --- tenant isolation & RBAC ----------------------------------------------


def test_list_only_returns_tenant_shipments(client):
    resp = client.get("/shipments")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["tenant_id"].replace("-", "") == str(_TENANT).replace("-", "")


def test_rbac_client_cannot_create(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        resp = client.post("/shipments", json=_payload())
        assert resp.status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_client_can_read(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/shipments").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN
