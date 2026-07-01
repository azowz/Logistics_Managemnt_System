"""Reporting & Analytics projection models (context #20, Sprint 11, ADR-006).

Read-side CQRS projections derived from the operational event stream. These
tables are **not** operational truth — they are rebuildable from ``event_store``
and never mutate source aggregates. All are tenant-scoped (RLS) and optimized for
dashboard reads. Projections are not soft-deleted or version-locked: they are
disposable, recomputable read models.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ProjectionHealth(TimestampMixin, Base):
    """Per-(tenant, projection) health: last event applied + counters."""

    __tablename__ = "projection_health"
    __table_args__ = (
        UniqueConstraint("tenant_id", "projection_name", name="uq_projection_health_tenant_id_projection_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    projection_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_event_type: Mapped[Optional[str]] = mapped_column(String(128))
    last_applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    events_applied: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_rebuilt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Sprint 12 health automation (additive): operational status + diagnostics for the
    # scheduled projection-health check. ``status`` ∈ {healthy, stale, error}.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="healthy")
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(512))
    last_event_occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rebuild_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ShipmentPerformanceProjection(TimestampMixin, Base):
    __tablename__ = "proj_shipment_performance"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_date", name="uq_proj_shipment_performance_tenant_id_period_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    assigned_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    in_transit_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivered_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delayed_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    returned_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cancelled_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    on_time_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    late_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    average_delivery_duration_minutes: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    # Sprint 12 (additive): sample count backing the incremental delivery-duration mean.
    # Only deliveries carrying both pickup + delivery timestamps contribute, so this can
    # be < delivered_shipments. Kept internal (not exposed in the read schema).
    delivery_duration_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delay_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    failure_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")


class FinancialSummaryProjection(TimestampMixin, Base):
    __tablename__ = "proj_financial_summary"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_date", "currency_code",
                         name="uq_proj_financial_summary_tenant_period_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    total_quotes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    approved_quotes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    issued_invoices: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    paid_invoices: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    overdue_invoices: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    collected_revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    # Per-period net receivable change (gross issued − collected this period); NOT
    # the authoritative outstanding AR balance — see proj_ar_aging for that.
    net_receivable_change: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    claim_adjustments: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    penalties_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    settlement_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")


class ARAgingProjection(TimestampMixin, Base):
    __tablename__ = "proj_ar_aging"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", "currency_code",
                         name="uq_proj_ar_aging_tenant_customer_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    current_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    days_1_30: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    days_31_60: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    days_61_90: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    days_over_90: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    total_outstanding: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")


class ClaimsMetricsProjection(TimestampMixin, Base):
    __tablename__ = "proj_claims_metrics"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_date", "currency_code",
                         name="uq_proj_claims_metrics_tenant_period_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    total_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    approved_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rejected_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    settled_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    open_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_claimed_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    total_approved_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    total_settled_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
    average_claim_cycle_days: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    # Sprint 12 (additive): sample count backing the incremental claim-cycle mean. Only
    # settled claims carrying a cycle_days value contribute, so this can be < settled_claims.
    # Kept internal (not exposed in the read schema).
    claim_cycle_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ComplianceMetricsProjection(TimestampMixin, Base):
    __tablename__ = "proj_compliance_metrics"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_date", name="uq_proj_compliance_metrics_tenant_id_period_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    permits_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    permits_approved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    permits_rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    permits_expired: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dispatch_blocks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dispatch_clears: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    compliance_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    override_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class NotificationDeliverabilityProjection(TimestampMixin, Base):
    __tablename__ = "proj_notification_deliverability"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_date", name="uq_proj_notification_deliverability_tenant_id_period_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_notifications: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_notifications: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_notifications: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    read_notifications: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    in_app_sent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    email_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sms_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    push_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    webhook_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    read_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    failure_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")


class OperationsDashboardProjection(TimestampMixin, Base):
    """One snapshot row per tenant — the at-a-glance operational dashboard."""

    __tablename__ = "proj_operations_dashboard"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_proj_operations_dashboard_tenant_id"),
        CheckConstraint("active_shipments >= 0", name="active_shipments_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    active_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delayed_shipments: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pending_compliance_blocks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unread_urgent_notifications: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    open_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    outstanding_invoices: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Cumulative collected revenue (lifetime running sum of confirmed payments), not a period figure.
    cumulative_collected_revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, server_default="0")
