# M2 Readiness Report — Enterprise Event Backbone (Mesaar)

> **Type:** Pre-implementation gate review (M2). **Documentation only.** Produced 2026-06-22.
> **Outcome:** ⚠ **CONDITIONALLY READY — STOP for two prerequisite corrections before building the event store.** Two approved-architecture dependencies that M2 *itself* relies on are not yet implemented. Per the M2 brief ("Never continue with known architectural debt"), these must be corrected first. Details in §3–§5.

---

## 1. Conformance review — M1 implementation vs approved architecture

I reviewed the architecture docs (`01`–`12`), ADR-001…009, the final domain model (`09`/`09a`), the Database Freeze review (`10`), and the **as-built M1 code** (models, migration `0003`, RLS, JWT propagation, repositories, tests).

| Area | Approved source | As-built (M1) | Conformance |
|---|---|---|---|
| Shared-schema multi-tenancy + RLS | ADR-001, `docs/03` §8 | `tenants` + `tenant_id` + `ENABLE/FORCE` RLS policy (`0003`) | ✅ matches |
| `tenant_id` on every aggregate + per-tenant composite uniques | `docs/03` §3.2 | all 6 aggregates; 7 composites; single-col uniques dropped | ✅ matches |
| Tenant GUC on pooled connections (`SET LOCAL`) | `docs/03` §8.1 | `after_begin` listener → `set_config('app.current_tenant', …, true)` | ✅ matches |
| Tenant propagation via JWT | `docs/11` §7 | `tid` claim set into ContextVar in `get_current_user` before queries; login platform-scoped | ✅ matches |
| Additive, Alembic-safe migrations | `docs/05` §3.6 | `0003` additive; `Base.metadata`+`app.models` targets unchanged | ✅ matches |
| Aggregate ownership / one-owner | `docs/09` §4, `docs/05` §4 | models unchanged in ownership; `Tenant` added | ✅ matches |
| Repository pattern | `docs/05` §5 | `TenantRepository` added, consistent | ✅ matches |
| UUIDv7 generator + `BaseModel` + mixins | `docs/03` §0, `app/db` | present (`uuid7`, `BaseModel`, `TimestampMixin/SoftDelete/Audit/Tenant`) | ✅ present (mixins largely unused on aggregates) |
| Async substrate (Celery/Redis) | ADR-003 | `app/workers/celery_app` present | ✅ present |
| Cross-tenant isolation **verified** | `docs/07` M1 gate | test written, **Postgres-gated / not run in CI** | ⚠ **R-2 open** |
| Least-privilege non-superuser DB role | `docs/03` §6/§8 | **not implemented** (default = superuser → RLS bypassed) | ⚠ **R-1 open** |
| **Aggregate `version` (optimistic lock)** | ADR-004, `docs/03` §0/§7.3 | **not implemented** | ❌ **gap (B1)** |
| **`created_by` / `updated_by` / `deleted_at` / `currency_code`** | `docs/03` §0/§6 | **not implemented** | ❌ **gap (R-3)** |
| **Current-user context + `app.current_user_id` GUC** | `docs/03` §6/§8.1 | **not implemented** (M1 propagated tenant only) | ❌ **gap (B2)** |

**Conclusion:** M1 faithfully implements the **tenancy** slice. The event backbone, however, has two hard upstream dependencies (`version`, current-user context) that M1 did not deliver and that M2 **cannot be built correctly without**.

---

## 2. What M2 requires that must already exist

| M2 needs… | …because | Status |
|---|---|---|
| `tenant_id` + tenant GUC | every event/outbox/audit row is tenant-scoped & RLS-protected; no cross-tenant leakage | ✅ present (M1) |
| UUIDv7 generator + `BaseModel` | `event_id`/`audit.id` PKs are time-ordered UUIDv7 | ✅ present |
| Celery/Redis | outbox relay + async dispatch | ✅ present |
| **Aggregate `version`** | `event_store.UNIQUE(aggregate_id, aggregate_version)` is **paired with the aggregate's optimistic-lock `version`** (ADR-004; `docs/03` §7.3: *"this is the optimistic-concurrency mechanism, paired with `shipments.version`"*). Without it, `aggregate_version` has no authoritative source and concurrency is unenforceable. | ❌ **B1 — BLOCKER** |
| **Current-user propagation** | every Domain Event must carry `user_id`, and the audit layer needs `created_by/updated_by`/`actor_user_id` from `app.current_user_id`. M1 propagates tenant but **not user**. | ❌ **B2 — BLOCKER** |
| Non-superuser app role + immutability grants | append-only/immutability of `event_store`/`audit_log` is enforced by `INSERT`/`SELECT`-only grants on a **non-superuser** role; superusers bypass RLS + grants | ⚠ **C1 — production condition (R-1)** |
| RLS isolation proven in CI (Postgres) | M2 adds `event_store`/`audit_log` with `tenant_id`+RLS; the isolation gate must cover them | ⚠ **C2 — condition (R-2)** |

---

## 3. Blockers (must be corrected before building the event store)

### B1 — Aggregate optimistic-lock `version` is missing (was R-3)
- **Problem.** No aggregate carries `version`. The approved event model pairs `event_store.aggregate_version` with the aggregate's `version` for optimistic concurrency.
- **Impact.** The event store's central concurrency guarantee cannot be implemented faithfully; building it without `version` would bake in architectural debt the M2 brief forbids.
- **Root cause.** M1 was scoped to `tenant_id` only; the `docs/03` §0 lifecycle-column rollout was not completed.
- **Recommendation.** Additive migration **`0004`** adding `version int NOT NULL DEFAULT 1` (CHECK ≥ 1) to all aggregates — plus the rest of §0 (`created_by`, `updated_by`, `deleted_at`, and `shipments.currency_code`) in the same pass.

### B2 — Current-user context + `app.current_user_id` GUC is missing
- **Problem.** M1 added a tenant ContextVar + GUC, but no equivalent for the acting user. Domain Events require `user_id`; the audit layer requires actor columns.
- **Impact.** Events and audit rows could not be reliably attributed to a user (the M2 event schema mandates `User ID`).
- **Root cause.** Out of M1's tenancy scope.
- **Recommendation.** Mirror the tenant mechanism: a `current_user` ContextVar in `app/db/tenant` (or a sibling), set in `get_current_user`/middleware from the JWT `sub`, applied as `SET LOCAL app.current_user_id` via the same `after_begin` listener. Build this in **`0004`/M2 step-0**.

---

## 4. Conditions (M2 must be designed to satisfy; enforced at deploy/CI)

- **C1 (R-1, Critical for production):** the application must connect as a **non-superuser, non-owner** role; M2 will define `INSERT`/`SELECT`-only immutability grants for `event_store`/`audit_log`, but they are only effective under that role. *M2 implements the design; deploy enforces the role.*
- **C2 (R-2, Critical for production):** the cross-tenant isolation test must run in **CI against PostgreSQL** and be extended to `event_store`/`audit_log`. *M2 adds the tests; CI must run them with a non-superuser `TEST_DATABASE_URL`.*

These do **not** block writing M2, but M2 is not production-trustworthy until they are closed (they were the two Criticals in `docs/10` §12).

---

## 5. Recommended corrected sequence

```
Step 0  (prereq, small)  Migration 0004 + context:
        - version / created_by / updated_by / deleted_at on all aggregates; shipments.currency_code
        - current-user ContextVar + app.current_user_id GUC (mirror tenant)
        - extend the after_begin listener to set both tenant + user GUCs
Step 1  (M2 core)        event_store (UUIDv7 PK (event_id, occurred_at); UNIQUE(aggregate_id, aggregate_version);
                         monthly RANGE partition; full envelope; RLS) + repository
Step 2                   Transactional outbox (published_at, retry_count, next_attempt_at, dead-lettered)
                         + processed_events(consumer, event_id) idempotency ledger
Step 3                   Domain Event abstraction (Event ID, Aggregate ID/Version, Type, Event Version,
                         Tenant, Correlation, Causation, User, Timestamp, Metadata, Payload) + registry/upcasting
Step 4                   Event Bus abstraction (pluggable: in-process now; Kafka/NATS/RabbitMQ later)
                         + dispatchers (internal/async/retry) + relay worker
Step 5                   Projection engine (rebuild from log) + audit_log integration (trigger + domain)
Step 6                   Replay (by aggregate / tenant / date / event type) + dead_letter table + observability
Step 7                   Tests (unit/integration/replay/idempotency/outbox/RLS/concurrency) + compliance/security/perf review
```

All steps remain additive, Alembic-safe, Clean-Architecture-compliant, and tenant-isolated.

---

## 6. Verdict

**⚠ CONDITIONALLY READY.** The approved architecture is sound and M1 conforms to it for tenancy. **Two prerequisite corrections (B1 `version`, B2 current-user context) must land first** because the event backbone's concurrency and attribution guarantees depend on them — proceeding without them would introduce exactly the architectural debt the M2 brief forbids. The two production Criticals (C1 non-superuser role, C2 RLS CI verification) carry forward as deploy/CI conditions.

**Recommended:** approve **Step 0 (migration `0004` + current-user context)** folded into M2, then implement the event backbone (Steps 1–7). I have not written any M2 code pending this decision.
