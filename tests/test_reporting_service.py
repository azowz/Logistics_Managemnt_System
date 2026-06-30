"""Behavioral tests for ProjectionService updaters (SQLite)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.events.envelope import EventEnvelope
from app.services.projection_service import ProjectionService
from reporting_sqlite import make_engine, seed_customer, seed_invoice, seed_tenant

_TENANT = uuid.uuid4()
_CUSTOMER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
_WHEN = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant(_Session, tenant_id=_TENANT)
    seed_customer(_Session, tenant_id=_TENANT, customer_id=_CUSTOMER)


def _env(event_type, payload=None, *, tenant=_TENANT, occurred=_WHEN, aggregate_id=None):
    return EventEnvelope(
        event_id=uuid.uuid4(), tenant_id=tenant, aggregate_type="X",
        aggregate_id=aggregate_id or uuid.uuid4(), aggregate_version=1,
        event_type=event_type, event_version=1, payload=payload or {}, occurred_at=occurred,
    )


def _apply(svc, *envs):
    for e in envs:
        svc.handle_domain_event(e)


def test_shipment_performance_counters_and_rates():
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("ShipmentCreated"), _env("ShipmentCreated"), _env("ShipmentCreated"), _env("ShipmentCreated"),
               _env("ShipmentDelayed"), _env("ShipmentDelivered"), _env("ShipmentFailed"))
        s.commit()
        from app.repositories.projection_repository import ShipmentPerformanceProjectionRepository
        r = ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date())
        assert r.total_shipments == 4
        assert r.delayed_shipments == 1 and r.failed_shipments == 1
        assert r.delay_rate == Decimal("0.2500") and r.failure_rate == Decimal("0.2500")
    finally:
        s.close()


def test_financial_summary_amounts():
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("QuoteCreated", {"total_amount": "500.00"}),
               _env("InvoiceIssued", {"total_amount": "1000.00"}),
               _env("PaymentRecorded", {"amount": "400.00"}),
               _env("PaymentRecorded", {"amount": "100.00"}),
               _env("PenaltyApplied", {"amount": "50.00"}),
               _env("SettlementSettled", {"amount": "200.00"}),
               _env("ClaimSettlementConsumed", {"adjustment_amount": "75.00"}))
        s.commit()
        from app.repositories.projection_repository import FinancialSummaryProjectionRepository
        r = FinancialSummaryProjectionRepository(s).get_or_create(_TENANT, _WHEN.date(), "SAR")
        assert r.total_quotes == 1 and r.issued_invoices == 1
        assert r.gross_revenue == Decimal("1000.00")
        assert r.collected_revenue == Decimal("500.00")
        assert r.outstanding_amount == Decimal("500.00")
        assert r.penalties_amount == Decimal("50.00")
        assert r.settlement_amount == Decimal("200.00")
        assert r.claim_adjustments == Decimal("75.00")
    finally:
        s.close()


def test_claims_metrics_open_recompute():
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("ClaimCreated"), _env("ClaimCreated"), _env("ClaimCreated"),
               _env("ClaimApproved", {"approved_amount": "300.00"}),
               _env("ClaimSettled", {"approved_amount": "300.00"}),
               _env("ClaimRejected"))
        s.commit()
        from app.repositories.projection_repository import ClaimsMetricsProjectionRepository
        r = ClaimsMetricsProjectionRepository(s).get_or_create(_TENANT, _WHEN.date(), "SAR")
        assert r.total_claims == 3 and r.settled_claims == 1 and r.rejected_claims == 1
        assert r.open_claims == 1  # 3 - 1 - 1
        assert r.total_settled_amount == Decimal("300.00")
    finally:
        s.close()


def test_compliance_metrics_counters():
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("PermitCreated"), _env("PermitApproved"), _env("PermitExpired"),
               _env("DispatchBlockedByCompliance"), _env("ComplianceOverrideApplied"))
        s.commit()
        from app.repositories.projection_repository import ComplianceMetricsProjectionRepository
        r = ComplianceMetricsProjectionRepository(s).get_or_create(_TENANT, _WHEN.date())
        assert r.permits_created == 1 and r.permits_approved == 1 and r.permits_expired == 1
        assert r.dispatch_blocks == 1 and r.override_count == 1
    finally:
        s.close()


def test_notification_deliverability_rates():
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("NotificationCreated"), _env("NotificationCreated"), _env("NotificationCreated"),
               _env("NotificationCreated"),
               _env("NotificationSent", {"channel": "in_app"}),
               _env("NotificationFailed", {"channel": "email"}),
               _env("NotificationRead"))
        s.commit()
        from app.repositories.projection_repository import NotificationDeliverabilityProjectionRepository
        r = NotificationDeliverabilityProjectionRepository(s).get_or_create(_TENANT, _WHEN.date())
        assert r.total_notifications == 4 and r.in_app_sent == 1 and r.email_failed == 1
        assert r.read_rate == Decimal("0.2500") and r.failure_rate == Decimal("0.2500")
    finally:
        s.close()


def test_operations_dashboard_active_clamped():
    t_ops = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t_ops)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("ShipmentCreated", tenant=t_ops),
               _env("ShipmentDelivered", tenant=t_ops),
               _env("ShipmentDelivered", tenant=t_ops))
        s.commit()
        from app.repositories.projection_repository import OperationsDashboardProjectionRepository
        r = OperationsDashboardProjectionRepository(s).get_for_tenant(t_ops)
        assert r.active_shipments == 0  # 1 created, 2 terminal -> clamped at 0, not negative
    finally:
        s.close()


def test_ar_aging_read_through_buckets():
    s = _Session()
    try:
        inv_cur = uuid.uuid4()
        inv_old = uuid.uuid4()
        # current (due in the future) and >90 days overdue
        seed_invoice(_Session, tenant_id=_TENANT, invoice_id=inv_cur, customer_id=_CUSTOMER,
                     total=Decimal("100"), status="issued",
                     due_date=datetime(2026, 7, 1, tzinfo=timezone.utc))
        seed_invoice(_Session, tenant_id=_TENANT, invoice_id=inv_old, customer_id=_CUSTOMER,
                     total=Decimal("250"), status="overdue",
                     due_date=datetime(2026, 1, 1, tzinfo=timezone.utc))
        svc = ProjectionService(s)
        svc.handle_domain_event(_env("InvoiceIssued", {"invoice_id": str(inv_cur), "total_amount": "100.00"}))
        s.commit()
        from app.repositories.projection_repository import ARAgingProjectionRepository
        rows = ARAgingProjectionRepository(s).list_for_tenant(_TENANT, customer_id=_CUSTOMER)
        assert len(rows) == 1
        r = rows[0]
        assert r.current_amount == Decimal("100.00")
        assert r.days_over_90 == Decimal("250.00")
        assert r.total_outstanding == Decimal("350.00")
    finally:
        s.close()


def test_unrelated_event_is_noop():
    s = _Session()
    try:
        svc = ProjectionService(s)
        assert svc.handle_domain_event(_env("SomethingUnknown")) is False
    finally:
        s.close()
