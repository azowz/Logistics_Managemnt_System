# 19 — Shipment Domain (Sprint 5)

> Status: **IMPLEMENTED & VERIFIED**. This document describes the production-grade
> Shipment domain after the Sprint 5 refactor that aligned it with the Customer
> (Sprint 3) and Order (Sprint 4) patterns. It supersedes the pre-existing
> Shipment debt recorded in `docs/15-enterprise-code-audit.md` (§"ShipmentService
> does not emit domain events").

---

## 1. Domain purpose

The **Shipment** is the operational center of the logistics platform: the
physical movement of cargo from an origin warehouse to a destination warehouse,
optionally fulfilling an upstream **Order**, executed by an assigned
**Driver**/**Vehicle**. Shipment owns the operational lifecycle, assignment,
pickup, in-transit tracking, delivery, failure, return, and cancellation.

## 2. Aggregate ownership

| Concern | Owner |
| --- | --- |
| Aggregate root | `app/models/shipment.py::Shipment` |
| State machine | `app/services/shipment_policies.py::ShipmentStateMachine` |
| Persistence boundary | `app/repositories/shipment_repository.py::ShipmentRepository` |
| Application service / UoW | `app/services/shipment_service.py::ShipmentService` |
| Domain events | `app/events/shipment_events.py` |
| API | `app/api/routes/shipments.py` |
| Schemas | `app/schemas/shipment.py` |
| Append-only tracking slice | `ShipmentTrackingEvent` (unchanged) |

Shipment references (FK) the tenant, the client `User`, two `Warehouse`s
(origin/destination), and optionally an `Order`, `Driver`, `Vehicle`, and an
opaque `equipment_id`.

## 3. Lifecycle & state machine

```
created → ready → assigned → picked_up → in_transit → delivered
                                              │  ▲
                                              ▼  │
                                           delayed
   in-progress ──────────────────────────────────→ failed → returned
   any pre-delivery ─────────────────────────────→ cancelled
```

Authoritative transition table (`ShipmentStateMachine.ALLOWED_TRANSITIONS`):

| From | Allowed targets |
| --- | --- |
| `created` | `ready`, `cancelled` |
| `ready` | `assigned`, `cancelled` |
| `assigned` | `picked_up`, `cancelled`, `failed` |
| `picked_up` | `in_transit`, `cancelled`, `failed` |
| `in_transit` | `delayed`, `delivered`, `failed`, `returned`, `cancelled` |
| `delayed` | `in_transit`, `delivered`, `failed`, `returned`, `cancelled` |
| `failed` | `returned` |
| `delivered` / `cancelled` / `returned` | *(terminal)* |

Rules enforced:

- `delivered`, `cancelled`, `returned` are **terminal**; `failed` permits a single
  follow-on `returned` (return / compensation) and is otherwise terminal.
- **assignment requires a driver *and* a vehicle** (both tenant-owned, available,
  not already on another active shipment, and within vehicle capacity).
- pickup requires assignment; in_transit requires pickup; delivery requires
  transit (a `delayed` shipment resumes via `start_transit`).
- `delayed` is an **in-transit overlay** — it never advances the lifecycle and
  can resume to `in_transit` or proceed to a terminal outcome.
- cancellation is allowed before delivery; cancelling from a committed state
  (`assigned`/`picked_up`/`in_transit`/`delayed`) sets `compensation_required`.

## 4. Business rules (service-enforced)

`ShipmentService` validates, per the production pattern:

1. tenant context present (`ValidationError` otherwise);
2. client/order/origin-warehouse/destination-warehouse exist and belong to the
   current tenant (defence-in-depth over RLS);
3. reference code is tenant-unique (auto-generated `SHP-…` when omitted);
4. warehouse capacity is not exceeded (preserved from the legacy service);
5. on assign: driver/vehicle are tenant-owned, the driver is linked to a
   driver-role user and available, neither is on another active shipment, and the
   vehicle's weight/volume capacity covers the cargo;
6. the requested transition is legal for the current state;
7. terminal shipments cannot be edited.

Exceptions: `ValidationError` (422), `ConflictError` (409), `NotFoundError`
(404), `StatusTransitionError` (409), `AssignmentError` (409), `CapacityError`
(409) — mapped centrally by `install_exception_handlers`.

## 5. Unit-of-work & event emission

Every state-changing operation follows the Sprint 3/4 contract (repositories
never commit; the service owns the UoW):

```
validate tenant → load aggregate → validate rules → mutate →
session.flush() → DomainEvent → EventEnvelope.create() →
EventStoreRepository.append() → session.commit()
```

`aggregate_type = "Shipment"`; the event `aggregate_version` is sourced from
`EventStoreRepository.next_aggregate_version`, while the row's optimistic-lock
`version` column guards concurrent writes (ADR-004).

## 6. Domain events

Registered on import via `@register_event` (see `app/events/__init__.py`); all are
`@dataclass(frozen=True, slots=True)`, JSONB-serializable, tenant-aware, and
versioned (`event_version = 1`):

`ShipmentCreated`, `ShipmentMarkedReady`, `ShipmentAssigned`, `ShipmentPickedUp`,
`ShipmentInTransit`, `ShipmentDelayed`, `ShipmentDelivered`, `ShipmentFailed`,
`ShipmentReturned`, `ShipmentCancelled`, `ShipmentUpdated`, `ShipmentDeleted`,
`ShipmentRestored`, `ShipmentAddressChanged`, `ShipmentCargoChanged`,
`ShipmentDriverChanged`, `ShipmentVehicleChanged`, `ShipmentStatusChanged`.

Every transition emits the specific event(s) plus a general
`ShipmentStatusChanged`. Update emits `ShipmentAddressChanged` /
`ShipmentCargoChanged` / `ShipmentUpdated` partitioned by changed field group.

## 7. API contract

| Method | Path | Roles | Purpose |
| --- | --- | --- | --- |
| POST | `/shipments` | ADMIN, MANAGER | Create (status `created`) |
| GET | `/shipments` | ADMIN, MANAGER, CLIENT, DRIVER | List (filter/sort/paginate) |
| GET | `/shipments/search` | read roles | Faceted + free-text search |
| GET | `/shipments/{id}` | read roles | Retrieve |
| PATCH | `/shipments/{id}` | ADMIN, MANAGER | Partial update |
| DELETE | `/shipments/{id}` | ADMIN | Soft-delete |
| POST | `/shipments/{id}/restore` | ADMIN | Restore |
| POST | `/shipments/{id}/ready` | ADMIN, MANAGER | created → ready |
| POST | `/shipments/{id}/assign` | ADMIN, MANAGER | ready → assigned |
| POST | `/shipments/{id}/pickup` | field roles | assigned → picked_up |
| POST | `/shipments/{id}/transit` | field roles | picked_up/delayed → in_transit |
| POST | `/shipments/{id}/delay` | field roles | in_transit → delayed |
| POST | `/shipments/{id}/deliver` | field roles | → delivered |
| POST | `/shipments/{id}/fail` | field roles | → failed |
| POST | `/shipments/{id}/return` | ADMIN, MANAGER | → returned |
| POST | `/shipments/{id}/cancel` | ADMIN, MANAGER | → cancelled |
| POST | `/shipments/{id}/events` | field roles | Append tracking event (preserved) |

`/shipments/search` is declared **before** `/shipments/{id}` so the literal path
wins over the UUID converter. Routes are thin: they extract input, enforce RBAC,
and delegate; domain exceptions are translated by the global handlers.

## 8. Security & tenant isolation

- `tenant_id` is **never** accepted from the client — it is read from the
  request context (`get_current_tenant`) and stamped on create.
- Row-Level Security is enabled on `shipments` (migration 0003); the service
  additionally validates that every referenced aggregate (`client`, `order`,
  `origin/destination warehouse`, `driver`, `vehicle`) belongs to the caller's
  tenant — preventing cross-tenant IDOR / FK assignment.
- RBAC is enforced on every endpoint via `require_roles`.
- Actor attribution (`created_by` / `updated_by` / `deleted_by`, event `user_id`)
  is captured from the authenticated principal.

## 9. Database

Migration **`0008_shipment_domain`** is additive and backward-compatible:

- New nullable columns: `order_id` (FK `orders` SET NULL), `cargo_description`,
  `equipment_id`, `picked_up_at`, `failed_at`, `return_reason`, `deleted_by`.
- New `priority` column (NOT NULL, default `normal`) + value CHECK.
- Indexes: `status`, `priority`, `order_id`, `driver_id`, `vehicle_id`,
  `delivery_due_at`; PostgreSQL partial indexes for ready-unassigned offers and
  active driver/vehicle assignment exclusivity.
- The `status` column is a plain VARCHAR (`Enum(create_constraint=False)`), so the
  new `picked_up` / `delayed` states needed no constraint migration.

`tenant_id` (0003) and the optimistic-lock/audit columns (0004) already existed.
All PostgreSQL-specific operations are guarded by `_is_postgres()`.

## 10. Test summary

Six suites (`tests/test_shipment_*.py`), 166 tests, ~94% coverage of the
shipment modules:

- `test_shipment_state_machine.py` — every valid/invalid transition, terminal &
  compensation states.
- `test_shipment_events.py` — registration, frozen/slots, UUID/Decimal/datetime
  serialization, envelope round-trip.
- `test_shipment_model.py` — defaults, constraints, soft-delete, versioning.
- `test_shipment_repository.py` — **no-commit contract**, queries, filters,
  active-assignment exclusivity, soft-delete/restore.
- `test_shipment_service.py` — UoW pattern, event emission, cross-tenant
  validation, every transition, legacy methods, tracking events.
- `test_shipment_routes.py` — RBAC, validation, route ordering, full lifecycle,
  tenant isolation.

Full regression: **676 passed, 13 skipped**.

## 11. Backward compatibility

- The legacy mobile flow is preserved: `ShipmentService.assign_driver_only`
  (driver self-accept) and the `/shipments/{id}/events` tracking route continue
  to work (now emitting events). `ShipmentRepository.get_by_id`/`get_by_reference`/
  `list` legacy signatures are retained.
- `ShipmentStatus` only **added** `picked_up` and `delayed`; existing values are
  unchanged. `status` is stored as the enum *name* (legacy behaviour, untouched);
  `priority` is stored as the lowercase value, matching the Order column.

## 12. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| `equipment_id` has no aggregate yet, so tenant ownership cannot be validated. | LOW | Stored as an opaque optional UUID; validate once an Equipment domain (docs/08) ships. |
| Pre-existing latent mismatch: legacy migration 0001 had no status CHECK (Enum `create_constraint=False`), so no DB-level guard on `status` values. | LOW | Enforced at the model/service layer; could add a PG CHECK in a later migration. |
| Warehouse capacity is computed per-request (no reservation ledger). | MEDIUM | Acceptable for current scale; revisit with a projection (ADR-006) if contention appears. |
| Assignment exclusivity is enforced in the service, not by a DB unique partial index on driver/vehicle. | MEDIUM | Partial indexes added in 0008 support the query; a future hard constraint could close the race window. |
