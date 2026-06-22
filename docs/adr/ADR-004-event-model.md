# ADR-004 — Event model depth (CQRS-lite vs full event sourcing)

- **Status:** Accepted (default)
- **Date:** 2026-06-20

## Context
`shipment_tracking_events` is already an **append-only** log with monotonic
`event_time` ordering enforced in `shipment_service.create_tracking_event()`.
We must decide how far to take event-driven design without over-engineering.

## Decision
Adopt **CQRS-lite**: the relational aggregate (`shipments`) remains the source of
truth for current state; the append-only tracking table is the **audit/event log**;
**projection tables** (ADR-006) serve read-heavy console views. We do **not** rebuild
aggregate state purely from events (no full event sourcing).

Domain events (see `docs/event-catalog.md`) are emitted on each state transition
and consumed by projection builders and Celery workers.

## Consequences
- (+) Keeps existing models/queries; adds auditability + fast reads incrementally.
- (+) Replay rebuilds *projections* (cheap), not aggregates.
- (−) Two write targets per transition (aggregate + event) — wrap in one DB tx.
- Requires: **optimistic concurrency** (`version` column on `shipments`),
  **idempotency keys** on events, **compensating events** for reversals
  (e.g. `ShipmentReturned` after `ShipmentDelivered` is modeled as a new event,
  never a mutation/delete of history).

## Alternatives
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **CQRS-lite (append log + projections)** | Audit + fast reads, low risk | Two writes/txn | **Chosen** |
| Full event sourcing | Max replay/audit | Versioning, eventual consistency, cost | Deferred unless regulator-mandated |
| State-only (no events) | Simplest | No audit, slow control tower | Rejected |
