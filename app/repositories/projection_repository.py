"""Repositories for Reporting & Analytics projections (Sprint 11).

Constructor takes ``Session``; never commit/flush/rollback; no FastAPI; no events.
Reads are tenant-scoped via RLS. ``get_or_create`` returns an existing projection
row for a key or stages a new zeroed one (the caller/service flushes so a
subsequent lookup in the same transaction sees it — important for rebuild replay).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional, Tuple, Type

from sqlalchemy import Integer, Numeric, asc, delete, desc, func, select
from sqlalchemy.orm import Session

from app.models.projection import (
    ARAgingProjection,
    ClaimsMetricsProjection,
    ComplianceMetricsProjection,
    FinancialSummaryProjection,
    NotificationDeliverabilityProjection,
    OperationsDashboardProjection,
    ProjectionHealth,
    ShipmentPerformanceProjection,
)


class _BaseProjectionRepo:
    model: Type = None

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_or_create(self, **key):
        stmt = select(self.model)
        for col, val in key.items():
            stmt = stmt.where(getattr(self.model, col) == val)
        row = self._session.scalars(stmt).first()
        if row is None:
            row = self.model(**key)
            # Numeric server_defaults only materialize on the DB at flush; seed the
            # in-memory counters/amounts to 0 so the service can increment a fresh
            # row before flushing (matters for rebuild replay within one transaction).
            for col in self.model.__table__.columns:
                if col.name in key or col.primary_key:
                    continue
                if isinstance(col.type, (Integer, Numeric)) and getattr(row, col.name, None) is None:
                    setattr(row, col.name, 0)
            self._session.add(row)
        return row

    def truncate_for_tenant(self, tenant_id: uuid.UUID) -> int:
        result = self._session.execute(
            delete(self.model).where(self.model.tenant_id == tenant_id)
        )
        return int(result.rowcount or 0)

    def count_for_tenant(self, tenant_id: uuid.UUID) -> int:
        return int(self._session.scalar(
            select(func.count()).select_from(self.model).where(self.model.tenant_id == tenant_id)
        ) or 0)


class _PeriodRepoMixin:
    """List helper for period-keyed projections (filter by [start, end])."""

    def list_for_period(self, tenant_id, *, start=None, end=None, currency_code=None, sort_dir="asc", limit=400):
        stmt = select(self.model).where(self.model.tenant_id == tenant_id)
        if start is not None:
            stmt = stmt.where(self.model.period_date >= start)
        if end is not None:
            stmt = stmt.where(self.model.period_date <= end)
        # Multi-currency projections (financial_summary, claims_metrics) can be narrowed
        # to a single currency; projections without the column ignore the filter.
        if currency_code is not None and hasattr(self.model, "currency_code"):
            stmt = stmt.where(self.model.currency_code == currency_code)
        order = asc if sort_dir == "asc" else desc
        stmt = stmt.order_by(order(self.model.period_date)).limit(limit)
        return list(self._session.scalars(stmt).all())


class ShipmentPerformanceProjectionRepository(_BaseProjectionRepo, _PeriodRepoMixin):
    model = ShipmentPerformanceProjection

    def get_or_create(self, tenant_id, period_date: date):
        return self._get_or_create(tenant_id=tenant_id, period_date=period_date)


class FinancialSummaryProjectionRepository(_BaseProjectionRepo, _PeriodRepoMixin):
    model = FinancialSummaryProjection

    def get_or_create(self, tenant_id, period_date: date, currency_code: str = "SAR"):
        return self._get_or_create(tenant_id=tenant_id, period_date=period_date, currency_code=currency_code)


class ARAgingProjectionRepository(_BaseProjectionRepo):
    model = ARAgingProjection

    def get_or_create(self, tenant_id, customer_id, currency_code: str = "SAR"):
        return self._get_or_create(tenant_id=tenant_id, customer_id=customer_id, currency_code=currency_code)

    def list_for_tenant(self, tenant_id, *, customer_id=None, currency_code=None, limit=400):
        stmt = select(ARAgingProjection).where(ARAgingProjection.tenant_id == tenant_id)
        if customer_id is not None:
            stmt = stmt.where(ARAgingProjection.customer_id == customer_id)
        if currency_code is not None:
            stmt = stmt.where(ARAgingProjection.currency_code == currency_code)
        return list(self._session.scalars(stmt.limit(limit)).all())


class ClaimsMetricsProjectionRepository(_BaseProjectionRepo, _PeriodRepoMixin):
    model = ClaimsMetricsProjection

    def get_or_create(self, tenant_id, period_date: date, currency_code: str = "SAR"):
        return self._get_or_create(tenant_id=tenant_id, period_date=period_date, currency_code=currency_code)


class ComplianceMetricsProjectionRepository(_BaseProjectionRepo, _PeriodRepoMixin):
    model = ComplianceMetricsProjection

    def get_or_create(self, tenant_id, period_date: date):
        return self._get_or_create(tenant_id=tenant_id, period_date=period_date)


class NotificationDeliverabilityProjectionRepository(_BaseProjectionRepo, _PeriodRepoMixin):
    model = NotificationDeliverabilityProjection

    def get_or_create(self, tenant_id, period_date: date):
        return self._get_or_create(tenant_id=tenant_id, period_date=period_date)


class OperationsDashboardProjectionRepository(_BaseProjectionRepo):
    model = OperationsDashboardProjection

    def get_or_create(self, tenant_id):
        return self._get_or_create(tenant_id=tenant_id)

    def get_for_tenant(self, tenant_id) -> Optional[OperationsDashboardProjection]:
        return self._session.scalars(
            select(OperationsDashboardProjection).where(OperationsDashboardProjection.tenant_id == tenant_id)
        ).first()


class ProjectionHealthRepository(_BaseProjectionRepo):
    model = ProjectionHealth

    def get_or_create(self, tenant_id, projection_name: str):
        return self._get_or_create(tenant_id=tenant_id, projection_name=projection_name)

    def list_for_tenant(self, tenant_id) -> List[ProjectionHealth]:
        return list(self._session.scalars(
            select(ProjectionHealth).where(ProjectionHealth.tenant_id == tenant_id)
            .order_by(ProjectionHealth.projection_name)
        ).all())
