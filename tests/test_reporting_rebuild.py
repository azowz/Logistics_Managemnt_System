"""Tests for projection rebuild/backfill from the event store (Sprint 11)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.event_store import EventStore
from app.repositories.projection_repository import ShipmentPerformanceProjectionRepository
from app.services.exceptions import ValidationError
from app.services.projection_service import ProjectionService
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
_WHEN = datetime(2026, 6, 5, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant(_Session, tenant_id=_TENANT)


def _insert_event(s, event_type, *, tenant=_TENANT, payload=None, occurred=_WHEN, version=1):
    s.add(EventStore(
        event_id=uuid.uuid4(), tenant_id=tenant, aggregate_type="X", aggregate_id=uuid.uuid4(),
        aggregate_version=version, event_type=event_type, event_version=1,
        payload=payload or {}, occurred_at=occurred,
    ))


@pytest.fixture(autouse=True)
def ctx():
    with patch("app.services.projection_service.get_current_tenant", return_value=_TENANT):
        yield


def test_rebuild_all_from_event_store():
    s = _Session()
    try:
        for _ in range(3):
            _insert_event(s, "ShipmentCreated")
        _insert_event(s, "ShipmentDelivered")
        _insert_event(s, "InvoiceIssued", payload={"total_amount": "100.00"})
        s.commit()
        result = ProjectionService(s).rebuild_all_projections()
        assert result["applied"] == 5 and result["dry_run"] is False
        r = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date())
        assert r.total_shipments == 3 and r.delivered_shipments == 1
    finally:
        s.close()


def test_rebuild_is_idempotent():
    s = _Session()
    try:
        ProjectionService(s).rebuild_all_projections()
        first = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date()).total_shipments
        ProjectionService(s).rebuild_all_projections()  # truncate + replay again
        second = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date()).total_shipments
        assert first == second  # not doubled
    finally:
        s.close()


def test_dry_run_does_not_write():
    s = _Session()
    try:
        # truncate to a known state then dry-run
        ProjectionService(s).rebuild_all_projections()
        before = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date()).total_shipments
        result = ProjectionService(s).rebuild_all_projections(dry_run=True)
        assert result["dry_run"] is True and result["applied"] == 0
        after = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date()).total_shipments
        assert before == after
    finally:
        s.close()


def test_rebuild_single_projection():
    s = _Session()
    try:
        result = ProjectionService(s).rebuild_projection("shipment_performance")
        assert result["projection_type"] == "shipment_performance"
        assert result["applied"] == 4  # 3 created + 1 delivered (InvoiceIssued not relevant)
    finally:
        s.close()


def test_rebuild_unknown_type_raises():
    s = _Session()
    try:
        with pytest.raises(ValidationError):
            ProjectionService(s).rebuild_projection("bogus")
    finally:
        s.close()


def test_rebuild_deterministic_under_occurred_at_ties():
    """L1: same occurred_at -> ordered by aggregate_version so Created precedes
    Delivered, giving a stable (and correct) operations-dashboard result."""
    from app.repositories.projection_repository import OperationsDashboardProjectionRepository
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    tie = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
    s = _Session()
    try:
        # Insert Delivered (v2) BEFORE Created (v1); same timestamp. Stable sort must
        # still replay Created (v1) first -> active ends at 0, not 1.
        _insert_event(s, "ShipmentDelivered", tenant=t, occurred=tie, version=2)
        _insert_event(s, "ShipmentCreated", tenant=t, occurred=tie, version=1)
        s.commit()
        with patch("app.services.projection_service.get_current_tenant", return_value=t):
            ProjectionService(s).rebuild_all_projections()
            again = ProjectionService(s).rebuild_all_projections()  # repeat -> identical
        r = OperationsDashboardProjectionRepository(s).get_for_tenant(t)
        assert r.active_shipments == 0
        assert again["applied"] == 2
    finally:
        s.close()
