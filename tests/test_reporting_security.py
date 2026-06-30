"""Security tests for Reporting & Analytics: tenant isolation on rebuild + reads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.event_store import EventStore
from app.repositories.projection_repository import ShipmentPerformanceProjectionRepository
from app.services.projection_service import ProjectionService
from reporting_sqlite import make_engine, seed_tenant

_A = uuid.uuid4()
_B = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
_WHEN = datetime(2026, 6, 8, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant(_Session, tenant_id=_A)
    seed_tenant(_Session, tenant_id=_B)
    s = _Session()
    try:
        for tenant in (_A, _B):
            for _ in range(2):
                s.add(EventStore(event_id=uuid.uuid4(), tenant_id=tenant, aggregate_type="X",
                                 aggregate_id=uuid.uuid4(), aggregate_version=1, event_type="ShipmentCreated",
                                 event_version=1, payload={}, occurred_at=_WHEN))
        s.commit()
    finally:
        s.close()


def test_rebuild_is_tenant_scoped():
    # Rebuild only tenant A; tenant B must be untouched.
    s = _Session()
    try:
        with patch("app.services.projection_service.get_current_tenant", return_value=_A):
            ProjectionService(s).rebuild_all_projections()
        a = ShipmentPerformanceProjectionRepository(s).get_or_create(_A, _WHEN.date()).total_shipments
        assert a == 2
        # tenant B has no projection row yet (its events were never replayed)
        assert ShipmentPerformanceProjectionRepository(s).count_for_tenant(_B) == 0
    finally:
        s.close()


def test_rebuild_b_does_not_affect_a():
    s = _Session()
    try:
        with patch("app.services.projection_service.get_current_tenant", return_value=_B):
            ProjectionService(s).rebuild_all_projections()
        a = ShipmentPerformanceProjectionRepository(s).get_or_create(_A, _WHEN.date()).total_shipments
        b = ShipmentPerformanceProjectionRepository(s).get_or_create(_B, _WHEN.date()).total_shipments
        assert a == 2 and b == 2  # A preserved, B built independently
    finally:
        s.close()


def test_load_events_only_reads_current_tenant():
    s = _Session()
    try:
        with patch("app.services.projection_service.get_current_tenant", return_value=_A):
            events = ProjectionService(s)._load_events(_A)
        assert events and all(e.tenant_id == _A for e in events)
    finally:
        s.close()
