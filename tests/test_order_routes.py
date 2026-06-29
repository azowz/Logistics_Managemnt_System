"""Integration tests for Order API routes (SQLite TestClient).

Strategy mirrors test_customer_routes.py:
  * in-memory SQLite with all tables created via Base.metadata.create_all(),
  * get_session overridden to the test session,
  * EventStoreRepository patched at the service module (no event_store writes),
  * require_roles overridden to a stub user (bypasses JWT),
  * tenant/user context vars patched.
A Tenant AND a Customer are seeded once per module (orders FK + validate against them).
"""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.orders import router as order_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.base import Base
from app.db.session import get_session
from app.models.enums import (
    CreditStatus,
    CustomerStatus,
    CustomerType,
    RiskLevel,
    UserRole,
)

_TENANT_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()
_CUSTOMER_ID = uuid.uuid4()

_test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    # StaticPool shares a single connection across threads so the TestClient's
    # request thread sees the same in-memory database that create_all/seed used.
    poolclass=StaticPool,
)
_TestSession = sessionmaker(
    bind=_test_engine, autocommit=False, autoflush=False, expire_on_commit=False
)


def _create_test_session() -> Iterator[Session]:
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def test_app():
    import app.models  # noqa: F401 — register all models
    from app.models.customer import Customer
    from app.models.order import Order
    from app.models.tenant import Tenant
    from app.models.user import User

    # Create only the tables this suite needs. Full-metadata create_all is not
    # SQLite-safe (the shipments table uses a PostgreSQL regex CHECK).
    Base.metadata.create_all(
        bind=_test_engine,
        tables=[Tenant.__table__, User.__table__, Customer.__table__, Order.__table__],
    )
    _seed_prerequisites()

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(order_router)
    app.dependency_overrides[get_session] = _create_test_session
    # Bypass JWT auth: every require_roles(...) inner dependency depends on
    # get_current_user, so overriding it satisfies all role checks with an ADMIN.
    app.dependency_overrides[get_current_user] = _override_current_user
    return app


def _override_current_user():
    """Return a dummy ADMIN user so all RBAC checks pass."""
    return types.SimpleNamespace(
        id=_USER_ID, tenant_id=_TENANT_ID, role=UserRole.ADMIN, is_active=True
    )


@pytest.fixture(scope="module")
def client(test_app):
    return TestClient(test_app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_context_and_events():
    with (
        patch("app.services.order_service.get_current_tenant", return_value=_TENANT_ID),
        patch("app.services.order_service.get_current_user_id", return_value=_USER_ID),
        patch("app.services.order_service.EventStoreRepository", autospec=True) as MockEventStore,
    ):
        inst = MockEventStore.return_value
        inst.next_aggregate_version.return_value = 1
        inst.append.return_value = None
        yield


def _seed_prerequisites():
    """Insert the tenant, a customer, and a dispatcher user the orders reference."""
    from app.models.customer import Customer
    from app.models.tenant import Tenant
    from app.models.user import User

    session = _TestSession()
    try:
        if session.get(Tenant, _TENANT_ID) is None:
            session.add(
                Tenant(
                    id=_TENANT_ID,
                    slug="order-tenant",
                    name="Order Tenant",
                    status="active",
                    isolation_mode="shared",
                )
            )
            session.commit()

        if session.get(Customer, _CUSTOMER_ID) is None:
            session.add(
                Customer(
                    id=_CUSTOMER_ID,
                    tenant_id=_TENANT_ID,
                    code="CUST-ORD-001",
                    company_name="Order Customer Co",
                    customer_type=CustomerType.CORPORATE,
                    status=CustomerStatus.ACTIVE,
                    risk_level=RiskLevel.LOW,
                    credit_status=CreditStatus.GOOD,
                )
            )
            session.commit()

        # Dispatcher user referenced by assign_order (id == _USER_ID).
        if session.get(User, _USER_ID) is None:
            session.add(
                User(
                    id=_USER_ID,
                    tenant_id=_TENANT_ID,
                    email="dispatcher@order-tenant.test",
                    hashed_password="x",
                    role=UserRole.MANAGER,
                    is_active=True,
                )
            )
            session.commit()
    finally:
        session.close()


def _payload(**overrides) -> dict:
    base = {"customer_id": str(_CUSTOMER_ID), "order_type": "standard"}
    base.update(overrides)
    return base


def _create(client, **overrides) -> dict:
    resp = client.post("/orders", json=_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- create ---------------------------------------------------------------


def test_create_order_201(client):
    body = _create(client, order_number="ORD-A001")
    assert body["order_number"] == "ORD-A001"
    assert body["status"] == "draft"
    assert body["customer_id"] == str(_CUSTOMER_ID)
    assert "id" in body


def test_create_order_auto_number(client):
    resp = client.post("/orders", json=_payload())
    assert resp.status_code == 201
    assert resp.json()["order_number"].startswith("ORD-")


def test_create_order_duplicate_number_409(client):
    p = _payload(order_number="ORD-DUP1")
    client.post("/orders", json=p)
    resp = client.post("/orders", json=p)
    assert resp.status_code == 409


def test_create_order_unknown_customer_422(client):
    resp = client.post("/orders", json={"customer_id": str(uuid.uuid4())})
    assert resp.status_code == 422


def test_create_order_whitespace_number_422(client):
    resp = client.post("/orders", json=_payload(order_number="HAS SPACE"))
    assert resp.status_code == 422


def test_create_order_delivery_before_pickup_422(client):
    resp = client.post(
        "/orders",
        json=_payload(
            requested_pickup_date="2026-07-10T10:00:00+00:00",
            requested_delivery_date="2026-07-01T10:00:00+00:00",
        ),
    )
    assert resp.status_code == 422


# --- read / list / search -------------------------------------------------


def test_get_order_200(client):
    cid = _create(client, order_number="ORD-GET1")["id"]
    resp = client.get(f"/orders/{cid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == cid


def test_get_order_404(client):
    resp = client.get(f"/orders/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_list_orders_200(client):
    resp = client.get("/orders")
    assert resp.status_code == 200
    body = resp.json()
    assert {"items", "total", "page", "size", "pages"} <= body.keys()


def test_list_orders_pagination(client):
    for i in range(3):
        _create(client, order_number=f"ORD-PAG{i}")
    resp = client.get("/orders?page=1&size=2")
    assert resp.status_code == 200
    assert resp.json()["size"] == 2
    assert len(resp.json()["items"]) <= 2


def test_list_orders_filter_status(client):
    resp = client.get("/orders?status=draft")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["status"] == "draft"


def test_list_orders_invalid_sort_422(client):
    resp = client.get("/orders?sort_by=ssn")
    assert resp.status_code == 422


def test_search_orders(client):
    _create(client, order_number="ORD-SRCH1", cargo_description="Refrigerated pharma")
    resp = client.get("/orders/search?q=pharma")
    assert resp.status_code == 200
    assert any("pharma" in (i.get("cargo_description") or "").lower() for i in resp.json()["items"])


def test_search_orders_no_match_empty(client):
    resp = client.get("/orders/search?q=ZZZNOMATCH99")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# --- update ---------------------------------------------------------------


def test_update_order_200(client):
    cid = _create(client, order_number="ORD-UPD1")["id"]
    resp = client.patch(f"/orders/{cid}", json={"priority": "urgent"})
    assert resp.status_code == 200
    assert resp.json()["priority"] == "urgent"


def test_update_order_empty_body_422(client):
    cid = _create(client, order_number="ORD-UPD2")["id"]
    resp = client.patch(f"/orders/{cid}", json={})
    assert resp.status_code == 422


def test_update_order_404(client):
    resp = client.patch(f"/orders/{uuid.uuid4()}", json={"priority": "high"})
    assert resp.status_code == 404


# --- state machine via API ------------------------------------------------


def test_submit_approve_schedule_assign_transit_deliver(client):
    cid = _create(client, order_number="ORD-FLOW1")["id"]

    assert client.post(f"/orders/{cid}/submit").json()["status"] == "submitted"
    assert client.post(f"/orders/{cid}/approve", json={}).json()["status"] == "approved"
    assert client.post(f"/orders/{cid}/schedule").json()["status"] == "scheduled"
    assigned = client.post(
        f"/orders/{cid}/assign", json={"assigned_dispatcher_id": str(_USER_ID)}
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "assigned"
    assert client.post(f"/orders/{cid}/start-transit").json()["status"] == "in_transit"
    delivered = client.post(f"/orders/{cid}/deliver")
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "delivered"


def test_invalid_transition_409(client):
    cid = _create(client, order_number="ORD-BADTX")["id"]
    # draft → deliver is illegal (no such endpoint path jump); use approve on draft
    resp = client.post(f"/orders/{cid}/approve", json={})
    assert resp.status_code == 409


def test_cancel_order(client):
    cid = _create(client, order_number="ORD-CAN1")["id"]
    resp = client.post(f"/orders/{cid}/cancel", json={"reason": "customer changed mind"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_fail_order(client):
    cid = _create(client, order_number="ORD-FAIL1")["id"]
    client.post(f"/orders/{cid}/submit")
    resp = client.post(f"/orders/{cid}/fail", json={"reason": "no capacity"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


# --- delete / restore -----------------------------------------------------


def test_delete_order_204(client):
    cid = _create(client, order_number="ORD-DEL1")["id"]
    resp = client.delete(f"/orders/{cid}")
    assert resp.status_code == 204


def test_deleted_order_hidden(client):
    cid = _create(client, order_number="ORD-DEL2")["id"]
    client.delete(f"/orders/{cid}")
    resp = client.get(f"/orders/{cid}")
    assert resp.status_code == 404


def test_delete_twice_404(client):
    cid = _create(client, order_number="ORD-DEL3")["id"]
    client.delete(f"/orders/{cid}")
    resp = client.delete(f"/orders/{cid}")
    assert resp.status_code == 404


def test_restore_order_200(client):
    cid = _create(client, order_number="ORD-RST1")["id"]
    client.delete(f"/orders/{cid}")
    resp = client.post(f"/orders/{cid}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None


def test_restore_non_deleted_422(client):
    cid = _create(client, order_number="ORD-RST2")["id"]
    resp = client.post(f"/orders/{cid}/restore")
    assert resp.status_code == 422


# --- tenant isolation -----------------------------------------------------


def test_list_only_returns_tenant_orders(client):
    resp = client.get("/orders")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["tenant_id"].replace("-", "") == str(_TENANT_ID).replace("-", "")
