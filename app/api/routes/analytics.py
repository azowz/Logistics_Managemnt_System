"""Reporting & Analytics API routes — dashboard reads + ADMIN projection rebuild.

Read-only except the rebuild endpoints. Literal paths precede dynamic ones.
Reads serve from projection tables (fast); they never scan the raw event store
and never expose raw event payloads.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import UserRole
from app.schemas.analytics import (
    ARAgingRead,
    ClaimsMetricsRead,
    ComplianceMetricsRead,
    DashboardSummaryRead,
    FinancialSummaryRead,
    NotificationDeliverabilityRead,
    ProjectionHealthRead,
    ProjectionRebuildRequest,
    ProjectionRebuildResult,
    ShipmentPerformanceRead,
)
from app.services.projection_service import ProjectionService

router = APIRouter(prefix="/analytics", tags=["analytics"])

_READ = (UserRole.ADMIN, UserRole.MANAGER)
_REBUILD = (UserRole.ADMIN,)


def _validate_range(start_date: Optional[date], end_date: Optional[date]) -> None:
    from app.schemas.analytics import AnalyticsDateRangeParams
    AnalyticsDateRangeParams(start_date=start_date, end_date=end_date)  # raises on invalid


# --- dashboard + reads (literal paths) -------------------------------------


@router.get("/dashboard", response_model=Optional[DashboardSummaryRead], summary="Tenant operations dashboard summary.")
def get_dashboard(session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_READ))) -> Optional[DashboardSummaryRead]:
    row = ProjectionService(session).get_dashboard_summary()
    return DashboardSummaryRead.model_validate(row) if row is not None else None


@router.get("/shipments/performance", response_model=list[ShipmentPerformanceRead],
            summary="Shipment performance by period.")
def shipment_performance(start_date: Optional[date] = Query(default=None),
                         end_date: Optional[date] = Query(default=None),
                         session: Session = Depends(get_session),
                         current_user=Depends(require_roles(*_READ))) -> list[ShipmentPerformanceRead]:
    _validate_range(start_date, end_date)
    rows = ProjectionService(session).get_shipment_performance(start=start_date, end=end_date)
    return [ShipmentPerformanceRead.model_validate(r) for r in rows]


@router.get("/financial/summary", response_model=list[FinancialSummaryRead], summary="Financial summary by period.")
def financial_summary(start_date: Optional[date] = Query(default=None),
                      end_date: Optional[date] = Query(default=None),
                      session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_READ))) -> list[FinancialSummaryRead]:
    _validate_range(start_date, end_date)
    rows = ProjectionService(session).get_financial_summary(start=start_date, end=end_date)
    return [FinancialSummaryRead.model_validate(r) for r in rows]


@router.get("/financial/ar-aging", response_model=list[ARAgingRead], summary="Accounts-receivable aging.")
def ar_aging(customer_id: Optional[str] = Query(default=None),
             currency_code: Optional[str] = Query(default=None, min_length=3, max_length=3),
             session: Session = Depends(get_session),
             current_user=Depends(require_roles(*_READ))) -> list[ARAgingRead]:
    rows = ProjectionService(session).get_ar_aging(
        customer_id=customer_id, currency_code=currency_code.upper() if currency_code else None)
    return [ARAgingRead.model_validate(r) for r in rows]


@router.get("/claims/metrics", response_model=list[ClaimsMetricsRead], summary="Claims metrics by period.")
def claims_metrics(start_date: Optional[date] = Query(default=None),
                   end_date: Optional[date] = Query(default=None),
                   session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_READ))) -> list[ClaimsMetricsRead]:
    _validate_range(start_date, end_date)
    rows = ProjectionService(session).get_claims_metrics(start=start_date, end=end_date)
    return [ClaimsMetricsRead.model_validate(r) for r in rows]


@router.get("/compliance/metrics", response_model=list[ComplianceMetricsRead], summary="Compliance metrics by period.")
def compliance_metrics(start_date: Optional[date] = Query(default=None),
                       end_date: Optional[date] = Query(default=None),
                       session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_READ))) -> list[ComplianceMetricsRead]:
    _validate_range(start_date, end_date)
    rows = ProjectionService(session).get_compliance_metrics(start=start_date, end=end_date)
    return [ComplianceMetricsRead.model_validate(r) for r in rows]


@router.get("/notifications/deliverability", response_model=list[NotificationDeliverabilityRead],
            summary="Notification deliverability by period.")
def notification_deliverability(start_date: Optional[date] = Query(default=None),
                                end_date: Optional[date] = Query(default=None),
                                session: Session = Depends(get_session),
                                current_user=Depends(require_roles(*_READ))) -> list[NotificationDeliverabilityRead]:
    _validate_range(start_date, end_date)
    rows = ProjectionService(session).get_notification_deliverability(start=start_date, end=end_date)
    return [NotificationDeliverabilityRead.model_validate(r) for r in rows]


@router.get("/projections/health", response_model=list[ProjectionHealthRead], summary="Projection health.")
def projection_health(session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_READ))) -> list[ProjectionHealthRead]:
    return [ProjectionHealthRead.model_validate(r) for r in ProjectionService(session).get_projection_health()]


# --- rebuild (ADMIN only; literal before dynamic) --------------------------


@router.post("/projections/rebuild", response_model=ProjectionRebuildResult,
             summary="Rebuild all projections for the current tenant.")
def rebuild_all(payload: ProjectionRebuildRequest, session: Session = Depends(get_session),
                current_user=Depends(require_roles(*_REBUILD))) -> ProjectionRebuildResult:
    return ProjectionRebuildResult(**ProjectionService(session).rebuild_all_projections(dry_run=payload.dry_run))


@router.post("/projections/rebuild/{projection_type}", response_model=ProjectionRebuildResult,
             summary="Rebuild a single projection type for the current tenant.")
def rebuild_one(projection_type: str, payload: ProjectionRebuildRequest, session: Session = Depends(get_session),
                current_user=Depends(require_roles(*_REBUILD))) -> ProjectionRebuildResult:
    return ProjectionRebuildResult(**ProjectionService(session).rebuild_projection(projection_type, dry_run=payload.dry_run))
