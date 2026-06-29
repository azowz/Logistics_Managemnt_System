"""Integration tests for Customer API routes.

Strategy
--------
* SQLite in-memory database with all tables created via ``Base.metadata.create_all()``.
* ``get_session`` dependency is overridden to use the test session.
* ``EventStoreRepository`` is patched at the service-module level so no
  ``event_store`` table writes are needed (that table has PostgreSQL-specific
  UUID PKs that SQLite handles differently; isolating it avoids noise).
* ``require_roles`` is overridden with a stub that returns a dummy user,
  bypassing JWT validation.
* Tenant context vars (``get_current_tenant`` / ``get_current_user_id``) are
  patched for the duration of each test module.

All fixtures use ``scope="module"`` so the in-memory DB is shared and seeded
once per test run.
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

from app.api.routes.customers import router as customer_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.base import Base
from app.db.session import get_session
from app.models.enums import UserRole

# ---------------------------------------------------------------------------
# Test-level constants
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# In-memory SQLite engine (module-scoped — shared across all tests)
# ---------------------------------------------------------------------------

_test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    # Single shared connection so the TestClient's request thread sees the same
    # in-memory DB that create_all/seed populated.
    poolclass=StaticPool,
)
_TestSession = sessionmaker(
    bind=_test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def _create_test_session() -> Iterator[Session]:
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def test_app():
    """Build an isolated FastAPI app wired only with the customer router."""
    import app.models  # noqa: F401 — register all models
    from app.models.customer import Customer
    from app.models.tenant import Tenant

    # Create only the tables this suite needs. Full-metadata create_all is not
    # SQLite-safe (the shipments table uses a PostgreSQL regex CHECK).
    Base.metadata.create_all(
        bind=_test_engine, tables=[Tenant.__table__, Customer.__table__]
    )

    _seed_tenant()

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(customer_router)
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
    """Module-scoped patch for tenant/user context vars and event store."""
    with (
        patch(
            "app.services.customer_service.get_current_tenant",
            return_value=_TENANT_ID,
        ),
        patch(
            "app.services.customer_service.get_current_user_id",
            return_value=_USER_ID,
        ),
        patch(
            "app.services.customer_service.EventStoreRepository",
            autospec=True,
        ) as MockEventStore,
    ):
        mock_instance = MockEventStore.return_value
        mock_instance.next_aggregate_version.return_value = 1
        mock_instance.append.return_value = None
        yield


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_tenant():
    """Insert the test tenant row (via ORM) so FK constraints pass."""
    from app.models.tenant import Tenant

    session = _TestSession()
    try:
        if session.get(Tenant, _TENANT_ID) is None:
            session.add(
                Tenant(
                    id=_TENANT_ID,
                    slug="test-tenant",
                    name="Test Tenant",
                    status="active",
                    isolation_mode="shared",
                )
            )
            session.commit()
    finally:
        session.close()


def _create_payload(**overrides) -> dict:
    base = {
        "code": "CUST-001",
        "company_name": "Acme Corp",
        "customer_type": "corporate",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# POST /customers
# ---------------------------------------------------------------------------


def test_create_customer_returns_201(client):
    response = client.post("/customers", json=_create_payload(code="NEW-001"))
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "NEW-001"
    assert body["company_name"] == "Acme Corp"
    assert body["status"] == "active"
    assert "id" in body


def test_create_customer_returns_409_on_duplicate_code(client):
    payload = _create_payload(code="DUP-001")
    client.post("/customers", json=payload)  # first insert succeeds
    response = client.post("/customers", json=payload)  # second must fail
    assert response.status_code == 409


def test_create_customer_returns_422_on_whitespace_code(client):
    response = client.post("/customers", json=_create_payload(code="HAS SPACE"))
    assert response.status_code == 422


def test_create_customer_returns_422_on_missing_company_name(client):
    response = client.post(
        "/customers",
        json={"code": "X001", "customer_type": "corporate"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /customers/{id}
# ---------------------------------------------------------------------------


def test_get_customer_returns_200(client):
    create_resp = client.post("/customers", json=_create_payload(code="GET-001"))
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]

    response = client.get(f"/customers/{cid}")
    assert response.status_code == 200
    assert response.json()["id"] == cid


def test_get_customer_returns_404_for_unknown_id(client):
    response = client.get(f"/customers/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_customer_returns_404_for_deleted(client):
    create_resp = client.post("/customers", json=_create_payload(code="DEL-FOR-GET"))
    cid = create_resp.json()["id"]
    client.delete(f"/customers/{cid}")

    response = client.get(f"/customers/{cid}")
    assert response.status_code == 404


def test_get_customer_includes_deleted_when_param_set(client):
    create_resp = client.post("/customers", json=_create_payload(code="DEL-INCL"))
    cid = create_resp.json()["id"]
    client.delete(f"/customers/{cid}")

    response = client.get(f"/customers/{cid}?include_deleted=true")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /customers
# ---------------------------------------------------------------------------


def test_list_customers_returns_200(client):
    response = client.get("/customers")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "pages" in body


def test_list_customers_pagination(client):
    # Create a handful of customers.
    for i in range(3):
        client.post("/customers", json=_create_payload(code=f"LIST-{i:03d}"))

    response = client.get("/customers?page=1&size=2")
    assert response.status_code == 200
    body = response.json()
    assert body["size"] == 2
    assert len(body["items"]) <= 2


def test_list_customers_filter_by_status(client):
    response = client.get("/customers?status=active")
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert item["status"] == "active"


def test_list_customers_invalid_sort_by_returns_422(client):
    response = client.get("/customers?sort_by=nonexistent_field")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /customers/search
# ---------------------------------------------------------------------------


def test_search_customers_returns_200(client):
    client.post("/customers", json=_create_payload(code="SRCH-001", company_name="Search Target Ltd"))
    response = client.get("/customers/search?q=Search+Target")
    assert response.status_code == 200
    body = response.json()
    assert any("Search Target" in item["company_name"] for item in body["items"])


def test_search_customers_no_match_returns_empty(client):
    response = client.get("/customers/search?q=ZZZNOMATCH999")
    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---------------------------------------------------------------------------
# PATCH /customers/{id}
# ---------------------------------------------------------------------------


def test_update_customer_returns_200(client):
    create_resp = client.post("/customers", json=_create_payload(code="UPD-001"))
    cid = create_resp.json()["id"]

    response = client.patch(f"/customers/{cid}", json={"company_name": "Updated Corp"})
    assert response.status_code == 200
    assert response.json()["company_name"] == "Updated Corp"


def test_update_customer_returns_404_for_unknown(client):
    response = client.patch(
        f"/customers/{uuid.uuid4()}", json={"company_name": "Ghost Corp"}
    )
    assert response.status_code == 404


def test_update_customer_returns_422_on_empty_body(client):
    create_resp = client.post("/customers", json=_create_payload(code="UPD-EMPTY"))
    cid = create_resp.json()["id"]
    response = client.patch(f"/customers/{cid}", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /customers/{id}
# ---------------------------------------------------------------------------


def test_delete_customer_returns_204(client):
    create_resp = client.post("/customers", json=_create_payload(code="DEL-001"))
    cid = create_resp.json()["id"]

    response = client.delete(f"/customers/{cid}")
    assert response.status_code == 204


def test_delete_customer_hides_from_list(client):
    create_resp = client.post("/customers", json=_create_payload(code="DEL-HIDE"))
    cid = create_resp.json()["id"]
    client.delete(f"/customers/{cid}")

    # Should not appear in default listing.
    list_resp = client.get("/customers")
    ids = [item["id"] for item in list_resp.json()["items"]]
    assert cid not in ids


def test_delete_customer_twice_returns_404(client):
    create_resp = client.post("/customers", json=_create_payload(code="DEL-TWICE"))
    cid = create_resp.json()["id"]
    client.delete(f"/customers/{cid}")

    response = client.delete(f"/customers/{cid}")
    assert response.status_code == 404


def test_delete_unknown_customer_returns_404(client):
    response = client.delete(f"/customers/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /customers/{id}/restore
# ---------------------------------------------------------------------------


def test_restore_customer_returns_200(client):
    create_resp = client.post("/customers", json=_create_payload(code="RST-001"))
    cid = create_resp.json()["id"]
    client.delete(f"/customers/{cid}")

    response = client.post(f"/customers/{cid}/restore")
    assert response.status_code == 200
    assert response.json()["deleted_at"] is None


def test_restore_non_deleted_customer_returns_422(client):
    create_resp = client.post("/customers", json=_create_payload(code="RST-NDEL"))
    cid = create_resp.json()["id"]

    response = client.post(f"/customers/{cid}/restore")
    assert response.status_code == 422


def test_restore_unknown_customer_returns_404(client):
    response = client.post(f"/customers/{uuid.uuid4()}/restore")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /customers/{id}/activate and /suspend
# ---------------------------------------------------------------------------


def test_activate_customer_from_suspended(client):
    create_resp = client.post("/customers", json=_create_payload(code="ACT-001"))
    cid = create_resp.json()["id"]

    # Suspend first.
    client.post(f"/customers/{cid}/suspend", json={"reason": "test"})

    # Then activate.
    response = client.post(f"/customers/{cid}/activate", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_suspend_customer(client):
    create_resp = client.post("/customers", json=_create_payload(code="SUSP-001"))
    cid = create_resp.json()["id"]

    response = client.post(f"/customers/{cid}/suspend", json={"reason": "Late payment"})
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


def test_suspend_already_suspended_is_noop(client):
    create_resp = client.post("/customers", json=_create_payload(code="SUSP-IDEM"))
    cid = create_resp.json()["id"]
    client.post(f"/customers/{cid}/suspend", json={})

    # Second suspend should return the customer unchanged (idempotent).
    response = client.post(f"/customers/{cid}/suspend", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_list_customers_only_returns_tenant_customers(client):
    """All returned customers must belong to the test tenant (RLS via context var)."""
    response = client.get("/customers")
    assert response.status_code == 200
    for item in response.json()["items"]:
        # FastAPI serialises UUID fields as lowercase hex strings.
        assert item["tenant_id"].replace("-", "") == str(_TENANT_ID).replace("-", "")
