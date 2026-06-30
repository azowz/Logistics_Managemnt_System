"""Tests for projection repositories: get_or_create, truncate, list, health."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from app.repositories.projection_repository import (
    FinancialSummaryProjectionRepository,
    ProjectionHealthRepository,
    ShipmentPerformanceProjectionRepository,
)
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()
_OTHER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    S = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant(S, tenant_id=_TENANT)
    seed_tenant(S, tenant_id=_OTHER)
    return S


def test_get_or_create_is_stable(Session):
    s = Session()
    try:
        repo = ShipmentPerformanceProjectionRepository(s)
        r1 = repo.get_or_create(_TENANT, date(2026, 6, 1))
        s.flush()
        r2 = repo.get_or_create(_TENANT, date(2026, 6, 1))
        assert r1 is r2  # same row, not a duplicate
    finally:
        s.close()


def test_list_for_period_range(Session):
    s = Session()
    try:
        repo = ShipmentPerformanceProjectionRepository(s)
        for d in (date(2026, 5, 1), date(2026, 5, 15), date(2026, 6, 1)):
            repo.get_or_create(_TENANT, d)
        s.commit()
        rows = repo.list_for_period(_TENANT, start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert len(rows) == 2
    finally:
        s.close()


def test_truncate_is_tenant_scoped(Session):
    s = Session()
    try:
        repo = FinancialSummaryProjectionRepository(s)
        repo.get_or_create(_TENANT, date(2026, 6, 1))
        repo.get_or_create(_OTHER, date(2026, 6, 1))
        s.commit()
        removed = repo.truncate_for_tenant(_TENANT)
        s.commit()
        assert removed == 1
        assert repo.count_for_tenant(_TENANT) == 0
        assert repo.count_for_tenant(_OTHER) == 1  # other tenant untouched
    finally:
        s.close()


def test_health_get_or_create_and_list(Session):
    s = Session()
    try:
        repo = ProjectionHealthRepository(s)
        h = repo.get_or_create(_TENANT, "claims_metrics")
        h.events_applied = 5
        s.commit()
        again = repo.get_or_create(_TENANT, "claims_metrics")
        assert again.events_applied == 5
        assert any(x.projection_name == "claims_metrics" for x in repo.list_for_tenant(_TENANT))
    finally:
        s.close()
