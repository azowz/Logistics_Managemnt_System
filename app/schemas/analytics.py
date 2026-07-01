"""Pydantic schemas for Reporting & Analytics (Sprint 11). Read-only DTOs."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PROJECTION_TYPES = frozenset({
    "shipment_performance", "financial_summary", "ar_aging", "claims_metrics",
    "compliance_metrics", "notification_deliverability", "operations_dashboard",
})
_MAX_RANGE_DAYS = 366 * 3  # guard against unbounded scans


def _currency(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.upper()
    if not re.fullmatch(r"[A-Z]{3}", v):
        raise ValueError("currency_code must be a 3-letter ISO-4217 code.")
    return v


# --- query params ----------------------------------------------------------


class AnalyticsDateRangeParams(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def check_range(self) -> "AnalyticsDateRangeParams":
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValueError("start_date must be on or before end_date.")
            if (self.end_date - self.start_date).days > _MAX_RANGE_DAYS:
                raise ValueError(f"Date range too large (max {_MAX_RANGE_DAYS} days).")
        return self


class AnalyticsPeriodParams(AnalyticsDateRangeParams):
    pass


# --- reads -----------------------------------------------------------------


class ShipmentPerformanceRead(BaseModel):
    tenant_id: uuid.UUID
    period_date: date
    total_shipments: int
    assigned_shipments: int
    in_transit_shipments: int
    delivered_shipments: int
    delayed_shipments: int
    failed_shipments: int
    returned_shipments: int
    cancelled_shipments: int
    on_time_deliveries: int
    late_deliveries: int
    average_delivery_duration_minutes: Decimal
    delay_rate: Decimal
    failure_rate: Decimal
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FinancialSummaryRead(BaseModel):
    tenant_id: uuid.UUID
    period_date: date
    currency_code: str
    total_quotes: int
    approved_quotes: int
    issued_invoices: int
    paid_invoices: int
    overdue_invoices: int
    gross_revenue: Decimal
    collected_revenue: Decimal
    net_receivable_change: Decimal = Field(
        description="Per-period net receivable change (gross issued − collected this period). "
                    "NOT authoritative outstanding AR — use /analytics/financial/ar-aging for that.")
    claim_adjustments: Decimal
    penalties_amount: Decimal
    settlement_amount: Decimal
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ARAgingRead(BaseModel):
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    currency_code: str
    current_amount: Decimal
    days_1_30: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    days_over_90: Decimal
    total_outstanding: Decimal
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ClaimsMetricsRead(BaseModel):
    tenant_id: uuid.UUID
    period_date: date
    currency_code: str
    total_claims: int
    approved_claims: int
    rejected_claims: int
    settled_claims: int
    open_claims: int
    total_claimed_amount: Decimal
    total_approved_amount: Decimal
    total_settled_amount: Decimal
    average_claim_cycle_days: Decimal
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ComplianceMetricsRead(BaseModel):
    tenant_id: uuid.UUID
    period_date: date
    permits_created: int
    permits_approved: int
    permits_rejected: int
    permits_expired: int
    dispatch_blocks: int
    dispatch_clears: int
    compliance_failures: int
    override_count: int
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NotificationDeliverabilityRead(BaseModel):
    tenant_id: uuid.UUID
    period_date: date
    total_notifications: int
    sent_notifications: int
    failed_notifications: int
    read_notifications: int
    retry_count: int
    in_app_sent: int
    email_failed: int
    sms_failed: int
    push_failed: int
    webhook_failed: int
    read_rate: Decimal
    failure_rate: Decimal
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DashboardSummaryRead(BaseModel):
    tenant_id: uuid.UUID
    active_shipments: int
    delayed_shipments: int
    pending_compliance_blocks: int
    unread_urgent_notifications: int
    open_claims: int
    outstanding_invoices: int
    cumulative_collected_revenue: Decimal = Field(
        description="Lifetime running total of confirmed payments (cumulative, not a single period).")
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectionHealthRead(BaseModel):
    tenant_id: uuid.UUID
    projection_name: str
    last_event_id: Optional[uuid.UUID] = None
    last_event_type: Optional[str] = None
    last_applied_at: Optional[datetime] = None
    events_applied: int
    last_rebuilt_at: Optional[datetime] = None
    # Sprint 12 health automation.
    status: str = Field(default="healthy", description="Operational status: healthy | stale | error.")
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_event_occurred_at: Optional[datetime] = None
    rebuild_count: int = 0
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# --- rebuild ---------------------------------------------------------------


class ProjectionRebuildRequest(BaseModel):
    dry_run: bool = False


class ProjectionRebuildResult(BaseModel):
    tenant_id: str
    projection_type: Optional[str] = None
    events_total: Optional[int] = None
    events_relevant: int
    applied: int
    dry_run: bool


class ARAgingQueryParams(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)
