# ADR-003 — Background job processing

- **Status:** Accepted — **Confirmed 2026-06-20** (SMB scale; Celery + Redis remains the choice)
- **Date:** 2026-06-20

## Context
SLA breach alerts, ETA recomputation, notification fan-out, freight settlement,
and projection rebuilds must run off the request path with retries and scheduling.

## Decision
Use **Celery** with a **Redis** broker (Redis also serves as cache). Add
**celery-beat** for scheduled jobs (SLA sweeps, ETA refresh). Workers are separate
containers (see `docs/diagrams/deployment.mmd`).

## Consequences
- (+) Mature: routing, retries/backoff, rate limits, workflows (chains/groups),
  monitoring, horizontal scaling — matches a growing SLA/settlement workload.
- (+) Redis is reused for caching and Celery, reducing infra count.
- (−) More moving parts than an in-process queue; needs worker observability.

## Alternatives
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Celery + Redis** | HA, workflows, scheduling | Operational weight | **Chosen** |
| RQ | Simplest, Redis-only | Fewer primitives, weaker workflows | Rejected for SLA scope |
| FastAPI BackgroundTasks | Zero infra | No durability/retries/scheduling | Dev-only |

## Rules
- All handlers **idempotent** (keyed by event id) — pairs with ADR-004.
- Settlement/notification jobs are **at-least-once**; dedupe at the sink.
