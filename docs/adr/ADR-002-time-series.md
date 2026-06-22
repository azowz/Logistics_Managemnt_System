# ADR-002 — Time-series & event analytics store

- **Status:** Accepted — **Confirmed 2026-06-20** (scale envelope = SMB/regional, so Postgres-only holds)
- **Date:** 2026-06-20

## Context
`shipment_tracking_events` is append-only and will grow fastest (location pings,
status changes, POD). Control-tower KPIs and ETA-risk analytics read over it. We
must decide whether plain PostgreSQL suffices or we need a time-series engine now.

## Decision
**Start PostgreSQL-only.** Partition `shipment_tracking_events` by month
(declarative partitioning) and serve dashboards from **projection tables** (ADR-006),
not live scans. Defer any time-series extension until volume justifies it.

## Consequences
- (+) One system to operate; ACID, JSONB, existing tooling.
- (+) Projections keep read latency low regardless of raw event volume.
- (−) At very high ping rates, manual partition/index management grows; revisit.

## Trigger to revisit
Adopt a PostgreSQL-compatible time-series extension (hypertables / continuous
aggregates) when **sustained event ingest > ~5k events/sec** or rollup queries
exceed p95 latency budget. Because it is PG-compatible, migration is additive.

## Alternatives
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **PostgreSQL-only + partitions** | Simple, ACID | Manual at scale | **Chosen** |
| Time-series extension now | Optimized rollups | Extra ops surface early | Deferred |
| Separate OLAP warehouse | Heavy analytics | Sync complexity | Later (Phase 5+) |
