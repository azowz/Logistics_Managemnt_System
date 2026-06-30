# 25 — Reporting & Analytics / CQRS Projections (Sprint 11)

> Status: **IMPLEMENTED & VERIFIED**. Implements context **#20 — Reporting &
> Analytics** (ADR-006 read models, ADR-007 event store + outbox). A read-side
> bounded context: it consumes the operational event stream into fast,
> rebuildable projection tables and never mutates operational truth.

---

## 1. Domain purpose

Turns the platform's domain events into dashboard-ready read models for
operations, finance, compliance, claims, and notification deliverability.
Projections are disposable and **rebuildable from `event_store`** — if a
projection is wrong, it is recomputed, never hand-edited.

## 2. CQRS projection strategy

Source domains emit events (transactional outbox). The outbox relay publishes
each event through `default_bus`; a single `analytics` consumer
(`AnalyticsProjectionHandler`) applies it to projection tables via
`ProjectionService`. The handler runs inside the dispatcher's transaction
(SAVEPOINT) and **never commits** — the dispatcher commits the projection write
together with the `processed_events` idempotency record (effectively-once). The
admin **rebuild** path commits via the service (truncate-then-replay).

## 3. Projection ownership

| Concern | Owner |
| --- | --- |
| Projection tables (8) | `app/models/projection.py` |
| Repositories | `app/repositories/projection_repository.py` (upsert-style `get_or_create`, no commit) |
| Apply / rebuild / read | `ProjectionService` (`app/services/projection_service.py`) |
| Event consumer | `AnalyticsProjectionHandler` + `register_analytics_handlers` (`app/analytics/handlers.py`) |
| API / Schemas | `app/api/routes/analytics.py`, `app/schemas/analytics.py` |

## 4. Event inputs → projections

| Projection | Fed by |
| --- | --- |
| `proj_shipment_performance` | `Shipment*` (Created/Assigned/InTransit/Delayed/Delivered/Failed/Returned/Cancelled) |
| `proj_financial_summary` | `Quote*`, `Invoice*`, `PaymentRecorded`, `SettlementSettled`, `PenaltyApplied`, `ClaimSettlementConsumed` |
| `proj_ar_aging` | `Invoice*`, `PaymentRecorded` (read-through to Billing for customer/due-date) |
| `proj_claims_metrics` | `Claim*`, `DamageReportCreated`, `LiabilityRecordCreated` |
| `proj_compliance_metrics` | `Permit*`, `Dispatch*ByCompliance`, `ComplianceCheckFailed`, `ComplianceOverrideApplied` |
| `proj_notification_deliverability` | `Notification*` (Created/Sent/Failed/Read/Retried/DeliveryAttemptCreated) |
| `proj_operations_dashboard` | union of shipment / claims / billing / compliance events (snapshot counters) |

## 5. Projection tables

`proj_shipment_performance`, `proj_financial_summary`, `proj_ar_aging`,
`proj_claims_metrics`, `proj_compliance_metrics`,
`proj_notification_deliverability`, `proj_operations_dashboard`, plus
`projection_health` (per-projection last event + counts + last-rebuilt). Period
projections key on `(tenant_id, period_date[, currency_code])`; AR aging on
`(tenant_id, customer_id, currency_code)`; operations dashboard one row per
tenant. All tenant-scoped + RLS.

## 6. Rebuild strategy

`rebuild_all_projections()` / `rebuild_projection(type)`: truncate the tenant's
projection rows, replay the tenant's `event_store` rows (ordered deterministically
by `occurred_at`, then `aggregate_version`, then `event_id`) directly through the
apply methods — bypassing the dispatcher, so no `processed_events` interaction. Strictly tenant-scoped (no cross-tenant
rebuild). `dry_run=True` returns event counts without writing. Idempotent by
construction (truncate + full replay ⇒ same result).

## 6a. Metric semantics (read me before building dashboards)

- **`proj_financial_summary.net_receivable_change`** is the *per-period* net
  receivable change (`gross issued − collected`, within that period row). It is
  **not** the authoritative outstanding AR balance and **can be negative** when a
  payment lands in a later period than the invoice. For true outstanding AR by
  customer, use **`proj_ar_aging`** (`GET /analytics/financial/ar-aging`).
- **`proj_operations_dashboard.cumulative_collected_revenue`** is a **lifetime
  running total** of confirmed payments, not a single-period figure. For
  per-period collected revenue use `proj_financial_summary.collected_revenue`.

## 7. Idempotency strategy

**Live path:** the `Dispatcher` is the *sole* idempotency boundary for live
projection updates — it dedups `(consumer="analytics", event_id)` via
`processed_events` and commits the projection write with that record, so a
replayed envelope is applied exactly once. Projection writes therefore **assume
dispatcher-controlled delivery**; `handle_domain_event` must not be invoked
directly for production live updates (doing so would bypass dedup and
double-count counters). **Rebuild path:** idempotency is achieved by
tenant-scoped truncate + deterministic replay (ordered by `occurred_at`,
`aggregate_version`, `event_id`), so recomputation is identical no matter how
many times it runs.

## 8. Dashboard APIs

`GET /analytics/dashboard`, `/shipments/performance`, `/financial/summary`,
`/financial/ar-aging`, `/claims/metrics`, `/compliance/metrics`,
`/notifications/deliverability`, `/projections/health`; `POST
/analytics/projections/rebuild` and `/projections/rebuild/{projection_type}`.
Reads serve from projection tables only (never raw `event_store`), never expose
raw event payloads, and validate date ranges (`start ≤ end`, max-span guard).

## 9. Security model & tenant isolation

`tenant_id` from request context only (no analytics endpoint accepts it from the
client); RLS on all projection tables; reads = ADMIN/MANAGER; rebuild = ADMIN
only; rebuild is tenant-scoped so it cannot touch another tenant's data; no IDOR
(all reads filter by the context tenant via RLS + service).

## 10. Performance considerations

Dashboard reads hit indexed projection rows (`tenant_id`, `period_date`,
`customer_id`), not event-store scans; rebuild (the only heavy path) is separate
from read APIs; AR aging is indexed by `customer_id`. Period projections are
small (one row per day per tenant).

## 11. Migration summary

`0014_reporting_analytics_projections_domain` (down_revision `0013`, single
head) — additive: 8 tables with named PK/FK/unique/check constraints, indexes,
and RLS (guarded by `_is_postgres()`); reversible (8 create / 8 drop). **No
source-domain table is modified.**

## 12. Test summary

Eight suites (`test_reporting_{model,repository,service,handlers,routes,rebuild,security,idempotency}.py`),
**96% coverage** of the reporting modules (model/handlers/routes 100%, repository
99%, schemas 94%, service 93%). Idempotency proven via the real `Dispatcher`;
rebuild proven deterministic + tenant-scoped. Full regression: **1330 passed,
13 skipped**.

## 13. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Metrics not present in the event stream are stored as 0: `on_time/late_deliveries`, `average_delivery_duration_minutes` (no expected-delivery date in events), `total_claimed_amount` & `average_claim_cycle_days` (no claimed amount / per-claim cycle in payloads), `unread_urgent_notifications` (no priority in `NotificationCreated`). | MEDIUM | Computed rates (delay/failure/read) are correct. Enriching the relevant events (add expected-delivery, claimed_amount, priority) is the follow-up; projections recompute on rebuild once added. |
| `proj_financial_summary` is single-currency (`SAR`): billing events omit `currency_code`. | MEDIUM | Keyed by currency already; add `currency_code` to billing event payloads to unlock multi-currency, then rebuild. |
| AR aging is a **read-through** projection (reads Billing via read-only `InvoiceRepository`) because billing events omit `customer_id`/`due_date`. | LOW | Read-only, tenant-checked, rebuildable; documented deviation from pure event-sourcing. |
| Operations-dashboard counters are best-effort live snapshots (clamped ≥0); some (delayed_shipments) can drift vs. exact open state. `cumulative_collected_revenue` is lifetime, not per-period (see §6a). | LOW | Authoritative analytics are the period projections; the dashboard is a glanceable summary, fully recomputed on rebuild (deterministic replay). |
| Full-tenant rebuild loads the tenant's events into memory. | LOW | Fine at current scale; a batched/streamed replay is a follow-up for very large tenants. |
