# Phase 2 — Architecture & Domain Overview

Status: **Draft for approval.** Builds on the existing FastAPI backend; nothing here
contradicts the current code (it extends it). All diagrams live in `docs/diagrams/`.

## 1. Architectural style
- **DDD + Clean Architecture** (already reflected in the layering below).
- **CQRS-lite + event-driven** (ADR-004): aggregate is source of truth; append-only
  events feed projections (ADR-006) and async workers (ADR-003).
- **Multitenant** via row-level `tenant_id` + RLS (ADR-001).
- **Versioned API** under `/v1` (ADR-005).

## 2. Layering (matches `app/`)
```
api/routes/*      → thin HTTP handlers, RBAC via require_roles      (Interface)
schemas/*         → Pydantic request/response contracts            (Interface DTOs)
services/*        → business rules, transitions, capacity          (Application)
models/*          → SQLAlchemy aggregates + enums                  (Domain)
repositories/*    → persistence boundary                          (Infrastructure)
db/*, core/*      → session, base, config, security                (Infrastructure)
```
**Add in Phase 4:** `events/` (domain event types + bus), `projections/` (read-model
builders), `workers/` (Celery tasks), `api/deps.py` (tenant scope), `migrations/`.

## 3. Bounded contexts
| Context | Aggregates | Status |
|---|---|---|
| Identity & Access | User, Role | exists; **RBAC enforced**, add tenant + self-service |
| Fleet & Capacity | Driver, Vehicle, Warehouse | exists |
| Order & Execution | **Shipment** (root), assignment | exists; richest logic |
| Tracking & Events | ShipmentTrackingEvent (append-only) | exists |
| Read Models / Intelligence | projections, KPIs | **new** (ADR-006) |
| Billing & Settlement | pricing, settlement | **new** (driver app needs fare) |
| Notifications | push/SMS | **new** (integration) |

## 4. Shipment lifecycle (authoritative)
See `docs/diagrams/shipment-state-machine.mmd` — transcribed verbatim from
`services/shipment_service.py::_is_transition_allowed`. Terminal: `delivered`,
`cancelled`, `returned`, `failed`. Tracking-event creation enforces **monotonic
`event_time`** and can carry a guarded status change.

## 5. Cross-cutting concerns
| Concern | Decision |
|---|---|
| AuthN | JWT bearer (`sub`, `role`, `exp`, `iat`), bcrypt; OAuth2 password flow today, **add phone+OTP** for drivers |
| AuthZ | `require_roles(...)`; add **resource ownership** (driver↔own shipment) and tenant scope |
| Concurrency | add `version` column → optimistic locking on `shipments` (ADR-004) |
| Idempotency | event `event_id` keys; accept/assign idempotent |
| Observability | Prometheus metrics, structured logs, projection-lag gauge |
| Migrations | **Alembic** baseline (this phase) → autogenerate thereafter |
| Errors | typed service exceptions → HTTP mapping (already in routes) + uniform error schema |

## 6. Open gaps surfaced this phase
1. **`/v1` prefix** not yet applied (ADR-005).
2. **Driver self-service endpoints** missing — see `docs/api-gap-analysis.md`.
3. **No `tenant_id`** yet — ADR-001 migration required.
4. **No pricing/cargo/route enrichment** — new Billing + maps integration.
5. **No optimistic-concurrency `version`** on shipments.

## 7. Phase 2 exit criteria (gate)
- [ ] ADR-001…006 reviewed & accepted.
- [ ] ERD + state + sequence + deployment diagrams approved.
- [ ] Event catalog + glossary agreed as ubiquitous language.
- [ ] `api/openapi.yaml` `/v1` draft reviewed.
- [ ] Alembic baseline runs clean against current models.
- [ ] API gap backlog accepted into Phase 4 plan.
