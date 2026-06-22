# ADR-001 — Tenancy model

- **Status:** Accepted — **Confirmed 2026-06-20** (program lead chose shared multitenant + RLS)
- **Date:** 2026-06-20
- **Deciders:** Program lead

## Context
The platform serves multiple shipper customers and an internal operations org.
Current models (`app/models/*`) have **no `tenant_id`** — they are effectively
single-tenant. We must choose an isolation strategy before building consoles and
RBAC, because it touches every table, query, and migration.

## Decision
Adopt **shared multitenancy with a row-level `tenant_id`** on every aggregate
root, enforced by PostgreSQL **Row-Level Security (RLS)** plus an application-layer
tenant scope resolved from the JWT. Internal operations is tenant `0` (platform).

## Consequences
- (+) Lowest cost, fastest onboarding, one schema/migration set.
- (+) RLS gives defense-in-depth even if an app query forgets the scope.
- (−) Noisy-neighbor risk; needs per-tenant rate limits and query budgets.
- (−) Requires a migration to add `tenant_id` + backfill + composite indexes
  `(tenant_id, <natural key>)`; unique constraints become per-tenant.
- Cross-tenant analytics run as the platform tenant with explicit elevation.

## Alternatives considered
| Option | Isolation | Ops cost | Verdict |
|---|---|---|---|
| DB-per-tenant (single-tenant) | Highest | High | Reserve for enterprise-isolation customers (hybrid) |
| **Shared row-level + RLS** | Medium-High | Low | **Chosen** |
| Schema-per-tenant | High | Medium | Rejected: migration fan-out pain |

## Follow-ups
- Phase 2: add `tenant_id` to ERD + Alembic; convert `uq_*` to per-tenant.
- Revisit as **hybrid "stamps"** if a regulated customer requires hard isolation.
