"""Sprint 12 — event enrichment & analytics hardening tests (SQLite).

Covers, end to end:
  * backward compatibility — pre-enrichment payloads (missing the new keys) still
    deserialize, and every enriched event stays at ``event_version == 1``;
  * multi-currency financial + claims projections never mix currencies and honor the
    currency filter;
  * claims money + cycle-days running average; shipment on-time/late + delivery duration;
  * unread-urgent operations badge from notification priority;
  * projection-health transitions (healthy → stale) and rebuild bookkeeping.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.events.envelope import EventEnvelope
from app.events.registry import event_registry
from app.repositories.projection_repository import (
    ClaimsMetricsProjectionRepository,
    FinancialSummaryProjectionRepository,
    OperationsDashboardProjectionRepository,
    ProjectionHealthRepository,
    ShipmentPerformanceProjectionRepository,
)
from app.services.projection_service import ProjectionService
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
_WHEN = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant(_Session, tenant_id=_TENANT)


def _env(event_type, payload=None, *, tenant=_TENANT, occurred=_WHEN):
    return EventEnvelope(
        event_id=uuid.uuid4(), tenant_id=tenant, aggregate_type="X",
        aggregate_id=uuid.uuid4(), aggregate_version=1,
        event_type=event_type, event_version=1, payload=payload or {}, occurred_at=occurred,
    )


def _apply(svc, *envs):
    for e in envs:
        svc.handle_domain_event(e)


# --------------------------------------------------------------------------- #
# Backward compatibility
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("event_type, old_payload", [
    ("ShipmentDelivered", {"shipment_id": str(uuid.uuid4()), "tenant_id": str(_TENANT),
                           "delivered_at": None, "previous_status": "in_transit"}),
    ("InvoiceIssued", {"invoice_id": str(uuid.uuid4()), "tenant_id": str(_TENANT),
                       "previous_status": "draft", "total_amount": "100.00"}),
    ("ClaimCreated", {"claim_id": str(uuid.uuid4()), "tenant_id": str(_TENANT), "claim_number": "C1",
                      "claim_type": "damage", "status": "open", "shipment_id": None, "equipment_id": None}),
    ("ClaimSettled", {"claim_id": str(uuid.uuid4()), "tenant_id": str(_TENANT),
                      "previous_status": "approved", "approved_amount": "50.00"}),
    ("NotificationCreated", {"notification_id": str(uuid.uuid4()), "tenant_id": str(_TENANT),
                             "channel": "in_app", "status": "pending", "source_event_type": None,
                             "recipient_user_id": None}),
    ("SettlementSettled", {"settlement_id": str(uuid.uuid4()), "tenant_id": str(_TENANT),
                           "previous_status": "approved", "amount": "10.00"}),
    ("ClaimSettlementConsumed", {"settlement_id": str(uuid.uuid4()), "tenant_id": str(_TENANT),
                                 "claim_id": str(uuid.uuid4()), "amount": "10.00", "invoice_id": None,
                                 "adjustment_amount": None}),
])
def test_old_payload_deserializes_with_enriched_fields_as_none(event_type, old_payload):
    """A pre-Sprint-12 payload (no enriched keys) still rehydrates; new fields → None."""
    cls = event_registry.get(event_type, 1)
    event = cls.from_payload(old_payload)
    assert event is not None
    # The new enriched attributes exist and default to None for old payloads.
    for attr in ("currency_code", "delay_minutes", "picked_up_at", "claimed_amount",
                 "cycle_days", "priority"):
        if hasattr(event, attr):
            assert getattr(event, attr) is None


def test_enriched_events_stay_version_one():
    """Enrichment must not bump event_version (no upcaster registered → would break replay)."""
    for et in ("ShipmentDelivered", "InvoiceIssued", "InvoicePaid", "InvoiceOverdue",
               "PaymentRecorded", "PenaltyApplied", "SettlementSettled", "ClaimSettlementConsumed",
               "QuoteCreated", "QuoteApproved", "ClaimCreated", "ClaimApproved", "ClaimSettled",
               "NotificationCreated", "NotificationRead"):
        assert event_registry.get(et, 1).event_version == 1


def test_new_payload_roundtrips_through_event_store_envelope():
    """An enriched payload survives to_payload → from_payload unchanged."""
    cls = event_registry.get("ShipmentDelivered", 1)
    inst = cls(
        shipment_id=uuid.uuid4(), tenant_id=_TENANT, delivered_at=_WHEN.isoformat(),
        previous_status="in_transit", planned_delivery_at=_WHEN.isoformat(),
        picked_up_at=_WHEN.isoformat(), delay_minutes=30, order_id=uuid.uuid4(), customer_id=uuid.uuid4(),
    )
    back = cls.from_payload(inst.to_payload())
    assert back.delay_minutes == 30
    assert back.planned_delivery_at == _WHEN.isoformat()


# --------------------------------------------------------------------------- #
# Multi-currency financial summary
# --------------------------------------------------------------------------- #


def test_financial_summary_does_not_mix_currencies():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("InvoiceIssued", {"total_amount": "1000.00", "currency_code": "USD"}, tenant=t),
               _env("PaymentRecorded", {"amount": "400.00", "currency_code": "USD"}, tenant=t),
               _env("InvoiceIssued", {"total_amount": "500.00", "currency_code": "SAR"}, tenant=t),
               _env("PaymentRecorded", {"amount": "500.00", "currency_code": "SAR"}, tenant=t))
        s.commit()
        repo = FinancialSummaryProjectionRepository(s)
        usd = repo.get_or_create(t, _WHEN.date(), "USD")
        sar = repo.get_or_create(t, _WHEN.date(), "SAR")
        assert usd.gross_revenue == Decimal("1000.00") and usd.collected_revenue == Decimal("400.00")
        assert sar.gross_revenue == Decimal("500.00") and sar.collected_revenue == Decimal("500.00")
        # The currency filter narrows to one row.
        usd_only = repo.list_for_period(t, currency_code="USD")
        assert len(usd_only) == 1 and usd_only[0].currency_code == "USD"
    finally:
        s.close()


def test_missing_currency_falls_back_to_sar():
    """Historical events with no currency_code collapse to the SAR bucket (legacy behaviour)."""
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc, _env("InvoiceIssued", {"total_amount": "200.00"}, tenant=t))  # no currency_code
        s.commit()
        sar = FinancialSummaryProjectionRepository(s).get_or_create(t, _WHEN.date(), "SAR")
        assert sar.gross_revenue == Decimal("200.00")
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Claims money + cycle-days running average
# --------------------------------------------------------------------------- #


def test_claims_metrics_money_and_cycle_average():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("ClaimCreated", {"claimed_amount": "300.00", "currency_code": "SAR"}, tenant=t),
               _env("ClaimCreated", {"claimed_amount": "100.00", "currency_code": "SAR"}, tenant=t),
               _env("ClaimApproved", {"approved_amount": "250.00", "currency_code": "SAR"}, tenant=t),
               _env("ClaimSettled", {"approved_amount": "250.00", "currency_code": "SAR", "cycle_days": 10}, tenant=t),
               _env("ClaimSettled", {"approved_amount": "0.00", "currency_code": "SAR", "cycle_days": 20}, tenant=t))
        s.commit()
        r = ClaimsMetricsProjectionRepository(s).get_or_create(t, _WHEN.date(), "SAR")
        assert r.total_claims == 2
        assert r.total_claimed_amount == Decimal("400.00")
        assert r.settled_claims == 2
        assert r.average_claim_cycle_days == Decimal("15.00")  # mean(10, 20)
        assert r.claim_cycle_sample_count == 2
    finally:
        s.close()


def test_claims_cycle_ignores_missing_cycle_days():
    """A settled claim without cycle_days leaves the average and sample count untouched."""
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("ClaimSettled", {"approved_amount": "0.00", "cycle_days": 12}, tenant=t),
               _env("ClaimSettled", {"approved_amount": "0.00"}, tenant=t))  # no cycle_days
        s.commit()
        r = ClaimsMetricsProjectionRepository(s).get_or_create(t, _WHEN.date(), "SAR")
        assert r.settled_claims == 2
        assert r.average_claim_cycle_days == Decimal("12.00")
        assert r.claim_cycle_sample_count == 1
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Shipment on-time/late + delivery duration
# --------------------------------------------------------------------------- #


def test_shipment_on_time_late_and_duration():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    picked = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
    delivered = datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc)  # 150 minutes
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("ShipmentDelivered", {"delay_minutes": 0, "picked_up_at": picked.isoformat(),
                                          "delivered_at": delivered.isoformat()}, tenant=t),
               _env("ShipmentDelivered", {"delay_minutes": 45, "picked_up_at": picked.isoformat(),
                                          "delivered_at": delivered.isoformat()}, tenant=t),
               _env("ShipmentDelivered", {}, tenant=t))  # legacy: no timing → contributes to neither
        s.commit()
        r = ShipmentPerformanceProjectionRepository(s).get_or_create(t, _WHEN.date())
        assert r.delivered_shipments == 3
        assert r.on_time_deliveries == 1 and r.late_deliveries == 1
        assert r.delivery_duration_sample_count == 2
        assert r.average_delivery_duration_minutes == Decimal("150.00")
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Operations dashboard — unread urgent notifications
# --------------------------------------------------------------------------- #


def test_unread_urgent_notifications_badge():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc,
               _env("NotificationCreated", {"channel": "in_app", "priority": "urgent"}, tenant=t),
               _env("NotificationCreated", {"channel": "in_app", "priority": "high"}, tenant=t),
               _env("NotificationCreated", {"channel": "in_app", "priority": "normal"}, tenant=t),
               _env("NotificationRead", {"priority": "urgent"}, tenant=t))
        s.commit()
        r = OperationsDashboardProjectionRepository(s).get_for_tenant(t)
        assert r.unread_urgent_notifications == 1  # 2 urgent/high created, 1 urgent read
    finally:
        s.close()


def test_unread_urgent_clamps_at_zero():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc, _env("NotificationRead", {"priority": "urgent"}, tenant=t))  # read with none outstanding
        s.commit()
        r = OperationsDashboardProjectionRepository(s).get_for_tenant(t)
        assert r.unread_urgent_notifications == 0
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Projection health automation
# --------------------------------------------------------------------------- #


def test_bump_health_sets_status_and_occurrence():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc, _env("ShipmentCreated", tenant=t, occurred=_WHEN))
        s.commit()
        h = ProjectionHealthRepository(s).get_or_create(t, "shipment_performance")
        assert h.status == "healthy"
        assert h.last_success_at is not None
        assert h.last_event_occurred_at.replace(tzinfo=timezone.utc) == _WHEN
        assert h.events_applied >= 1
    finally:
        s.close()


def test_run_health_check_marks_stale():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        _apply(svc, _env("ShipmentCreated", tenant=t, occurred=_WHEN))
        s.commit()
        # A "now" well past the staleness window flips the row to stale.
        future = _WHEN + timedelta(hours=12)
        summary = svc.run_health_check(t, now=future)
        s.commit()
        assert summary["stale"] >= 1
        h = ProjectionHealthRepository(s).get_or_create(t, "shipment_performance")
        assert h.status == "stale"
        # A "now" within the window restores healthy.
        svc.run_health_check(t, now=_WHEN + timedelta(minutes=5))
        s.commit()
        h2 = ProjectionHealthRepository(s).get_or_create(t, "shipment_performance")
        assert h2.status == "healthy"
    finally:
        s.close()


def test_rebuild_bumps_rebuild_count():
    t = uuid.uuid4()
    seed_tenant(_Session, tenant_id=t)
    s = _Session()
    try:
        svc = ProjectionService(s)
        svc._stamp_rebuilt(t, ["shipment_performance"])
        svc._stamp_rebuilt(t, ["shipment_performance"])
        s.commit()
        h = ProjectionHealthRepository(s).get_or_create(t, "shipment_performance")
        assert h.rebuild_count == 2
        assert h.last_rebuilt_at is not None
        assert h.status == "healthy"
    finally:
        s.close()


class _NullCtx:
    """Minimal context manager yielding a sentinel 'session' for the runner under test."""

    def __enter__(self):
        return "session"

    def __exit__(self, *exc):
        return False


def test_run_projection_health_check_aggregates_per_tenant(monkeypatch):
    """The sweep visits every tenant and sums their per-tenant health summaries."""
    from app.analytics import health as health_mod

    t1, t2 = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(health_mod, "_distinct_tenant_ids", lambda: [t1, t2])
    monkeypatch.setattr(health_mod, "session_scope", lambda *_a, **_k: _NullCtx())

    class _StubSvc:
        def __init__(self, _session):
            pass

        def run_health_check(self, tenant_id, *, now=None):
            return {"tenant_id": str(tenant_id), "checked": 7, "healthy": 5, "stale": 2, "error": 0}

    monkeypatch.setattr(health_mod, "ProjectionService", _StubSvc)
    result = health_mod.run_projection_health_check()
    assert result.tenants == 2
    assert result.checked == 14 and result.healthy == 10 and result.stale == 4


def test_run_projection_health_check_isolates_tenant_failures(monkeypatch):
    """One tenant raising must not stall the sweep; the failure is swallowed and skipped."""
    from app.analytics import health as health_mod

    t1, t2 = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(health_mod, "_distinct_tenant_ids", lambda: [t1, t2])
    monkeypatch.setattr(health_mod, "session_scope", lambda *_a, **_k: _NullCtx())

    class _StubSvc:
        def __init__(self, _session):
            pass

        def run_health_check(self, tenant_id, *, now=None):
            if tenant_id == t1:
                raise RuntimeError("boom")
            return {"tenant_id": str(tenant_id), "checked": 3, "healthy": 3, "stale": 0, "error": 0}

    monkeypatch.setattr(health_mod, "ProjectionService", _StubSvc)
    result = health_mod.run_projection_health_check()
    assert result.tenants == 2       # both visited
    assert result.checked == 3       # only the surviving tenant contributed


def test_notification_created_emit_carries_priority():
    """Emit-site: NotificationCreated carries the notification's own priority."""
    from unittest.mock import MagicMock, patch
    from app.models.enums import NotificationChannel, NotificationStatus, NotificationPriority

    with patch("app.services.notification_service.EventStoreRepository") as ME, \
         patch("app.services.notification_service.get_current_user_id", return_value=uuid.uuid4()):
        from app.services.notification_service import NotificationService
        svc = NotificationService(MagicMock())
        svc._event_repo = ME.return_value
        svc._event_repo.next_aggregate_version.return_value = 1
        n = MagicMock()
        n.id = uuid.uuid4()
        n.channel = NotificationChannel.IN_APP
        n.status = NotificationStatus.PENDING
        n.event_type = None
        n.recipient_user_id = None
        n.priority = NotificationPriority.URGENT
        svc._emit_created(n, _TENANT)

    env = svc._event_repo.append.call_args.args[0]
    assert env.event_type == "NotificationCreated"
    assert env.payload["priority"] == "urgent"


def test_health_check_task_wrapper_returns_summary(monkeypatch):
    """The celery task is a thin wrapper that surfaces the runner's aggregate summary."""
    from app.analytics import health as health_mod
    import app.workers.tasks as tasks

    monkeypatch.setattr(
        health_mod, "run_projection_health_check",
        lambda: health_mod.HealthCheckResult(tenants=2, checked=14, healthy=12, stale=2, error=0),
    )
    out = tasks.projection_health_check()
    assert out == {"tenants": 2, "checked": 14, "healthy": 12, "stale": 2, "error": 0}
