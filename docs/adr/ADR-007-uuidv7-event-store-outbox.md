# ADR-007 — UUIDv7 keys, unified Event Store, and Transactional Outbox

- **Status:** Accepted — **2026-06-20** (finalizes Phase 4; locks the implementation mechanics designed in `docs/03-database-architecture.md` §6–7 and modeled in `docs/04` Part 6) · **Amended 2026-06-22 (Phase 6.5): added Migration Plan + Rollback Plan (closes audit gap `docs/06` §C.2).**
- **Date:** 2026-06-20
- **Deciders:** Program lead
- **Builds on:** ADR-002 (partitioning), ADR-004 (CQRS-lite event model), ADR-006 (projections)

## Context
Phase 3 introduced UUID primary keys with a *recommendation* to adopt UUIDv7 on append-heavy
tables, and Phase 4 modeled a CQRS-lite event flow. Three implementation mechanics were still
"recommended" rather than ratified, leaving Phase 5 ambiguous: (1) how ids are generated,
(2) the shape/ownership of the event log, and (3) how a state change and its event are published
without a dual-write race. This ADR locks all three as one coherent decision.

## Decision

### 1. UUIDv7 primary keys on append/high-insert tables
Adopt **UUIDv7** (RFC 9562, time-ordered) for the PKs of append-heavy tables — `event_store`,
`shipment_tracking_events`, `audit_log`, `ml_predictions`, and `proj_*` projections — generated
in-app via `app/db/uuidv7.uuid7` and `app/db/base_model.BaseModel`. UUIDv4 remains acceptable for
low-churn reference tables. **Existing models keep their `uuid4` ids (no retrofit, no migration of
in-place keys);** UUIDv7 applies to new tables only.

### 2. A single unified Event Store
One **`event_store`** table is the canonical, append-only domain-event log for **all** aggregates
(not per-aggregate tables). `shipment_tracking_events` remains the user-facing *tracking slice* of
that stream. Canonical envelope (per `docs/03` §7): `event_id` (UUIDv7, **idempotency key**),
`tenant_id`, `aggregate_type`, `aggregate_id`, `aggregate_version`, `event_type`, `payload` (jsonb),
`occurred_at`, `recorded_at`, `correlation_id`, `causation_id`, `published_at`. **Per-aggregate
ordering and optimistic concurrency** are enforced by `UNIQUE(aggregate_id, aggregate_version)`.
The table is **range-partitioned by month** on `occurred_at` (ADR-002).

### 3. Transactional Outbox
A command's **state change and its event row are written in one local transaction**. A separate
**relay/poller** reads rows where `published_at IS NULL`, publishes them to the bus (Celery/Redis,
ADR-003), and stamps `published_at`. Consumers are **at-least-once** and **dedupe on `event_id`**
via `processed_events(consumer, event_id)`. The application **never writes to the broker directly**
in the same flow as the DB commit.

## Consequences
- (+) UUIDv7 gives near-sequential index inserts → less B-tree page-splitting / WAL bloat on the
  fastest-growing tables, while staying globally unique and non-enumerable.
- (+) One event log = one mental model, one partitioning/retention policy, lossless audit, and
  replayable projections (ADR-006).
- (+) Outbox removes the dual-write failure mode (event lost if broker publish fails after commit).
- (−) Operate a **relay worker** and monitor outbox lag (Prometheus gauge); pairs with ADR-003.
- (−) **Two writes per command inside one transaction** (aggregate + event); keep payloads lean.
- (−) Monthly partition + index management on `event_store` (ADR-002 trigger to revisit at scale).

## Alternatives considered
| Option | Verdict |
|---|---|
| **UUIDv7 (chosen)** | Native `uuid` type, time-ordered, standardized (RFC 9562) |
| UUIDv4 everywhere | Rejected: random inserts → page splits / WAL bloat on append tables |
| ULID / bigint identity | Rejected: ULID needs a custom type; bigint isn't federation-safe/non-enumerable |
| Per-aggregate event tables | Rejected: schema/partition fan-out, no single replay surface |
| Event bus **without** outbox | Rejected: dual-write race loses events |
| Full event sourcing | Deferred (ADR-004): aggregate stays source of truth; we replay *projections* |

## Follow-ups (Phase 5+)
- `event_store` + `processed_events` models/migrations (additive; `app.db.base:Base.metadata`).
- Outbox **relay** task in `app/workers`; idempotent consumers (ADR-003 rules).
- `app/events` (domain event types + publish port) and `app/projections` (ADR-006 builders).
- Partition pre-create/retention job (celery-beat); outbox-lag metric.

## Migration Plan (added 2026-06-22, Phase 6.5)

Additive, **zero-downtime**, Alembic-safe (`app.db.base:Base.metadata` is the target); **no retrofit** of existing `uuid4` PKs. Strictly **after M1** (tenancy: `tenant_id` + RLS + isolation test).

1. **M2.1 — Schema (additive).** Create `event_store` (UUIDv7 PK, full envelope, `UNIQUE(aggregate_id, aggregate_version)`, monthly RANGE partition on `occurred_at`) and `processed_events(consumer, event_id)`; add `published_at` semantics to the outbox path. All new tables are **tenant-scoped + RLS** (ADR-001). New tables only ⇒ no migration of existing rows.
2. **M2.2 — Dual-write (shadow).** Behind a feature flag (`EVENT_STORE_ENABLED`), command handlers append the event row in the **same local transaction** as the aggregate write; the relay stays **off** (no publish). Validate that event rows land and reconcile counts against `shipment_tracking_events` for tracking-typed events.
3. **M2.3 — Backfill (optional, bounded).** Replay existing `shipment_tracking_events` into `event_store` as historical events (idempotent on `event_id`) if a complete replay surface is required; tracking rows remain the user-facing slice.
4. **M2.4 — Relay rollout.** Enable the relay/poller (publishes `published_at IS NULL` → Celery/Redis, ADR-003), **one consumer at a time**, each idempotent via `processed_events`; watch the outbox-lag Prometheus gauge.
5. **M2.5 — Projection cutover.** Point ADR-006 projection builders at the bus, rebuild projections from the log, then switch console reads to the projections.
6. **M2.6 — Enforce.** Once stable, make event-store append **non-optional** for new contexts; schedule partition pre-create/retention on celery-beat.

## Rollback Plan (added 2026-06-22, Phase 6.5)

Each step is independently reversible. The **aggregate remains the source of truth** (ADR-004), so disabling the event path never loses business state. **Rollback = stop appending/publishing, never DELETE committed events** (append-only / BR-H-24 / lossless audit).

| Failure | Rollback action | Data-loss risk |
|---|---|---|
| Relay failure / lag spike | Stop the relay worker; rows accumulate as `published_at IS NULL`; resume after fix (consumers are at-least-once + idempotent, so replays are safe). | None |
| Dual-write defect | Flip `EVENT_STORE_ENABLED=false`; handlers revert to aggregate-only writes; `shipment_tracking_events` keeps serving tracking. | None |
| Schema rollback needed | With the flag off the new tables are unreferenced by live flows; drop `event_store`/`processed_events` via a down-migration; `shipments`/tracking unaffected. | None |
| Backfill defect | Truncate backfilled historical rows and re-run (idempotent on `event_id`); projections rebuild from the canonical slice. | None (historical only) |

> **Guard:** "rollback" must never mutate or delete committed event history — it only disables publication/append. Hard-delete, if ever required, applies to non-event tables only (see `event-catalog.md` CF9 correction).

*Companion artifacts:* `docs/03-database-architecture.md` §6–7 · `docs/04-event-storming-and-state-machines.md` Part 6 · `docs/09a-reconciliation-and-closure.md` (Phase 6.5) · ADR-002/004/006.
