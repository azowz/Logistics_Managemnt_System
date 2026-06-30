"""Integration tests for Analytics API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.analytics import router as analytics_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.events.envelope import EventEnvelope
from app.models.enums import UserRole
from app.services.projection_service import ProjectionService
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_engine = make_engine()
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)
_ROLE = {"role": UserRole.ADMIN}
_WHEN = datetime(2026, 6, 10, tzinfo=timezone.utc)


def _sess() -> Iterator:
    s = _TestSession()
    try:
        yield s
    finally:
        s.close()


def _user():
    return types.SimpleNamespace(id=_USER, tenant_id=_TENANT, role=_ROLE["role"], is_active=True)


@pytest.fixture(scope="module", autouse=True)
def _seed_data():
    seed_tenant(_TestSession, tenant_id=_TENANT)
    # Pre-populate a few projection rows directly via the service apply path.
    with patch("app.services.projection_service.get_current_tenant", return_value=_TENANT):
        s = _TestSession()
        try:
            svc = ProjectionService(s)
            for et in ("ShipmentCreated", "ShipmentDelivered", "InvoiceIssued"):
                payload = {"total_amount": "100.00"} if et == "InvoiceIssued" else {}
                svc.handle_domain_event(EventEnvelope(
                    event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="X", aggregate_id=uuid.uuid4(),
                    aggregate_version=1, event_type=et, event_version=1, payload=payload, occurred_at=_WHEN))
            s.commit()
        finally:
            s.close()


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(analytics_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def ctx():
    with patch("app.services.projection_service.get_current_tenant", return_value=_TENANT):
        yield


def test_dashboard(client):
    r = client.get("/analytics/dashboard")
    assert r.status_code == 200


def test_shipment_performance(client):
    r = client.get("/analytics/shipments/performance")
    assert r.status_code == 200
    assert any(row["total_shipments"] >= 1 for row in r.json())


def test_financial_summary(client):
    r = client.get("/analytics/financial/summary")
    assert r.status_code == 200
    assert any(row["gross_revenue"] == "100.00" for row in r.json())


def test_ar_aging(client):
    assert client.get("/analytics/financial/ar-aging").status_code == 200


def test_claims_and_compliance_and_notifications(client):
    assert client.get("/analytics/claims/metrics").status_code == 200
    assert client.get("/analytics/compliance/metrics").status_code == 200
    assert client.get("/analytics/notifications/deliverability").status_code == 200


def test_projection_health(client):
    r = client.get("/analytics/projections/health")
    assert r.status_code == 200
    assert any(h["projection_name"] == "shipment_performance" for h in r.json())


def test_invalid_date_range_422(client):
    r = client.get("/analytics/financial/summary?start_date=2026-06-30&end_date=2026-06-01")
    assert r.status_code == 422


def test_rebuild_all_admin(client):
    r = client.post("/analytics/projections/rebuild", json={"dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True


def test_rebuild_one_admin(client):
    r = client.post("/analytics/projections/rebuild/shipment_performance", json={"dry_run": True})
    assert r.status_code == 200 and r.json()["projection_type"] == "shipment_performance"


def test_rebuild_invalid_type_422(client):
    r = client.post("/analytics/projections/rebuild/nope", json={})
    assert r.status_code == 422


def test_rebuild_requires_admin(client):
    _ROLE["role"] = UserRole.MANAGER
    try:
        assert client.post("/analytics/projections/rebuild", json={"dry_run": True}).status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_reads_allow_manager(client):
    _ROLE["role"] = UserRole.MANAGER
    try:
        assert client.get("/analytics/dashboard").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_reads_forbid_client(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/analytics/dashboard").status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN
