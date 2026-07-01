# 26 — Event Enrichment & Analytics Hardening (Sprint 12)

> Status: **IMPLEMENTED & VERIFIED**. A cross-cutting hardening sprint, not a new
> bounded context. It makes the dashboards built in Sprint 11 (docs/25) *truthful*
> by enriching domain-event payloads with the data the projections were forced to
> store as `0`, hardening the projection handlers to consume it, making the
> financial/claims read models genuinely multi-currency, and adding non-destructive
> projection-health automation. Nothing in the event backbone (ADR-007) is
> redesigned.

---

## 1. Core rule — backward compatibility above all

The event store is an append-only ledger of *historical* facts. Sprint 12 therefore
obeys one non-negotiable rule:

- **No historical event row is mutated.**
- **No event payload is made incompatible.** Every enrichment is an *additive*
  `Optional[...] = None` field on the event dataclass.
- **`event_version` stays at `1` for every enriched event.**

Why version stays at 1: `DomainEvent.from_payload` reads each field via
`payload.get(name)`, so a key absent from an older payload deserializes to `None` —
appending optional fields is transparently forward/backward compatible. Conversely,
`EventRegistry.upcast` *raises* `EventDeserializationError` if it sees a higher
`event_version` with no registered upcaster. Bumping the version would therefore
**break replay of every historical row**. Additive-optional-at-v1 is the lowest-risk
path and the one taken here.

> Net effect: a consumer written before Sprint 12 still works; a consumer written
> after Sprint 12 tolerates both the old (sparse) and new (enriched) payloads.

---

## 2. Event enrichment (additive, v1-compatible)

| Event | Added fields | Used by |
| --- | --- | --- |
| `ShipmentDelivered` | `planned_delivery_at`, `picked_up_at`, `delay_minutes`, `order_id`, `customer_id` | on-time/late split, delivery-duration mean |
| `QuoteCreated`, `QuoteApproved`, `InvoiceCreated`, `InvoiceIssued`, `InvoicePaid`, `InvoiceOverdue`, `PaymentRecorded`, `SettlementSettled`, `PenaltyApplied`, `ClaimSettlementConsumed` | `currency_code` | multi-currency financial summary |
| `ClaimCreated` | `claimed_amount`, `currency_code`, `customer_id` | `total_claimed_amount`, currency keying |
| `ClaimApproved`, `ClaimSettled` | `currency_code` (+ `cycle_days` on settle) | currency keying, claim-cycle mean |
| `NotificationCreated`, `NotificationRead` | `priority` | unread-urgent operations badge |

Each emitting service was updated to populate the new fields from data it already
holds (shipment timing columns, invoice/quote/settlement/penalty `currency_code`,
claim amounts/timestamps, notification priority). No new reads were introduced.

`delay_minutes` and `cycle_days` are computed by small tz-safe helpers
(`_delivery_delay_minutes`, `ClaimsService._cycle_days`) that return `None` when the
inputs are unknown (e.g. no delivery-due date), so they never fabricate a metric.

---

## 3. Projection handler hardening

All changes live in `ProjectionService` and degrade gracefully on sparse payloads.

- **Multi-currency keying.** `_currency(payload)` normalizes `currency_code` to an
  upper-case 3-letter code, defaulting to `SAR`. `financial_summary` and
  `claims_metrics` rows are keyed by that currency, so a USD invoice and a SAR
  invoice land in different rows and their money never mixes. Legacy events (no
  `currency_code`) collapse to the `SAR` bucket — exactly the single-currency
  behaviour they were written under.
- **Shipment on-time/late + duration.** `ShipmentDelivered` now classifies on-time
  vs. late from `delay_minutes` and folds `picked_up_at → delivered_at` into an
  incremental `average_delivery_duration_minutes`. Deliveries without timing simply
  don't contribute (no false classification, no zero-duration skew).
- **Claims money + cycle mean.** `ClaimCreated.claimed_amount` accumulates into
  `total_claimed_amount`; `ClaimSettled.cycle_days` feeds an incremental
  `average_claim_cycle_days`.
- **Unread-urgent badge.** `NotificationCreated`/`NotificationRead` with
  `priority ∈ {high, urgent}` increment/decrement (clamped ≥ 0)
  `operations_dashboard.unread_urgent_notifications`.

### 3a. Exact, rebuild-deterministic running means

A naïve incremental mean keyed off the *event count* would be wrong when old
(metric-less) and new events interleave during a rebuild. Two internal sample
counters — `proj_shipment_performance.delivery_duration_sample_count` and
`proj_claims_metrics.claim_cycle_sample_count` — count **only the samples that carry
the metric**, making each running mean exact and identical on every deterministic
replay. They are deliberately **not** exposed in the read schemas (internal
bookkeeping, not dashboard figures).

---

## 4. Projection health automation

`projection_health` gained operational columns: `status`
(`healthy | stale | error`), `last_success_at`, `last_failure_at`, `last_error`,
`last_event_occurred_at`, `rebuild_count`.

- Every applied event marks the projection `healthy`, stamps `last_success_at` and
  the source event's `last_event_occurred_at`, and clears `last_error`.
- Every rebuild bumps `rebuild_count` and re-asserts `healthy`.
- A **non-destructive** scheduled sweep (`ProjectionService.run_health_check` →
  `app.analytics.health.run_projection_health_check`) re-classifies a projection
  `stale` once its newest source event lags beyond `_HEALTH_STALE_AFTER` (6 h). It
  **never replays or rebuilds** — staleness is advisory, surfaced through
  `GET /analytics/projections/health` so operators decide when a rebuild is
  warranted.

The sweep runs on celery-beat every 5 minutes (`mesaar.projection_health_check`,
overlap-guarded), mirroring the outbox relay's tenant model: the tenant list is read
under platform scope, each tenant's rows updated inside that tenant's own RLS-scoped
transaction, and one tenant's failure is logged and skipped so it cannot stall the rest.

### 4a. Reserved `error` surface (not yet active)

**Today the only statuses written are `healthy` and `stale`.** The `error` status
value and the `last_error` / `last_failure_at` columns are **reserved scaffolding for
a future out-of-band failure-capture path** and are currently always `NULL` / unset.
The reason they are not wired yet is deliberate and structural:

- Projection writes execute **inside the dispatcher's SAVEPOINT transaction**. If an
  updater raises, that transaction — including any health-row mutation — **rolls back
  with it**, so there is no in-band way to *persist* an `error` status from the failing
  path. The failure is instead handled by the event backbone's existing retry / DLQ
  machinery (see docs on the dispatcher), not by `projection_health`.
- Populating `error` correctly therefore requires a **separate, tested out-of-band
  transaction** (e.g. a post-DLQ hook that writes health in its own session). That
  design is intentionally deferred; no fake error writes are emitted in the meantime.

`run_health_check` includes a guard that leaves any row already in `error` untouched,
so the future path composes cleanly — but until that path exists, the guard is inert.
Consumers of `GET /analytics/projections/health` should treat `last_error`,
`last_failure_at`, and a `status` of `error` as **reserved and always empty for now**;
they must not be read as evidence that projection-failure capture is active.

---

## 5. Multi-currency analytics API

`GET /analytics/financial/summary` and `GET /analytics/claims/metrics` accept an
optional `currency_code` query filter (3-letter, upper-cased). The repository
`list_for_period` applies it only to projections that actually have a
`currency_code` column, so single-currency projections ignore it harmlessly.
`ProjectionHealthRead` was extended with the new health fields.

---

## 6. Migration (additive only)

`0015_event_enrichment_analytics_hardening` adds the two sample-count columns and the
six `projection_health` columns. Every new column is nullable or NOT NULL with a
`server_default`, so existing rows back-fill implicitly. No column is dropped or
retyped; no data is migrated. Single linear head:
`0014 → 0015`.

---

## 7. Test summary

`tests/test_event_enrichment_sprint12.py` (23 cases) covers: old-vs-new payload
compatibility for every enriched event + the `event_version == 1` invariant;
multi-currency no-mixing and the currency filter; SAR fallback; claims money + cycle
running average (incl. the missing-`cycle_days` skip); shipment on-time/late +
delivery duration (incl. legacy no-timing rows); the unread-urgent badge and its ≥0
clamp; health `healthy → stale → healthy` transitions; rebuild bookkeeping; the
cross-tenant sweep aggregation + per-tenant failure isolation; the celery task
wrapper; and a `NotificationCreated` emit-site assertion.

Direct **emit-site** assertions (proving the new fields are populated from
service-owned data) were also added to the existing service-test harnesses:
`test_shipment_service.py` (ShipmentDelivered timing/ids, incl. the no-due-date →
`delay_minutes = None` case), `test_billing_service.py` (InvoiceIssued /
PaymentRecorded `currency_code`), and `test_insurance_service.py` (ClaimCreated
`claimed_amount` / `currency_code` / `customer_id`).

Full suite: **1361 passed, 13 skipped**; OpenAPI builds; alembic single head `0015`.

---

## 8. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Currency keying defaults missing `currency_code` to `SAR`. A non-SAR aggregate that emits *some* events without the field (only possible for never-enriched event types) could split across the `SAR` bucket. | LOW | All money-bearing billing/claims events were enriched, so amounts are always currency-tagged; only count-only legacy rows could land in `SAR`, and a rebuild after full enrichment reconciles them. |
| The unread-urgent badge counts `Created` − `Read`; a notification that is failed/cancelled while unread is not decremented. | LOW | The badge is a glanceable operational hint, not an authoritative inbox count; it is fully recomputed on rebuild. |
| Staleness threshold (6 h) is a fixed constant. | LOW | Sweep is non-destructive and advisory; the constant can be promoted to settings if per-tenant SLAs diverge. |
| Internal sample-count columns are exposed on the model but not the API. | LOW | Intentional — they back the running means; documented here and in the model. |
