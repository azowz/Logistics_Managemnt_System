# Final Database Review & Freeze — Mesaar Logistics Operations Platform

> **Document type:** Mandatory production-grade Database Freeze review (banking/enterprise discipline). **Documentation only** — no implementation code, SQLAlchemy models, SQL, or migrations are produced here.
> **Date:** 2026-06-22. **Supersedes** the Phase-7 freeze; **reflects the as-built reality after milestone M1** (multi-tenancy + RLS is now implemented on disk, migration `0003_multi_tenancy_rls`).
> **Reviewer stance:** challenge every decision; assume nothing; verify against the actual repo (`app/`, `migrations/`, `docs/03`, `docs/09–09a`, `docs/11–12`, ADR-001…009) and the live M1 build.
> **Maturity legend used throughout:** **`[BUILT]`** = table exists on disk (models + migration `0001→0003`); **`[DESIGNED]`** = column-complete in `docs/03` but not built (M2/M6/M8); **`[STRUCTURAL]`** = column-spec authored in `docs/11` §1, not built.

---

## 1. Executive Summary

Mesaar's data architecture is a **design-strong, build-early** system. The design corpus (ERD, tenancy, event store, projections, AI substrate, indexing, audit) is enterprise-grade, internally consistent, and — after the Phase-6.5 closures — free of unresolved **design** conflicts. As of M1, the **multi-tenant foundation is genuinely implemented**: a `tenants` table, `tenant_id` on every aggregate, per-tenant composite uniques, and Row-Level Security policies (migration `0003`) are on disk and pass model/migration verification.

However, a rigorous review surfaces **real as-built gaps and operational risks** that must gate production go-live — most importantly that **Row-Level Security is silently bypassed when the application connects as a PostgreSQL superuser** (which the default configuration does), the **RLS cross-tenant isolation test has not yet been executed against PostgreSQL**, and the **`docs/03` §0 lifecycle columns (`version`, `created_by`, `updated_by`, `deleted_at`, `currency_code`) were not delivered by M1** — leaving the aggregates without optimistic-concurrency control, soft-delete, or actor-audit columns that the design (and the event-store concurrency model) depend on.

The event store / outbox / audit backbone (M2) and the commercial + heavy-equipment + AI tables remain unbuilt — expected at this stage, and correctly sequenced.

### Scorecard

| Dimension | Score /100 | Basis |
|---|---|---|
| **Architecture (design)** | **90** | Frozen, coherent DDD/CQRS-lite/EDA; one aggregate ↔ one owner; conflicts resolved (6.5) |
| **Scalability** | **76** | Tenant-leading composites, monthly partitioning, outbox, LIST sub-partition path — but SMB envelope (ADR-002/003), OLAP deferred, partitioning unbuilt |
| **Security** | **58** | Strong design (RLS, 3-layer audit, immutability grants, tenant-scoped AI) **undercut by as-built gaps**: superuser-bypasses-RLS, no least-privilege roles, no PII encryption/masking, KMS/secrets ADR missing, RLS unverified |
| **Performance** | **80** | Sound index strategy (partial/BRIN/GIN/HNSW/covering), projections, partition retention — all unbuilt |
| **Maintainability** | **86** | Clean layering, frozen `NAMING_CONVENTION`, hand-authored migrations, ubiquitous language; minor catalog drift resolved |
| **AI readiness** | **70** | Excellent ML substrate (pgvector/HNSW, point-in-time feature store, `ml_predictions` feedback, RAG corpus) but **no model registry / prompt logs / agent memory / explicit feedback table**; MLOps ADR (ADR-010) pending; all unbuilt |
| **Overall production readiness** | **52** | Design ready; build = M1 only; production gated on the conditions below |

### Verdict (full detail in §12)

**⚠ APPROVED WITH CONDITIONS.** No unresolved **design-level Critical** defect remains, so implementation **may continue** (M2 next). But **production go-live and any real-tenant onboarding are BLOCKED** until the Critical conditions in §11/§12 are closed — chiefly: (C-1) the app must connect as a **non-superuser** role and the **RLS isolation test must pass in CI against PostgreSQL**; (C-2) the **§0 lifecycle/audit columns** must be delivered; (C-3) the **M2 event-store/outbox/audit** backbone must ship before event-driven contexts.

---

## 2. Database Inventory

**As-built totals:** 8 `[BUILT]` tables (after M1) · 15 `[DESIGNED]` (column-complete, `docs/03`) · 32 `[STRUCTURAL]` (column-spec `docs/11` §1) = **55 tables** in the frozen target. Growth/freq are order-of-magnitude estimates for an SMB-to-regional envelope (ADR-002).

### 2.1 BUILT tables (on disk; migrations `0001→0003`)

| Table | Purpose | Aggregate owner | Bounded context | PK | Foreign keys | Business key(s) | Growth | Read | Write | AI use | Retention |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `tenants` | Isolation boundary; nil-UUID platform org | Tenant | Identity & Access #1 | `id` (uuid4) | — | `slug` (global) | very low | high | very low | indirect (scopes all) | permanent |
| `users` | Authenticated account + role | User | Identity & Access #1 | `id` (uuid4) | `tenant_id`→tenants | `(tenant_id, email)` | low–med | high | features (driver/client) | permanent (soft-delete planned) |
| `drivers` | Driver operational profile | Driver | Driver Mgmt #6 | `id` | `tenant_id`, `user_id`→users (CASCADE), `home_warehouse_id`→warehouses (SET NULL) | `(tenant_id, user_id)`, `(tenant_id, license_number)` | low | high | assignment ranking | permanent |
| `vehicles` | Transport asset + capacity/status | Vehicle | Fleet #5 | `id` | `tenant_id`, `home_warehouse_id`→warehouses (SET NULL) | `(tenant_id, plate_number)`, `(tenant_id, vin)` | low | high | utilization | permanent |
| `warehouses` | Network node + capacity/geo | Warehouse | Warehouse #8 | `id` (uuid4) | `tenant_id` | `(tenant_id, code)` | very low | high | capacity/geo features | permanent |
| `shipments` | Physical-execution aggregate root; 8-state lifecycle; assignment cols | Shipment | Shipments #4 | `id` | `tenant_id`, `client_id`→users (RESTRICT), `origin/destination_warehouse_id`→warehouses (RESTRICT), `driver_id`/`vehicle_id`→ (SET NULL) | `(tenant_id, reference_code)` | **high** | very high | ETA/SLA/pricing/anomaly | hot 18mo → archive |
| `shipment_tracking_events` | Append-only per-shipment history (status/location/POD/exception) | ShipmentTrackingEvent | Tracking #9 | `id` (uuid4 today) | `tenant_id`, `shipment_id`→shipments (CASCADE), `recorded_by_user_id`→users (SET NULL) | — (append-only) | **very high** | high | location/POD features | hot 18mo → archive (partition drop) |

> **As-built note:** migration `0002` added `shipments.cargo_type / price_sar / required_vehicle_type` (driver offer feed). `0003` added `tenant_id` + per-tenant uniques + RLS to all six base aggregates and created `tenants`.

### 2.2 DESIGNED (column-complete in `docs/03`; not built — M2/M6/M8)

| Table | Purpose | Owner/Context | PK | Key FKs | State | Growth | Retention |
|---|---|---|---|---|---|---|---|
| `event_store` | Canonical append-only event log + transactional outbox | cross-cutting (ADR-007) | `(event_id, occurred_at)` UUIDv7; UK `(aggregate_id, aggregate_version)` | `tenant_id` (RLS) | [DESIGNED] | **very high** | hot 18mo → archive (monthly partition drop) |
| `processed_events` | Per-consumer idempotency ledger | cross-cutting | `(consumer, event_id)` | — | [DESIGNED] | high | rolling |
| `idempotency_keys` | API dedupe for unsafe POSTs | cross-cutting | `id` | `tenant_id` | [DESIGNED] | med | short TTL |
| `outbox_relay_state` | Relay cursor/heartbeat (lag) | cross-cutting | `id` | — | [DESIGNED] | tiny | n/a |
| `audit_log` (schema `audit`) | Generic row before/after history (trigger) | cross-cutting | `(id, at)` UUIDv7 | `tenant_id` (RLS) | [DESIGNED] | **very high** | regulatory (partition + archive) |
| `proj_active_shipments` | Ops board / live map | Analytics #12 | `shipment_id` | `tenant_id` | [DESIGNED] | med (disposable) | rebuildable |
| `proj_driver_status` | Dispatch availability | Analytics #12 | `driver_id` | `tenant_id` | [DESIGNED] | low | rebuildable |
| `proj_warehouse_load` | Capacity overview | Analytics #12 | `warehouse_id` | `tenant_id` | [DESIGNED] | low | rebuildable |
| `proj_sla_risk` | Exception center / `ShipmentDelayed` | Analytics #12 | `shipment_id` | `tenant_id` | [DESIGNED] | med | rebuildable |
| `proj_driver_daily_stats` | Driver KPIs | Analytics #12 | `(driver_id, day)` | `tenant_id` | [DESIGNED] | med | rolling |
| `embeddings` | pgvector vectors (HNSW) | AI Ops #13 | `id` | `tenant_id` | [DESIGNED] | med–high | model-versioned |
| `ml_features_shipment` | Point-in-time feature snapshots | AI Ops #13 | `id` UUIDv7 | `tenant_id`, `shipment_id` | [DESIGNED] | high | training window |
| `ml_predictions` | Inference log + `actual_outcome` feedback | AI Ops #13 | `id` UUIDv7 | `tenant_id` | [DESIGNED] | high | training window |
| `documents` / `document_chunks` | RAG corpus + chunk embeddings | AI Ops #13 | `id` / `id` | `tenant_id`; `document_id`→documents (CASCADE) | [DESIGNED] | med | corpus-managed |

### 2.3 STRUCTURAL (column-spec in `docs/11` §1; not built — M3/M4/M5/M7)

| Group (context) | Tables | State | Growth (anchor table) | Retention |
|---|---|---|---|---|
| Customers (#2) | `customers`, `customer_contacts` | [STRUCTURAL] | low | permanent |
| Orders (#3) | `orders`, `order_lines` | [STRUCTURAL] | high | permanent |
| Equipment (#15) | `equipment_categories`, `equipment_models`, `equipment` | [STRUCTURAL] | med | permanent |
| Contracts (#14) | `contracts`, `rental_contracts`, `pricing_rules`, `slas`, `penalties`, `carrier_agreements` | [STRUCTURAL] | low–med | regulatory |
| Insurance/Claims (#17) | `insurance_policies`, `coverage_rules`, `claims`, `damage_reports`, `liability_records` | [STRUCTURAL] | med | regulatory |
| Compliance/Permits (#16) | `permits`, `escorts`, `axle_weight_profiles`, `route_restrictions`, `compliance_rules`, `compliance_checks`, `operator_certifications` | [STRUCTURAL] | med | regulatory |
| Billing (#11) | `quotes`, `invoices`, `settlements`, `payouts` | [STRUCTURAL] | high | regulatory (7y) |
| Routes (#7) | `routes`, `route_stops` | [STRUCTURAL] | high | hot → archive |
| Notifications (#10) | `notifications` | [STRUCTURAL] | high | short → archive |

**Inventory findings:** (F-INV-1, Med) `shipment_tracking_events` PK is `id` only, but `docs/03` §3.1 requires a **composite PK including the partition key** `(id, event_time)` once partitioned — the as-built PK must change at M2 (a non-trivial migration). (F-INV-2, Low) `documents`/`document_chunks`, model registry, and prompt/agent tables are absent from the AI group (see §9).

---

## 3. Relationship Matrix

### 3.1 Built relationships (verified against models + migration `0003`)

| Parent → Child | Type | FK column | ON DELETE | Optional? | Notes |
|---|---|---|---|---|---|
| tenants → users | 1:M | `users.tenant_id` | **RESTRICT** | required | every aggregate is tenant-scoped |
| tenants → {drivers,vehicles,warehouses,shipments,tracking} | 1:M | `*.tenant_id` | **RESTRICT** | required | boundary never silently deleted |
| users → drivers | 1:0..1 | `drivers.user_id` | **CASCADE** | required | profile is dependent on identity |
| users → shipments (client) | 1:M | `shipments.client_id` | **RESTRICT** | required | client with shipments not hard-deletable |
| users → tracking (recorder) | 1:M | `recorded_by_user_id` | **SET NULL** | optional | keep event, drop actor link |
| warehouses → drivers/vehicles (home) | 1:M | `home_warehouse_id` | **SET NULL** | optional | optional home base |
| warehouses → shipments (origin/dest ×2) | 1:M | `origin/destination_warehouse_id` | **RESTRICT** | required | referenced network nodes |
| drivers/vehicles → shipments (assigned) | 1:M | `driver_id`/`vehicle_id` | **SET NULL** | optional | unassign on removal; shipment survives |
| shipments → tracking | 1:M | `shipment_id` | **CASCADE** | required | history scoped to shipment |

### 3.2 Designed/structural relationships (representative; full set in `docs/10`-prior §3 / `docs/11` §1)

customers→orders→order_lines (1:M:M, RESTRICT/CASCADE); orders→shipments (1:M, SET NULL, `order_id` nullable); equipment_categories→equipment_models→equipment (1:M:M); equipment→shipments (1:M, SET NULL, `equipment_id` nullable); insurance_policies→claims→{damage_reports, liability_records} (1:M:M); contracts→{rental/pricing/sla/penalties/carrier} (1:M, CASCADE); routes→route_stops→shipments (1:M:0..1); event_store→processed_events (1:M, logical, no FK).

### 3.3 Validation

| Check | Result | Detail |
|---|---|---|
| One-to-one | **PASS** | users↔drivers (1:0..1) — the only 1:1; enforced by `(tenant_id, user_id)` unique |
| One-to-many | **PASS** | all FK children declared with explicit ON DELETE |
| Many-to-many | **PASS (none)** | no native M:M; resolved via owned children (`route_stops`, `order_lines`) — additive `route_stop_shipments` flagged if multi-shipment stops arise |
| Bridge tables | **N/A** | none required today |
| Aggregate boundaries | **PASS** | one aggregate ↔ one owner; cross-aggregate by id only (`docs/05` §3.3) |
| Cascade rules | **PASS** | CASCADE only for dependent parts (driver↔user, tracking↔shipment, owned children); RESTRICT for referenced master data + tenant |
| Circular dependencies | **PASS** | FK graph is a DAG; `equipment_categories.parent_id`→self is a tree, not a cycle; AI Ops↔Equipment is event/advisory (no FK) |
| Optional vs required | **PASS** | nullable FKs (`driver_id`, `vehicle_id`, `order_id`, `equipment_id`, geo, recorder) are intentional |
| Domain violations | **PASS** | assignment kept as Shipment columns (not a leaked Driver/Vehicle coupling) |

**Relationship findings:** (F-REL-1, Low) tenants→child `RESTRICT` means tenant offboarding requires an explicit ordered purge (right-to-erasure job) — designed (`docs/03` §8.5) but unbuilt. (F-REL-2, Low) nullable `claims.shipment_id/equipment_id` and `shipments.order_id` are correct but require service-layer business-rule enforcement.

---

## 4. Constraint Matrix

| Constraint class | Built (M1) | Designed/Structural | Findings |
|---|---|---|---|
| **Primary keys** | uuid4 on all 8 built tables | UUIDv7 on append-heavy (event/audit/predictions/projections); composite PK on partitioned tables | F-CON-1 (Med): tracking PK must become `(id, event_time)` at partitioning |
| **Foreign keys** | 13 FKs incl. 6× `tenant_id`→tenants(RESTRICT) | all cross-aggregate links by id w/ ON DELETE | every FK column is indexed (✔ `docs/03` §3.3) |
| **Unique (per-tenant composite)** | `(tenant_id,email)`, `(tenant_id,code)`, `(tenant_id,plate_number)`, `(tenant_id,vin)`, `(tenant_id,user_id)`, `(tenant_id,license_number)`, `(tenant_id,reference_code)` | `(tenant_id, order_ref/customer_code/contract_no/claim_no/permit_no/invoice_no/asset_tag/route_code)` | **PASS** — single-column uniques correctly dropped in `0003` |
| **Composite keys** | `processed_events (consumer,event_id)` [designed] | `event_store UNIQUE(aggregate_id, aggregate_version)` (concurrency) | concurrency UK depends on `version` column — **not yet on aggregates** (see F-CON-4) |
| **Check (domain)** | `ck_shipments_weight_positive/volume_positive`, `ck_tenants_status`, `ck_tenants_isolation_mode` | `price ≥ 0`, geo bounds, `currency_code ~ '^[A-Z]{3}$'`, enum CHECKs, temporal sanity | F-CON-2 (Med): `price_sar ≥ 0`, geo-bounds, temporal-sanity CHECKs **designed but not built** |
| **Enums (VARCHAR+CHECK)** | role, vehicle_status, shipment_status, tracking_type, tenant status/isolation | order/equipment/permit/claim/contract statuses | **PASS** — additive evolution (no native ENUM) |
| **Business / cross-table** | exclusivity (one active assignment per driver/vehicle) | warehouse capacity over many shipments | F-CON-3 (**High**): the **partial-unique "one active assignment" indexes** (`docs/03` §4.2) are **NOT built** — driver/vehicle double-booking is currently only guarded in service code, not the DB |
| **Optimistic-lock `version`** | **absent** | required on every aggregate (ADR-004, `docs/03` §0) | F-CON-4 (**High**): no `version` column → no DB-level optimistic concurrency; blocks the event-store `aggregate_version` model |

---

## 5. Index Catalog

### 5.1 Built (migration `0003` + baseline)

| Index | Table | Type | Serves |
|---|---|---|---|
| `ix_<t>_tenant_id` (×6) | all aggregates | btree (FK-backing) | tenant-scoped scans; FK joins/deletes |
| `ix_users_email` | users | btree (now **non-unique**) | login lookup (platform-scoped) |
| `ix_shipment_tracking_events_shipment_id_event_time` | tracking | composite btree | ordered history + monotonic guard |
| per-tenant unique constraints (×7) | aggregates | unique btree | business keys |

### 5.2 Designed / recommended (not built)

| Type | Target | Purpose | State |
|---|---|---|---|
| **Partial** | `shipments (tenant_id,status) WHERE not terminal` | ops board live list | [DESIGNED] |
| **Partial** | `shipments (tenant_id,status,required_vehicle_type) WHERE status='ready' AND driver_id IS NULL` | offer feed | [DESIGNED] |
| **Partial** | `shipments (tenant_id,delivery_due_at) WHERE not terminal` | SLA sweep | [DESIGNED] |
| **Partial-unique** | `shipments (tenant_id,driver_id) / (tenant_id,vehicle_id) WHERE status IN ('assigned','in_transit')` | **one active assignment** (see F-CON-3) | [DESIGNED] — **build at M3/M4** |
| **Partial** | `event_store (published_at) WHERE published_at IS NULL` | outbox poll | [DESIGNED] |
| **BRIN** | `tracking.event_time`, `event_store.occurred_at`, `audit_log.at` | cheap time-range on append tables | [DESIGNED] |
| **GIN (jsonb_path_ops)** | `event_store.payload`, `tenants.settings`, `ml_predictions.output` | JSONB containment | [DESIGNED] |
| **GIN (pg_trgm)** | `shipments.reference_code`, names/addresses | fuzzy search | [DESIGNED] |
| **HNSW (pgvector)** | `embeddings.embedding` | ANN semantic search | [DESIGNED] |
| **GiST (PostGIS)** | `warehouses`/`route_restrictions` geography | nearest/geofence (triggered) | [DESIGNED] |
| **Covering (INCLUDE)** | `proj_active_shipments (...) INCLUDE (driver_id,eta)` | index-only console reads | [DESIGNED] |

**Index findings:** (F-IDX-1, Med) `tenants.settings` is `JSONB` but no GIN index is declared for settings containment if queried. (F-IDX-2, Low) the `ix_users_email` non-unique index is correct for platform-scoped login but means email lookups are not tenant-leading; acceptable because login is platform-scoped. (F-IDX-3, Med) **no specialized index is built yet** (all partial/BRIN/GIN/HNSW are M2+); the live tracking table will rely on the one composite index until then.

---

## 6. Security Review

| Area | State | Assessment |
|---|---|---|
| **Row-Level Security** | **BUILT (M1)** — `ENABLE` + **`FORCE`** + `tenant_isolation` policy on all 6 aggregates | Design is correct (fail-closed when GUC unset; platform nil-UUID branch). **But see F-SEC-1.** |
| **Tenant GUC propagation** | BUILT — `after_begin` listener applies `SET LOCAL app.current_tenant`; JWT `tid` claim sets it pre-query | Correct chokepoint for pooled connections; login/refresh run platform-scoped |
| **RLS verification** | **NOT RUN against PostgreSQL** | F-SEC-2 (**Critical condition**): the cross-tenant isolation test is written but **skipped without `TEST_DATABASE_URL`**; the isolation guarantee is unproven in CI |
| **Least-privilege DB roles** | **NOT BUILT** | F-SEC-1 (**Critical condition**): RLS — **even FORCE — is bypassed by PostgreSQL superusers**; the default `DATABASE_URL` connects as the `postgres` superuser, so RLS currently provides **no isolation** in the default setup. A dedicated **non-superuser, non-owner** app role with explicit grants is mandatory before any tenant data |
| **Immutability grants** | NOT BUILT | event/audit/tracking should be `INSERT`/`SELECT`-only for the app role (`docs/03` §6) — depends on the role above |
| **PII inventory** | identified, not protected | `users.email/full_name`, `drivers.license_number/phone_number`, addresses are **PII stored in plaintext** |
| **Encryption at rest** | NOT ADDRESSED | F-SEC-3 (High): no column-level encryption/tokenization for PII; relies on disk/volume encryption only (undocumented) |
| **Encryption in transit** | partial | DB URL/TLS not enforced in config; `sslmode` not pinned |
| **Hashing** | OK | passwords via bcrypt (`passlib`), tunable work factor |
| **Data masking** | NOT ADDRESSED | F-SEC-4 (Med): no masking policy for support/analytics reads of PII |
| **Secrets / KMS / key rotation** | weak | F-SEC-5 (High): `secret_key` is env-driven with an insecure default; **no KMS, no rotation policy, no ADR** (ADR-012 pending) |
| **Access control / RBAC** | BUILT (coarse) | one role per user + `require_permissions`; fine-grained `Role`/`Permission` aggregates planned |
| **Audit logs** | designed, not built | 3-layer model (column lineage / trigger `audit_log` / domain `event_store`); none built; **column-lineage actor columns missing (F-SEC-6 / F-CON-4)** |
| **Column-level security** | NOT ADDRESSED | acceptable to defer; note for regulated tenants |

**Security verdict:** the **design** is strong, but the **as-built RLS provides no real isolation under the default superuser connection**, and isolation is **unverified**. These are the dominant production blockers.

---

## 7. Multi-Tenant Review

| Aspect | State | Assessment |
|---|---|---|
| `tenant_id` everywhere | **BUILT** | NOT NULL + FK(RESTRICT) + index on all 6 aggregates; `tenants` is the boundary (no `tenant_id`) — correct |
| Isolation model | shared-schema + RLS | sound (ADR-001); hybrid `isolation_mode='dedicated'` escape hatch present in `tenants` |
| Shared vs dedicated tables | all shared | `dedicated` routing is design-only |
| **Cross-tenant leakage** | **at risk** | F-SEC-1 (superuser bypass) + F-SEC-2 (unverified) are the leakage vectors; projections fixed in design (ADR-006 6.5 amendment) but unbuilt |
| Tenant constraints | **BUILT** | per-tenant composite uniques verified in `0003` |
| Tenant indexes | **BUILT** | tenant-leading FK index on every aggregate |
| Pooled-connection `SET LOCAL` | BUILT, **unverified** | listener uses `set_config(...,is_local=true)`; no-leak test is Postgres-gated |
| Platform/admin access | designed | nil-UUID GUC = platform "see all" branch; **must be restricted to a platform role**, not the default app path |

**Findings:** (F-MT-1, Critical condition) = F-SEC-1/F-SEC-2 combined: tenancy is **not production-trustworthy until** a non-superuser role is used **and** the isolation test is green in CI. (F-MT-2, Med) the platform "see all" policy branch keyed on the nil-UUID GUC is convenient but means any path that fails to set the GUC to a real tenant under a non-superuser role is **deny-all (safe)** — good — yet any code that erroneously sets the platform GUC is **see-all (dangerous)**; restrict who can set platform scope.

---

## 8. Event Sourcing / Eventing Review

> Model is **CQRS-lite, not full event sourcing** (ADR-004): the relational aggregate is the source of truth; `event_store` is the durable log + transactional outbox.

| Object | State | Assessment |
|---|---|---|
| `event_store` | **DESIGNED, not built** | UUIDv7 PK, `UNIQUE(aggregate_id, aggregate_version)`, monthly partition, full envelope — sound; **depends on the missing `version` column (F-CON-4)** |
| `outbox` (within `event_store.published_at`) | DESIGNED | single-transaction write + relay; ADR-007 now has Migration + Rollback (6.5) |
| `processed_events` | DESIGNED | per-consumer idempotency `(consumer,event_id)` — correct |
| `snapshots` | **N/A (intentional)** | CQRS-lite keeps the aggregate as the live "snapshot"; ES snapshots not required — documented, not a gap |
| `projections` (`proj_*`) | DESIGNED | rebuildable from log; **now tenant_id+RLS** (6.5 amendment) |
| Event versioning | DESIGNED | `event_type` + envelope `version`; upcasting strategy not yet specified (F-ES-1, Med) |
| Idempotency | DESIGNED | consumers dedupe on `event_id`; API dedupe via `idempotency_keys` |
| Replay capability | DESIGNED | replay rebuilds projections (not aggregates) |
| Ordering | DESIGNED | per-aggregate via `aggregate_version`; no global order (intentional) |
| Event metadata | DESIGNED | `correlation_id`/`causation_id`/`occurred_at`/`recorded_at`/`tenant_id` — strong |
| Dead-letter | DESIGNED | flag/relocate after N retries (`docs/11` §6) — no DLQ table yet (F-ES-2, Med) |

**Findings:** (F-ES-1, Med) no **event-schema upcasting/versioning policy** for evolving payloads. (F-ES-2, Med) no explicit **dead-letter table**. (F-ES-3, **High**) the entire backbone is **unbuilt (M2)** and is a hard prerequisite for every event-driven context — correctly sequenced but on the critical path.

---

## 9. AI Readiness Review

| Capability | Object | State | Assessment |
|---|---|---|---|
| Vector / embeddings | `embeddings` (pgvector + HNSW) | DESIGNED | strong; tenant-scoped |
| Feature store | `ml_features_shipment` (point-in-time) | DESIGNED | avoids target leakage; offline/online parity |
| Inference / prediction history | `ml_predictions` (+ `actual_outcome`) | DESIGNED | closes the feedback loop; reproducible via `model_version`+`features_ref` |
| RAG storage / knowledge base | `documents` + `document_chunks` | DESIGNED | corpus + chunk embeddings; RLS-scoped |
| **Model registry** | — | **MISSING** | F-AI-1 (Med): no table for model name/version/lineage/metrics/stage; provenance lives only in `ml_predictions` strings |
| **Prompt / LLM call logs** | — | **MISSING** | F-AI-2 (Med): no prompt/response/token/cost log for LLM/agent calls (needed for the "ops copilot") |
| **Agent memory** | — | **MISSING** | F-AI-3 (Low): no conversational/agent-memory store |
| **Explicit feedback table** | (via `ml_predictions.actual_outcome`) | partial | F-AI-4 (Low): feedback is a column, not a first-class table; fine for ML, thin for human-in-the-loop labeling |
| Vector DB readiness | pgvector in-DB | DESIGNED | sound at current scale; external vector DB deferred |
| Governance | tenant-scoped, PII-disciplined | DESIGNED | no cross-tenant training; PII excluded/hashed before embedding |

**AI verdict:** the **ML substrate** (predict → feedback → retrain) and **RAG** are well-designed; the **LLM/agent platform** layer (model registry, prompt logs, agent memory) is **absent** and should be added to **ADR-010 (MLOps, deferred to M8)**. All AI tables are unbuilt — not blocking for the M1–M5 path.

---

## 10. Performance Review

| Concern | Assessment |
|---|---|
| Large-table growth | `shipment_tracking_events`, `event_store`, `audit_log` are the hot/large tables → **monthly RANGE partition + BRIN** (designed, unbuilt) |
| Hot tables | `shipments` (very high read/write) — partial indexes + projections offload reads |
| Read bottlenecks | control-tower reads offloaded to `proj_*` (p95 < 300 ms target) — projections unbuilt |
| Write bottlenecks | two-writes-per-command (aggregate + event) inside one txn — bounded by lean payloads; relay decouples publish |
| Locking / deadlocks | optimistic concurrency via `version` (**unbuilt, F-CON-4**) + per-aggregate `aggregate_version` minimize contention; FK RESTRICT on `tenants` is low-risk |
| Partitioning | designed (monthly; LIST sub-partition by tenant for large tenants) — **unbuilt** |
| Archiving | partition-drop retention (no giant DELETEs) — unbuilt |
| Caching | Redis present; query/result caching strategy not specified (F-PERF-1, Low) |
| Materialized views vs read models | chose `proj_*` tables (ADR-006) over matviews — sound |
| CQRS optimization | read/write split designed; unbuilt |

**Findings:** (F-PERF-1, Low) no explicit Redis caching policy for hot reference reads. (F-PERF-2, Med) the partial-unique active-assignment indexes (F-CON-3) are also a **performance** safeguard (cheap exclusivity) — their absence pushes the check into application transactions. (F-PERF-3, Low) connection-pool sizing (`db_pool_size=5`) is conservative for the SMB envelope; revisit under load (M9).

---

## 11. Risk Register

Severity: **Critical** = blocks production go-live / real-tenant data · **High** = must fix in the owning milestone · **Medium** = should fix · **Low** = track. (No item below is an unresolved *design* defect that halts implementation; the design is frozen.)

| ID | Severity | Problem | Impact | Root cause | Recommendation | Owner / fix effort |
|---|---|---|---|---|---|---|
| **R-1** | **Critical** | RLS is bypassed by PostgreSQL superusers; default `DATABASE_URL` uses the `postgres` superuser | **Total loss of tenant isolation** in the default config despite RLS being "on" | M1 built RLS but not the non-superuser role/grants | Create a dedicated **non-superuser, non-owner** app role; grant least privilege; forbid superuser in non-dev; document `sslmode` | M1.5 — **S–M** |
| **R-2** | **Critical** | Cross-tenant isolation test not executed against PostgreSQL | Isolation guarantee **unproven**; regressions undetectable | no Postgres/CI in the build env; test is gated | Stand up Postgres in CI with a **non-superuser** `TEST_DATABASE_URL`; make the isolation test a **required gate** before M2 | M1.5 — **S** |
| **R-3** | **High** | `version` (optimistic lock), `created_by`/`updated_by`, `deleted_at`, `currency_code` not delivered by M1 | No DB concurrency control, soft-delete, actor-audit, or multi-currency; blocks event-store `aggregate_version` and §6 column-lineage audit | M1 scoped to `tenant_id` only; §0 rollout incomplete | Complete the `docs/03` §0 column rollout (additive migration) as **M1.5/early M2** | **M** |
| **R-4** | **High** | "One active assignment per driver/vehicle" partial-unique indexes not built | DB cannot prevent double-booking; relies solely on service-layer guards (race-prone under concurrency) | deferred with the contexts | Build the partial-unique indexes (`docs/03` §4.2) with the assignment path (M3/M4) | **S** |
| **R-5** | **High** | Event store / outbox / audit backbone unbuilt | CQRS-lite/EDA non-functional; no domain audit; every event-driven context blocked | sequenced to M2 | Execute M2 per ADR-007 Migration Plan; hard prerequisite gate | M2 — **L** |
| **R-6** | **High** | No PII encryption/tokenization; weak secrets, no KMS/rotation | Regulatory/breach exposure for `email`, `license_number`, `phone`, addresses | KMS/secrets ADR (ADR-012) pending | Author ADR-012; column-encrypt/tokenize PII; enforce strong `secret_key`; pin TLS | M9 (ADR now) — **M** |
| **R-7** | **Med** | `shipment_tracking_events` PK is `id`, not the partition-inclusive `(id, event_time)` | Partitioning at M2 requires a PK change on a large/append table | as-built simplification | Plan the composite-PK migration as part of M2 partitioning | M2 — **M** |
| **R-8** | **Med** | Domain CHECKs (`price≥0`, geo bounds, temporal sanity, currency shape) designed not built | Weaker data integrity until added | additive, deferred | Add with the §0 rollout (R-3) | **S** |
| **R-9** | **Med** | AI platform gaps: no model registry, prompt/LLM logs, agent memory; feedback is a column | Limits LLM/agent ops, lineage, cost tracking | scoped to ML substrate first | Fold into ADR-010 (MLOps); add tables at M8 | M8 — **M** |
| **R-10** | **Med** | Event upcasting/versioning policy + dead-letter table unspecified | Payload evolution + poison-message handling undefined | detail deferred | Specify upcasting + a `dead_letter` table in M2 | M2 — **S** |
| **R-11** | **Med** | SMB scale envelope (ADR-002/003) vs enterprise ambition; OLAP deferred | Throughput ceiling (~5k ev/s) | deliberate | Track revisit triggers; ADR-015 (OLAP/throughput) at M9 | M9 — **track** |
| **R-12** | **Low** | No caching policy, conservative pool sizing, no masking policy | Minor perf/ops/privacy polish | deferred | Address in M6/M9 | **S** |

---

## 12. Final Database Freeze Report

### 12.1 Scores

| Dimension | Score |
|---|---|
| Architecture (design) | **90 / 100** |
| Scalability | **76 / 100** |
| Security | **58 / 100** |
| Performance | **80 / 100** |
| Maintainability | **86 / 100** |
| AI readiness | **70 / 100** |
| **Overall production readiness** | **52 / 100** |

### 12.2 Findings summary

- **Critical (production go-live blockers): 2** — R-1 (superuser bypasses RLS / no least-privilege role), R-2 (RLS isolation unverified in CI).
- **High: 4** — R-3 (§0 columns: version/audit/soft-delete/currency), R-4 (active-assignment partial-uniques), R-5 (M2 event backbone), R-6 (PII encryption / KMS).
- **Medium: 5** — R-7…R-11.
- **Low: 1** — R-12.
- **Resolved (prior phases): C-1 Order-cancel, CF2 event ownership, CF3 catalog drift, CF9 cascade-delete, CF10 projection tenancy** — all closed in Phase 6.5; not re-opened.

### 12.3 Recommended improvements (ordered)

1. **R-1 + R-2 together (M1.5):** create the non-superuser app role + least-privilege grants; run the Postgres isolation test as a **required CI gate**. *Nothing tenant-facing ships until both are green.*
2. **R-3 (M1.5/early M2):** additive migration for `version`, `created_by`, `updated_by`, `deleted_at`, `currency_code` + domain CHECKs (R-8).
3. **R-5 + R-7 + R-10 (M2):** event_store/outbox/processed_events/audit_log with partition-inclusive PKs, immutability grants, upcasting + dead-letter.
4. **R-4 (M3/M4):** active-assignment partial-uniques with the assignment path.
5. **R-6 (ADR-012 now; build M9):** PII encryption/tokenization, secrets/KMS/rotation, TLS pinning.
6. **R-9 (ADR-010; build M8):** model registry, prompt/agent logs.

### 12.4 Final approval

# ⚠ APPROVED WITH CONDITIONS

**Rationale.** The database **design is frozen, coherent, and free of unresolved Critical design defects** — implementation may continue, and M2 (event backbone) is the correct next build. The two **Critical findings are as-built / verification conditions, not design defects**, so they gate **production go-live and real-tenant onboarding**, not continued development.

**Binding conditions (must all be satisfied before production / any real tenant data):**
1. **R-1** — application connects as a **non-superuser, non-owner** role with least-privilege grants (RLS effective); superuser connections forbidden outside local dev.
2. **R-2** — the **cross-tenant isolation test passes in CI against PostgreSQL** under that non-superuser role, and is a required merge gate.
3. **R-3** — the **§0 lifecycle columns** (`version`, `created_by`, `updated_by`, `deleted_at`, `currency_code`) are delivered before contexts that depend on optimistic concurrency / soft-delete / the event-store `aggregate_version`.
4. **R-5** — the **M2 event-store/outbox/audit** backbone ships before any event-driven consumer/saga (standing rule: no consumer before M2).

**Conditions for full ✅ APPROVED:** close R-1…R-6 (Critical + High). Until then the freeze authorizes **continued implementation only**, not production.

---

*End of Final Database Review & Freeze. Documentation only — no implementation code, models, SQL, or migrations produced. Reflects the as-built state through milestone M1 (multi-tenancy + RLS) and the frozen design corpus (`docs/01`–`docs/12`, ADR-001…009).*
