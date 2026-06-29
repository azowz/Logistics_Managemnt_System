# 18 — Order Domain (Sprint 4)

> Status: **Implemented** (Sprint 4). Builds on the frozen architecture of
> ADR-001…009, the Event Backbone (M2, docs/14), and the Customer Domain
> (Sprint 3). Multi-tenant, event-sourced-at-the-edges (transactional outbox),
> CQRS-ready.

---

## 1. Overview

The **Order** aggregate is the customer's request to move cargo from a pickup
location to a delivery location. It is the upstream commercial aggregate that
dispatch/fulfilment is driven from. An Order owns a **lifecycle state machine**
and emits a domain event on every meaningful change.

- **Tenancy:** every row carries `tenant_id`; isolated by PostgreSQL Row-Level
  Security (ADR-001) and the per-transaction `app.current_tenant` GUC.
- **Concurrency:** optimistic locking via `version` (ADR-004).
- **Lifecycle:** soft-delete (`deleted_at` / `deleted_by`) + restore.
- **Auditing:** `created_by` / `updated_by` / `deleted_by`; every state change is
  appended to the unified `event_store` in the same transaction (transactional
  outbox, ADR-007).

### 1.1 Reconciliation note (docs vs. Sprint 4 brief)

`docs/04` and `docs/11` describe an *order-management* Order (order lines,
`fulfilling/completed` states, fan-out saga, credit-gating). The Sprint 4 brief
specified a *transport* Order (pickup/delivery, cargo, dispatcher,
`draft → … → delivered`). **Sprint 4 implements the brief.** The richer
order-management model from `docs/04`/`docs/11` (OrderLine, fan-out to Shipments,
billing/credit sagas) remains a planned, separate concern and is tracked as a
reconciliation item — it was **not** silently merged or discarded.

---

## 2. Aggregate / Model

`app/models/order.py` → table `orders` (44 columns).

| Group | Columns |
|---|---|
| Identity | `id` (uuid4 PK), `tenant_id` (FK→tenants, RESTRICT), `customer_id` (FK→customers, RESTRICT), `order_number` (unique per tenant) |
| Classification | `order_type`, `order_source`, `priority` |
| Lifecycle | `status` |
| Scheduling | `requested_pickup_date`, `requested_delivery_date` |
| Locations | `pickup_location`, `delivery_location`, `pickup_latitude/longitude`, `delivery_latitude/longitude`, `distance_km`, `estimated_duration_minutes` |
| Cargo | `cargo_description`, `cargo_weight_kg`, `cargo_volume_m3`, `dangerous_goods`, `temperature_requirements`, `is_fragile`, `insurance_required` |
| Instructions | `special_instructions` |
| Assignment | `assigned_dispatcher_id` (FK→users, SET NULL) |
| Lifecycle timestamps | `submitted_at`, `approved_at`, `scheduled_at`, `assigned_at`, `picked_up_at`, `delivered_at`, `cancelled_at`, `failed_at`, `cancellation_reason`, `failure_reason` |
| Timestamps/audit | `created_at`, `updated_at`, `created_by`, `updated_by` |
| Soft delete | `deleted_at`, `deleted_by` |
| Concurrency | `version` (`__mapper_args__["version_id_col"]`) |

### 2.1 Invariants (DB-enforced)

- `uq_orders_tenant_id_order_number` — order number unique per tenant.
- `ck_orders_status`, `ck_orders_order_type`, `ck_orders_order_source`,
  `ck_orders_priority` — enum values constrained (stored as lowercase **values**
  via `SAEnum(..., values_callable=...)`).
- `ck_orders_cargo_weight_non_negative`, `ck_orders_cargo_volume_non_negative`,
  `ck_orders_distance_non_negative`.

### 2.2 Enums (`app/models/enums.py`)

- `OrderType` = standard | express | same_day | economy | return
- `OrderSource` = web | mobile | api | phone | email | walk_in
- `OrderPriority` = low | normal | high | urgent
- `OrderStatus` = draft | submitted | approved | scheduled | assigned | in_transit | delivered | cancelled | failed

---

## 3. State Machine

`app/services/order_policies.py → OrderStateMachine` is the single source of
truth for transitions; `OrderService` delegates every status change to it.

```
        ┌─────────┐  submit   ┌───────────┐ approve  ┌──────────┐ schedule ┌───────────┐
        │  DRAFT  │ ────────▶ │ SUBMITTED │ ───────▶ │ APPROVED │ ───────▶ │ SCHEDULED │
        └────┬────┘           └─────┬─────┘          └────┬─────┘          └─────┬─────┘
             │                      │                     │                      │ assign
             │                      │                     │                      ▼
             │                      │                     │                ┌───────────┐
             │                      │                     │                │ ASSIGNED  │
             │                      │                     │                └─────┬─────┘
             │                      │                     │                      │ start-transit
             │                      │                     │                      ▼
             │                      │                     │                ┌────────────┐ deliver ┌───────────┐
             │                      │                     │                │ IN_TRANSIT │ ──────▶ │ DELIVERED │ (terminal)
             │                      │                     │                └─────┬──────┘         └───────────┘
             ▼                      ▼                     ▼                      ▼
        ┌──────────────────────────────────────────────────────────────────────────┐
        │  CANCELLED (terminal)        FAILED (terminal)                             │
        └──────────────────────────────────────────────────────────────────────────┘
```

- `cancel` is allowed from any non-terminal state. Cancelling from `assigned` or
  `in_transit` sets `OrderCancelled.compensation_required = true` (downstream
  compensation hook).
- `fail` is allowed from `submitted | approved | scheduled | assigned | in_transit`.
- `delivered`, `cancelled`, `failed` are terminal; a same-state transition is an
  idempotent no-op (no event, no commit).
- Terminal orders cannot be edited (`update_order` raises `ValidationError`).

Allowed transitions (`OrderStateMachine.ALLOWED_TRANSITIONS`):

| From | To |
|---|---|
| draft | submitted, cancelled |
| submitted | approved, cancelled, failed |
| approved | scheduled, cancelled, failed |
| scheduled | assigned, cancelled, failed |
| assigned | in_transit, cancelled, failed |
| in_transit | delivered, cancelled, failed |
| delivered / cancelled / failed | — (terminal) |

---

## 4. Domain Events (16)

`app/events/order_events.py` — all `@dataclass(frozen=True, slots=True)`,
`@register_event`, `event_version = 1`. Registered at import via
`app/events/__init__.py`. Wrapped in `EventEnvelope` with
`aggregate_type="Order"` and written to `event_store` in the same transaction.

| Event | Emitted by | Key payload |
|---|---|---|
| `OrderCreated` | `create_order` | customer_id, order_number, type/source/priority/status |
| `OrderSubmitted` | `submit_order` | previous_status |
| `OrderApproved` | `approve_order` | previous_status, reason |
| `OrderScheduled` | `schedule_order` | previous_status |
| `OrderAssigned` | `assign_order` | assigned_dispatcher_id, previous_status |
| `OrderPickedUp` | `start_transit_order` | picked_up_at, previous_status |
| `OrderInTransit` | `start_transit_order` | previous_status |
| `OrderDelivered` | `deliver_order` | delivered_at, previous_status |
| `OrderCancelled` | `cancel_order` | previous_status, reason, compensation_required |
| `OrderFailed` | `fail_order` | previous_status, reason |
| `OrderRestored` | `restore_order` | — |
| `OrderUpdated` | `update_order` | changed_fields |
| `OrderPriorityChanged` | `update_order` | previous_priority, new_priority |
| `OrderAddressChanged` | `update_order` | changed_fields (location fields) |
| `OrderStatusChanged` | every transition | previous_status, new_status, reason |
| `OrderDeleted` | `delete_order` | deleted_by |

> **Note (debt):** payloads duplicate `tenant_id` to stay consistent with the
> Sprint 3 `customer_events` precedent; it is also present on the envelope. A
> single cross-cutting cleanup is tracked for both domains.

---

## 5. API

Base path `/v1/orders`. RBAC via `require_roles` (least privilege). `/search`
is declared **before** `/{order_id}` so the literal path wins.

| Method | Path | Roles | Result |
|---|---|---|---|
| POST | `/orders` | ADMIN, MANAGER | 201; 409 dup number; 422 unknown customer/validation |
| GET | `/orders` | ADMIN, MANAGER, CLIENT, DRIVER | 200 `Page[OrderRead]` |
| GET | `/orders/search` | ADMIN, MANAGER, CLIENT, DRIVER | 200 `Page[OrderRead]` |
| GET | `/orders/{id}` | ADMIN, MANAGER, CLIENT, DRIVER | 200; 404 |
| PATCH | `/orders/{id}` | ADMIN, MANAGER | 200; 404; 422 terminal/empty |
| DELETE | `/orders/{id}` | ADMIN | 204; 404 |
| POST | `/orders/{id}/submit` | ADMIN, MANAGER | 200; 409 invalid transition |
| POST | `/orders/{id}/approve` | ADMIN, MANAGER | 200; 409 |
| POST | `/orders/{id}/schedule` | ADMIN, MANAGER | 200; 409 |
| POST | `/orders/{id}/assign` | ADMIN, MANAGER | 200; 409 |
| POST | `/orders/{id}/start-transit` | ADMIN, MANAGER, DRIVER | 200; 409 |
| POST | `/orders/{id}/deliver` | ADMIN, MANAGER, DRIVER | 200; 409 |
| POST | `/orders/{id}/cancel` | ADMIN, MANAGER | 200; 409 |
| POST | `/orders/{id}/fail` | ADMIN, MANAGER, DRIVER | 200; 409 |
| POST | `/orders/{id}/restore` | ADMIN | 200; 404; 422 not-deleted |

Filtering (`GET /orders`, `/orders/search`): `q` (order number, cargo
description, special instructions, pickup/delivery location), `status`,
`order_type`, `order_source`, `priority`, `customer_id`,
`assigned_dispatcher_id`, `include_deleted`. Sorting: `sort_by` (whitelist) +
`sort_dir`. Pagination: `page` + `size` (≤200).

---

## 6. Layering & Unit of Work

```
HTTP  ─▶ app/api/routes/orders.py      (thin; RBAC; DTO in/out; no business logic)
        └─▶ app/services/order_service.py   (validation, state machine, UoW, events)
              ├─▶ app/repositories/order_repository.py   (queries; NEVER commits)
              ├─▶ app/repositories/customer_repository.py (customer-exists check)
              ├─▶ app/repositories/event_store_repository.py (outbox append)
              └─▶ app/services/order_policies.py          (OrderStateMachine)
```

Event emission sequence (atomic):

```
create/transition
  repo.create/update            # session.add / setattr — NO commit
  session.flush()               # assign id / apply changes
  event_store.append(envelope)  # outbox row + audit row, same txn
  session.commit()              # aggregate + event committed together
  session.refresh()             # return canonical state
```

Repositories never commit — the service owns the unit of work, so a future
Order→Shipment fan-out can compose multiple writes in one transaction.

---

## 7. Database migration

`migrations/versions/0007_order_domain.py` (`down_revision = "0006_customer_domain"`):
creates `orders` with all columns, PK/FK/unique/check constraints (explicit
names per `NAMING_CONVENTION`), five indexes, and PostgreSQL Row-Level Security
(`ENABLE` + `FORCE` + `tenant_isolation` policy with the nil-UUID platform
escape hatch), guarded by `_is_postgres()` so SQLite/test runs skip RLS.
`downgrade()` reverses policy, indexes, and table.

---

## 8. Tests & Coverage

| File | Scope |
|---|---|
| `tests/test_order_model.py` | columns, enums, soft-delete, version mapper, constraint names |
| `tests/test_order_events.py` | 16 events registered, frozen, envelope payloads |
| `tests/test_order_service.py` | mocked repos/events: create, validation, state machine, delete/restore |
| `tests/test_order_routes.py` | SQLite TestClient: CRUD, lifecycle, search, pagination, tenant isolation |

Order-domain line coverage **≈99%** (target 90%). Full suite: **507 passed, 13
skipped** (skips are PostgreSQL-only RLS tests gated on `TEST_DATABASE_URL`).
