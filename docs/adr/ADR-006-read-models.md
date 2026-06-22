# ADR-006 — Read models / projections

- **Status:** Accepted (default)
- **Date:** 2026-06-20

## Context
The control tower (live map, exception center, SLA/ETA risk, capacity) needs fast,
denormalized reads. Today those would require multi-join scans over `shipments` +
`shipment_tracking_events`, which won't meet the p95 < 300ms read budget at scale.

## Decision
Build **projection tables in the same PostgreSQL** (no separate store yet), updated
by event consumers (ADR-003/004). Initial projections:

| Projection | Feeds | Source events |
|---|---|---|
| `proj_active_shipments` | Ops board, live map | Assigned/PickedUp/Delivered/Failed |
| `proj_driver_status` | Dispatch availability | DriverWentOnline/Offline, assignment |
| `proj_warehouse_load` | Capacity overview | ShipmentCreated/Delivered |
| `proj_sla_risk` | Exception center | clock + delivery_due_at |
| `proj_driver_daily_stats` | Driver app KPIs | Delivered + tracking distance |

## Consequences
- (+) Console reads hit a single denormalized row set.
- (+) Rebuildable from the append-only log (bounded replay).
- (−) Eventual consistency (sub-second target); UI shows "as of" timestamps.
- (−) Projection lag must be monitored (Prometheus gauge).

## Alternatives
| Option | Verdict |
|---|---|
| **PG projection tables** | **Chosen** — no new infra |
| Materialized views | Rejected: coarse refresh, locking |
| External read store (Elasticsearch) | Deferred to search-heavy phase |
