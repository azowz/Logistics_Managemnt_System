"""Reporting & Analytics projection service (context #20, Sprint 11, ADR-006).

Applies operational domain events to read-side projection tables. Two paths:

* **Consumer path** (`handle_domain_event`) — runs inside the event dispatcher's
  transaction (SAVEPOINT) and **never commits**; the dispatcher commits the
  projection writes together with the `processed_events` idempotency record.
* **API/rebuild path** — `rebuild_*` and the getters; rebuild commits via the
  service after truncate-then-replay (deterministic, idempotent by construction).

Projections never mutate source aggregates. AR aging is the one *read-through*
projection: billing events omit `customer_id`/`due_date`, so it reads Billing via
a read-only `InvoiceRepository` to recompute a customer's outstanding buckets.
Metrics not present in the event stream (on-time/late delivery, claim cycle days,
total_claimed_amount, urgent-unread) are left at 0 — see docs/25 known risks.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.db.tenant import get_current_tenant
from app.events.envelope import EventEnvelope
from app.models.enums import InvoiceStatus
from app.models.event_store import EventStore
from app.repositories.billing_repository import InvoiceRepository
from app.repositories.projection_repository import (
    ARAgingProjectionRepository,
    ClaimsMetricsProjectionRepository,
    ComplianceMetricsProjectionRepository,
    FinancialSummaryProjectionRepository,
    NotificationDeliverabilityProjectionRepository,
    OperationsDashboardProjectionRepository,
    ProjectionHealthRepository,
    ShipmentPerformanceProjectionRepository,
)
from app.services.exceptions import ValidationError

_ZERO = Decimal("0")

# Event-type → projection mapping. The analytics consumer subscribes to the union.
_SHIPMENT = {
    "ShipmentCreated",
    "ShipmentAssigned",
    "ShipmentPickedUp",
    "ShipmentInTransit",
    "ShipmentDelayed",
    "ShipmentDelivered",
    "ShipmentFailed",
    "ShipmentReturned",
    "ShipmentCancelled",
}
_COMPLIANCE = {
    "PermitCreated",
    "PermitApproved",
    "PermitRejected",
    "PermitExpired",
    "DispatchBlockedByCompliance",
    "DispatchClearedByCompliance",
    "ComplianceCheckFailed",
    "ComplianceOverrideApplied",
}
_CLAIMS = {
    "ClaimCreated",
    "ClaimApproved",
    "ClaimRejected",
    "ClaimSettled",
    "ClaimClosed",
    "DamageReportCreated",
    "LiabilityRecordCreated",
}
_BILLING = {
    "QuoteCreated",
    "QuoteIssued",
    "QuoteApproved",
    "QuoteExpired",
    "InvoiceCreated",
    "InvoiceIssued",
    "InvoicePartiallyPaid",
    "InvoicePaid",
    "InvoiceOverdue",
    "PaymentRecorded",
    "PaymentFailed",
    "SettlementCreated",
    "SettlementApproved",
    "SettlementSettled",
    "PenaltyApplied",
    "CancellationFeeApplied",
    "ClaimSettlementConsumed",
}
_NOTIFICATION = {
    "NotificationCreated",
    "NotificationSent",
    "NotificationFailed",
    "NotificationRetried",
    "NotificationRead",
    "NotificationDeliveryAttemptCreated",
}
_AR_AGING_EVENTS = {
    "InvoiceCreated",
    "InvoiceIssued",
    "InvoicePartiallyPaid",
    "InvoicePaid",
    "InvoiceOverdue",
    "PaymentRecorded",
}
_OPS_EVENTS = (
    _SHIPMENT
    | _CLAIMS
    | {
        "InvoiceIssued",
        "InvoicePaid",
        "PaymentRecorded",
        "DispatchBlockedByCompliance",
        "DispatchClearedByCompliance",
        "NotificationCreated",
        "NotificationRead",
    }
)

ALL_EVENT_TYPES = frozenset(_SHIPMENT | _COMPLIANCE | _CLAIMS | _BILLING | _NOTIFICATION)

# projection_type → relevant event types (for single-projection rebuild + validation).
PROJECTION_TYPES = {
    "shipment_performance": _SHIPMENT,
    "financial_summary": _BILLING,
    "ar_aging": _AR_AGING_EVENTS,
    "claims_metrics": _CLAIMS,
    "compliance_metrics": _COMPLIANCE,
    "notification_deliverability": _NOTIFICATION,
    "operations_dashboard": _OPS_EVENTS,
}


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else _ZERO
    except (ValueError, ArithmeticError):
        return _ZERO


def _rate(numerator, denominator) -> Decimal:
    d = Decimal(denominator or 0)
    if d == 0:
        return _ZERO
    return (Decimal(numerator or 0) / d).quantize(Decimal("0.0001"))


def _clamp0(value: int) -> int:
    return value if value > 0 else 0


def _currency(payload) -> str:
    """Normalize an event payload's currency to a 3-letter code, defaulting to SAR.

    Older (pre-Sprint-12) payloads omit ``currency_code`` entirely; they collapse to
    SAR, exactly the single-currency behaviour they were written under. Newer enriched
    payloads carry their real currency, so multi-currency rows never get mixed.
    """
    code = (payload or {}).get("currency_code")
    code = str(code).strip().upper() if code else ""
    return code or "SAR"


def _aware(dt: datetime) -> datetime:
    """Treat naive timestamps (e.g. SQLite round-trips) as UTC for safe subtraction."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_dt(value) -> Optional[datetime]:
    """Best-effort ISO-8601 parse of a payload timestamp; None if absent/unparseable."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


# Notification priorities that count toward the "unread urgent" operations badge.
_URGENT_PRIORITIES = {"high", "urgent"}

# Status thresholds for the scheduled projection-health check (see docs/26).
_HEALTH_STALE_AFTER = timedelta(hours=6)


class ProjectionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._ship = ShipmentPerformanceProjectionRepository(session)
        self._fin = FinancialSummaryProjectionRepository(session)
        self._ar = ARAgingProjectionRepository(session)
        self._claims = ClaimsMetricsProjectionRepository(session)
        self._comp = ComplianceMetricsProjectionRepository(session)
        self._notif = NotificationDeliverabilityProjectionRepository(session)
        self._ops = OperationsDashboardProjectionRepository(session)
        self._health = ProjectionHealthRepository(session)
        self._invoices = InvoiceRepository(session)

    # --- context ---

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    @staticmethod
    def _period(envelope: EventEnvelope) -> date:
        occurred = envelope.occurred_at
        return occurred.date() if occurred is not None else utcnow().date()

    def _bump_health(self, tenant_id, projection_name: str, envelope: EventEnvelope) -> None:
        h = self._health.get_or_create(tenant_id, projection_name)
        now = utcnow()
        h.last_event_id = envelope.event_id
        h.last_event_type = envelope.event_type
        h.last_applied_at = now
        h.events_applied = (h.events_applied or 0) + 1
        # Sprint 12: applying an event is a successful projection write — clear any prior
        # error state and record the source event's occurrence time for staleness checks.
        if envelope.occurred_at is not None:
            h.last_event_occurred_at = envelope.occurred_at
        h.last_success_at = now
        h.status = "healthy"
        h.last_error = None

    # ===================== Updaters (consumer path; no commit) =====================

    def update_shipment_performance(self, envelope: EventEnvelope) -> bool:
        et = envelope.event_type
        if et not in _SHIPMENT:
            return False
        row = self._ship.get_or_create(envelope.tenant_id, self._period(envelope))
        if et == "ShipmentCreated":
            row.total_shipments += 1
        elif et == "ShipmentAssigned":
            row.assigned_shipments += 1
        elif et == "ShipmentInTransit":
            row.in_transit_shipments += 1
        elif et == "ShipmentDelayed":
            row.delayed_shipments += 1
        elif et == "ShipmentDelivered":
            row.delivered_shipments += 1
            self._apply_delivery_timing(row, envelope.payload or {})
        elif et == "ShipmentFailed":
            row.failed_shipments += 1
        elif et == "ShipmentReturned":
            row.returned_shipments += 1
        elif et == "ShipmentCancelled":
            row.cancelled_shipments += 1
        total = row.total_shipments or 0
        row.delay_rate = _rate(row.delayed_shipments, total)
        row.failure_rate = _rate(row.failed_shipments, total)
        self._bump_health(envelope.tenant_id, "shipment_performance", envelope)
        return True

    @staticmethod
    def _apply_delivery_timing(row, payload: dict) -> None:
        """On-time/late split + incremental delivery-duration mean from enriched timing.

        Older ``ShipmentDelivered`` payloads omit ``delay_minutes`` / ``picked_up_at`` —
        those deliveries simply don't contribute to either metric (no false on-time/late
        classification, no zero-duration sample skewing the mean).
        """
        delay = payload.get("delay_minutes")
        if delay is not None:
            try:
                row.late_deliveries += 1 if int(delay) > 0 else 0
                row.on_time_deliveries += 0 if int(delay) > 0 else 1
            except (ValueError, TypeError):
                pass
        picked = _parse_dt(payload.get("picked_up_at"))
        delivered = _parse_dt(payload.get("delivered_at"))
        if picked is not None and delivered is not None:
            minutes = Decimal((delivered - picked).total_seconds()) / Decimal(60)
            if minutes >= 0:
                n = (row.delivery_duration_sample_count or 0) + 1
                prev = row.average_delivery_duration_minutes or _ZERO
                row.average_delivery_duration_minutes = (
                    (prev * (n - 1) + minutes) / Decimal(n)
                ).quantize(Decimal("0.01"))
                row.delivery_duration_sample_count = n

    def update_financial_summary(self, envelope: EventEnvelope) -> bool:
        et = envelope.event_type
        if et not in _BILLING:
            return False
        p = envelope.payload or {}
        row = self._fin.get_or_create(envelope.tenant_id, self._period(envelope), _currency(p))
        if et == "QuoteCreated":
            row.total_quotes += 1
        elif et == "QuoteApproved":
            row.approved_quotes += 1
        elif et == "InvoiceIssued":
            row.issued_invoices += 1
            row.gross_revenue += _dec(p.get("total_amount"))
        elif et == "InvoicePaid":
            row.paid_invoices += 1
        elif et == "InvoiceOverdue":
            row.overdue_invoices += 1
        elif et == "PaymentRecorded":
            row.collected_revenue += _dec(p.get("amount"))
        elif et == "SettlementSettled":
            row.settlement_amount += _dec(p.get("amount"))
        elif et == "PenaltyApplied":
            row.penalties_amount += _dec(p.get("amount"))
        elif et == "ClaimSettlementConsumed":
            row.claim_adjustments += _dec(p.get("adjustment_amount"))
        # Per-period net receivable change (not authoritative outstanding AR — see proj_ar_aging).
        row.net_receivable_change = row.gross_revenue - row.collected_revenue
        self._bump_health(envelope.tenant_id, "financial_summary", envelope)
        return True

    def update_claims_metrics(self, envelope: EventEnvelope) -> bool:
        et = envelope.event_type
        if et not in _CLAIMS:
            return False
        p = envelope.payload or {}
        row = self._claims.get_or_create(envelope.tenant_id, self._period(envelope), _currency(p))
        if et == "ClaimCreated":
            row.total_claims += 1
            row.total_claimed_amount += _dec(p.get("claimed_amount"))
        elif et == "ClaimApproved":
            row.approved_claims += 1
            row.total_approved_amount += _dec(p.get("approved_amount"))
        elif et == "ClaimRejected":
            row.rejected_claims += 1
        elif et == "ClaimSettled":
            row.settled_claims += 1
            row.total_settled_amount += _dec(p.get("approved_amount"))
            self._accumulate_cycle_days(row, p.get("cycle_days"))
        # DamageReportCreated / LiabilityRecordCreated / ClaimClosed have no metric column.
        row.open_claims = _clamp0(row.total_claims - row.settled_claims - row.rejected_claims)
        self._bump_health(envelope.tenant_id, "claims_metrics", envelope)
        return True

    @staticmethod
    def _accumulate_cycle_days(row, cycle_days) -> None:
        """Fold one settled-claim cycle length into the incremental mean.

        Only settled claims that report a ``cycle_days`` (Sprint 12 enrichment) update the
        average; older settlements without it leave ``average_claim_cycle_days`` untouched
        rather than dragging it toward zero. The dedicated sample counter keeps the running
        mean exact and rebuild-deterministic even when old/new settlements interleave.
        """
        if cycle_days is None:
            return
        try:
            sample = Decimal(int(cycle_days))
        except (ValueError, TypeError):
            return
        if sample < 0:
            return
        n = (row.claim_cycle_sample_count or 0) + 1
        prev = row.average_claim_cycle_days or _ZERO
        row.average_claim_cycle_days = ((prev * (n - 1) + sample) / Decimal(n)).quantize(
            Decimal("0.01")
        )
        row.claim_cycle_sample_count = n

    def update_compliance_metrics(self, envelope: EventEnvelope) -> bool:
        et = envelope.event_type
        if et not in _COMPLIANCE:
            return False
        row = self._comp.get_or_create(envelope.tenant_id, self._period(envelope))
        mapping = {
            "PermitCreated": "permits_created",
            "PermitApproved": "permits_approved",
            "PermitRejected": "permits_rejected",
            "PermitExpired": "permits_expired",
            "DispatchBlockedByCompliance": "dispatch_blocks",
            "DispatchClearedByCompliance": "dispatch_clears",
            "ComplianceCheckFailed": "compliance_failures",
            "ComplianceOverrideApplied": "override_count",
        }
        attr = mapping.get(et)
        if attr:
            setattr(row, attr, getattr(row, attr) + 1)
        self._bump_health(envelope.tenant_id, "compliance_metrics", envelope)
        return True

    def update_notification_deliverability(self, envelope: EventEnvelope) -> bool:
        et = envelope.event_type
        if et not in _NOTIFICATION:
            return False
        p = envelope.payload or {}
        channel = p.get("channel")
        row = self._notif.get_or_create(envelope.tenant_id, self._period(envelope))
        if et == "NotificationCreated":
            row.total_notifications += 1
        elif et == "NotificationSent":
            row.sent_notifications += 1
            if channel == "in_app":
                row.in_app_sent += 1
        elif et == "NotificationFailed":
            row.failed_notifications += 1
            per_channel = {
                "email": "email_failed",
                "sms": "sms_failed",
                "push": "push_failed",
                "webhook": "webhook_failed",
            }
            attr = per_channel.get(channel)
            if attr:
                setattr(row, attr, getattr(row, attr) + 1)
        elif et == "NotificationRead":
            row.read_notifications += 1
        elif et == "NotificationRetried":
            row.retry_count += 1
        # NotificationDeliveryAttemptCreated has no dedicated column (attempts tracked elsewhere).
        total = row.total_notifications or 0
        row.read_rate = _rate(row.read_notifications, total)
        row.failure_rate = _rate(row.failed_notifications, total)
        self._bump_health(envelope.tenant_id, "notification_deliverability", envelope)
        return True

    def update_ar_aging(self, envelope: EventEnvelope) -> bool:
        """Read-through: recompute a customer's outstanding buckets from Billing."""
        et = envelope.event_type
        if et not in _AR_AGING_EVENTS:
            return False
        p = envelope.payload or {}
        invoice = self._invoices.get_by_id(p.get("invoice_id")) if p.get("invoice_id") else None
        if (
            invoice is None
            or invoice.customer_id is None
            or invoice.tenant_id != envelope.tenant_id
        ):
            return False
        customer_id = invoice.customer_id
        currency = invoice.currency_code or "SAR"
        as_of = self._period(envelope)
        buckets = {
            "current": _ZERO,
            "1_30": _ZERO,
            "31_60": _ZERO,
            "61_90": _ZERO,
            "over_90": _ZERO,
        }
        open_states = (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE)
        for inv in self._invoices.list_invoices_for_customer(customer_id):
            if inv.currency_code != currency or inv.status not in open_states:
                continue
            balance = self._invoices.get_invoice_balance(inv)
            if balance <= 0:
                continue
            due = inv.due_date.date() if inv.due_date is not None else as_of
            overdue_days = (as_of - due).days
            if overdue_days <= 0:
                buckets["current"] += balance
            elif overdue_days <= 30:
                buckets["1_30"] += balance
            elif overdue_days <= 60:
                buckets["31_60"] += balance
            elif overdue_days <= 90:
                buckets["61_90"] += balance
            else:
                buckets["over_90"] += balance
        row = self._ar.get_or_create(envelope.tenant_id, customer_id, currency)
        row.current_amount = buckets["current"]
        row.days_1_30 = buckets["1_30"]
        row.days_31_60 = buckets["31_60"]
        row.days_61_90 = buckets["61_90"]
        row.days_over_90 = buckets["over_90"]
        row.total_outstanding = sum(buckets.values(), _ZERO)
        self._bump_health(envelope.tenant_id, "ar_aging", envelope)
        return True

    def update_operations_dashboard(self, envelope: EventEnvelope) -> bool:
        et = envelope.event_type
        if et not in _OPS_EVENTS:
            return False
        p = envelope.payload or {}
        row = self._ops.get_or_create(envelope.tenant_id)
        terminal_ship = {
            "ShipmentDelivered",
            "ShipmentFailed",
            "ShipmentReturned",
            "ShipmentCancelled",
        }
        if et == "ShipmentCreated":
            row.active_shipments += 1
        elif et in terminal_ship:
            row.active_shipments = _clamp0(row.active_shipments - 1)
            if et != "ShipmentDelivered":
                row.delayed_shipments = _clamp0(row.delayed_shipments)
        elif et == "ShipmentDelayed":
            row.delayed_shipments += 1
        elif et == "ClaimCreated":
            row.open_claims += 1
        elif et in ("ClaimSettled", "ClaimRejected", "ClaimClosed"):
            row.open_claims = _clamp0(row.open_claims - 1)
        elif et == "InvoiceIssued":
            row.outstanding_invoices += 1
        elif et == "InvoicePaid":
            row.outstanding_invoices = _clamp0(row.outstanding_invoices - 1)
        elif et == "PaymentRecorded":
            row.cumulative_collected_revenue += _dec(p.get("amount"))
        elif et == "DispatchBlockedByCompliance":
            row.pending_compliance_blocks += 1
        elif et == "DispatchClearedByCompliance":
            row.pending_compliance_blocks = _clamp0(row.pending_compliance_blocks - 1)
        elif et == "NotificationCreated":
            if (p.get("priority") or "").lower() in _URGENT_PRIORITIES:
                row.unread_urgent_notifications += 1
        elif et == "NotificationRead":
            if (p.get("priority") or "").lower() in _URGENT_PRIORITIES:
                row.unread_urgent_notifications = _clamp0(row.unread_urgent_notifications - 1)
        self._bump_health(envelope.tenant_id, "operations_dashboard", envelope)
        return True

    _UPDATERS = (
        "update_shipment_performance",
        "update_financial_summary",
        "update_ar_aging",
        "update_claims_metrics",
        "update_compliance_metrics",
        "update_notification_deliverability",
        "update_operations_dashboard",
    )

    def handle_domain_event(self, envelope: EventEnvelope) -> bool:
        """Apply one event to every relevant projection. No commit (caller owns it)."""
        applied = False
        for name in self._UPDATERS:
            if getattr(self, name)(envelope):
                applied = True
        if applied:
            self._session.flush()
        return applied

    # ===================== Rebuild (API path) =====================

    def _load_events(self, tenant_id) -> List[EventEnvelope]:
        # Deterministic replay order: occurred_at, then aggregate_version, then event_id.
        # The secondary keys make order-sensitive updaters (e.g. clamped operations-
        # dashboard counters) replay identically even when occurred_at ties.
        rows = self._session.scalars(
            select(EventStore)
            .where(EventStore.tenant_id == tenant_id)
            .order_by(EventStore.occurred_at, EventStore.aggregate_version, EventStore.event_id)
        ).all()
        return [EventEnvelope.from_record(r) for r in rows]

    _TRUNCATE_REPOS = {
        "shipment_performance": "_ship",
        "financial_summary": "_fin",
        "ar_aging": "_ar",
        "claims_metrics": "_claims",
        "compliance_metrics": "_comp",
        "notification_deliverability": "_notif",
        "operations_dashboard": "_ops",
    }

    def rebuild_all_projections(self, *, dry_run: bool = False) -> dict:
        tenant_id = self._tenant_id()
        events = self._load_events(tenant_id)
        relevant = [e for e in events if e.event_type in ALL_EVENT_TYPES]
        if dry_run:
            return {
                "tenant_id": str(tenant_id),
                "events_total": len(events),
                "events_relevant": len(relevant),
                "applied": 0,
                "dry_run": True,
            }
        for attr in self._TRUNCATE_REPOS.values():
            getattr(self, attr).truncate_for_tenant(tenant_id)
        self._session.flush()
        applied = 0
        for env in relevant:
            if self.handle_domain_event(env):
                applied += 1
        self._stamp_rebuilt(tenant_id, list(self._TRUNCATE_REPOS.keys()))
        self._session.commit()
        return {
            "tenant_id": str(tenant_id),
            "events_total": len(events),
            "events_relevant": len(relevant),
            "applied": applied,
            "dry_run": False,
        }

    def rebuild_projection(self, projection_type: str, *, dry_run: bool = False) -> dict:
        if projection_type not in PROJECTION_TYPES:
            raise ValidationError(
                f"Unknown projection_type '{projection_type}'. Valid: {', '.join(sorted(PROJECTION_TYPES))}."
            )
        tenant_id = self._tenant_id()
        event_set = PROJECTION_TYPES[projection_type]
        events = [e for e in self._load_events(tenant_id) if e.event_type in event_set]
        if dry_run:
            return {
                "tenant_id": str(tenant_id),
                "projection_type": projection_type,
                "events_relevant": len(events),
                "applied": 0,
                "dry_run": True,
            }
        getattr(self, self._TRUNCATE_REPOS[projection_type]).truncate_for_tenant(tenant_id)
        self._session.flush()
        updater = getattr(self, f"update_{projection_type}")
        applied = 0
        for env in events:
            if updater(env):
                applied += 1
                self._session.flush()
        self._stamp_rebuilt(tenant_id, [projection_type])
        self._session.commit()
        return {
            "tenant_id": str(tenant_id),
            "projection_type": projection_type,
            "events_relevant": len(events),
            "applied": applied,
            "dry_run": False,
        }

    def _stamp_rebuilt(self, tenant_id, names: Iterable[str]) -> None:
        now = utcnow()
        for name in names:
            h = self._health.get_or_create(tenant_id, name)
            h.last_rebuilt_at = now
            h.rebuild_count = (h.rebuild_count or 0) + 1
            # A successful rebuild is the strongest possible "healthy" signal.
            h.status = "healthy"
            h.last_success_at = now
            h.last_error = None

    # ===================== Getters (read-only API path) =====================

    def get_dashboard_summary(self):
        return self._ops.get_for_tenant(self._tenant_id())

    def get_shipment_performance(self, *, start=None, end=None):
        return self._ship.list_for_period(self._tenant_id(), start=start, end=end)

    def get_financial_summary(self, *, start=None, end=None, currency_code=None):
        return self._fin.list_for_period(
            self._tenant_id(), start=start, end=end, currency_code=currency_code
        )

    def get_ar_aging(self, *, customer_id=None, currency_code=None):
        return self._ar.list_for_tenant(
            self._tenant_id(), customer_id=customer_id, currency_code=currency_code
        )

    def get_claims_metrics(self, *, start=None, end=None, currency_code=None):
        return self._claims.list_for_period(
            self._tenant_id(), start=start, end=end, currency_code=currency_code
        )

    def get_compliance_metrics(self, *, start=None, end=None):
        return self._comp.list_for_period(self._tenant_id(), start=start, end=end)

    def get_notification_deliverability(self, *, start=None, end=None):
        return self._notif.list_for_period(self._tenant_id(), start=start, end=end)

    def get_projection_health(self):
        return self._health.list_for_tenant(self._tenant_id())

    # ===================== Health automation (scheduled task) =====================

    def run_health_check(self, tenant_id, *, now: Optional[datetime] = None) -> dict:
        """Non-destructive sweep: flag projections whose last applied event is stale.

        Compares each projection's newest source-event time against ``now`` and marks a
        row ``stale`` once it lags beyond :data:`_HEALTH_STALE_AFTER`. It never replays or
        rebuilds — staleness is advisory, surfaced via the health endpoint so operators can
        decide whether a rebuild is warranted. Caller owns the commit.

        Note: the ``status == "error"`` guard below is *reserved* — no code path writes an
        ``error`` status today (projection-write failures roll back inside the dispatcher
        transaction), so the guard is currently inert. It is kept so a future out-of-band
        failure-capture path composes cleanly without re-classifying a real error as stale
        or healthy. See docs/26 §4a.
        """
        now = now or utcnow()
        checked = stale = healthy = errored = 0
        for h in self._health.list_for_tenant(tenant_id):
            checked += 1
            if h.status == "error":
                errored += 1
                continue
            reference = h.last_event_occurred_at or h.last_applied_at
            if reference is not None and (now - _aware(reference)) > _HEALTH_STALE_AFTER:
                h.status = "stale"
                stale += 1
            else:
                h.status = "healthy"
                healthy += 1
        return {
            "tenant_id": str(tenant_id),
            "checked": checked,
            "healthy": healthy,
            "stale": stale,
            "error": errored,
        }
