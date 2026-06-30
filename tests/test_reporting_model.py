"""ORM-level tests for projection models (SQLite)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.projection import (
    FinancialSummaryProjection,
    OperationsDashboardProjection,
    ProjectionHealth,
    ShipmentPerformanceProjection,
)
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    S = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant(S, tenant_id=_TENANT)
    return S


def test_shipment_perf_defaults(Session):
    s = Session()
    try:
        row = ShipmentPerformanceProjection(tenant_id=_TENANT, period_date=date(2026, 6, 1))
        s.add(row)
        s.commit()
        s.refresh(row)
        assert row.total_shipments == 0 and row.delay_rate == Decimal("0")
    finally:
        s.close()


def test_shipment_perf_unique_period(Session):
    s = Session()
    try:
        s.add(ShipmentPerformanceProjection(tenant_id=_TENANT, period_date=date(2026, 6, 2)))
        s.commit()
        s.add(ShipmentPerformanceProjection(tenant_id=_TENANT, period_date=date(2026, 6, 2)))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
    finally:
        s.close()


def test_financial_unique_period_currency(Session):
    s = Session()
    try:
        s.add(FinancialSummaryProjection(tenant_id=_TENANT, period_date=date(2026, 6, 3), currency_code="SAR"))
        s.add(FinancialSummaryProjection(tenant_id=_TENANT, period_date=date(2026, 6, 3), currency_code="USD"))
        s.commit()  # same period, different currency -> allowed
        s.add(FinancialSummaryProjection(tenant_id=_TENANT, period_date=date(2026, 6, 3), currency_code="SAR"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
    finally:
        s.close()


def test_operations_dashboard_one_per_tenant(Session):
    s = Session()
    try:
        s.add(OperationsDashboardProjection(tenant_id=_TENANT))
        s.commit()
        s.add(OperationsDashboardProjection(tenant_id=_TENANT))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
    finally:
        s.close()


def test_projection_health_persist(Session):
    s = Session()
    try:
        h = ProjectionHealth(tenant_id=_TENANT, projection_name="shipment_performance", events_applied=0)
        s.add(h)
        s.commit()
        s.refresh(h)
        assert h.id is not None and h.events_applied == 0
    finally:
        s.close()
