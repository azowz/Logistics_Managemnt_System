# 20 — Equipment & Asset Domain (Sprint 6)

> Status: **IMPLEMENTED & VERIFIED**. Implements bounded context **#15 — Equipment
> & Asset** per **ADR-008** / **ADR-009** and `docs/08-heavy-equipment-domain-design.md`
> Part 1 & Part 6. Closes the Sprint 5 gap where `Shipment.equipment_id` was an
> opaque, un-validated UUID.

---

## 1. Domain purpose

The Equipment & Asset context owns the **physical heavy asset** that is the
*subject* of a logistics movement (excavator, crane, generator, …): its catalog
taxonomy, specifications, dimensions, transport-requirement flags, availability,
and lifecycle. It is the source of truth for *what the asset is* and *what moving
it requires*.

## 2. Aggregate ownership

| Concern | Owner |
| --- | --- |
| Aggregate root | `app/models/equipment.py::Equipment` |
| Reference entities | `EquipmentCategory`, `EquipmentModel` (tenant-scoped catalog) |
| State machine | `app/services/equipment_policies.py::EquipmentStateMachine` |
| Persistence boundary | `app/repositories/equipment_repository.py` |
| Application service / UoW | `app/services/equipment_service.py::EquipmentService` |
| Domain events | `app/events/equipment_events.py` (17 events) |
| API | `app/api/routes/equipment.py` |
| Schemas | `app/schemas/equipment.py` |

## 3. Equipment vs Fleet boundary (ADR-009)

`Equipment` (#15) is the **subject** moved; `Vehicle` (Fleet) is the **transport
asset performing the haul**. They are **never merged** — linked by id only. This
sprint does not touch `Vehicle`, and equipment lifecycle logic is **not** placed
inside `Shipment`: a `Shipment` *moves* an `Equipment` unit; the Equipment
lifecycle is a complementary machine. The simplified Sprint 6 status set maps onto
the docs/08 Part 6 design (`decommissioned` ≈ OutOfService terminal,
`under_maintenance` ≈ Maintenance).

## 4. State machine

Statuses: `active`, `inactive`, `under_maintenance`, `reserved`, `in_transit`,
`decommissioned` (terminal). Availability: `available`, `reserved`, `unavailable`,
`assigned`, `maintenance`. Ownership: `owned`, `leased`, `customer_owned`,
`third_party`.

| From | Allowed targets |
| --- | --- |
| `active` | `under_maintenance`, `reserved`, `in_transit`, `inactive`, `decommissioned` |
| `under_maintenance` | `active` |
| `reserved` | `active`, `in_transit` |
| `in_transit` | `active` |
| `inactive` | `active`, `decommissioned` |
| `decommissioned` | *(terminal)* |

`is_assignable(status)` is False for `inactive` / `under_maintenance` /
`decommissioned`. Illegal transitions raise `StatusTransitionError` (HTTP 409).

## 5. Business rules

- Equipment code and asset tag are **unique per tenant**; serial number is
  **optionally unique per tenant** (PostgreSQL partial unique index on non-null,
  non-deleted rows).
- Category (and model, if provided) and current warehouse (if provided) must
  belong to the current tenant.
- Soft-delete only; restore supported; optimistic locking (`version`).
- A unit cannot be reserved unless its availability is `available`.
- A unit cannot be assigned to a movement while `inactive` / `under_maintenance`
  / `decommissioned`.
- Status & availability transitions are validated by the state machine.

## 6. Events

20 events (`@dataclass(frozen=True, slots=True)`, `@register_event`, JSONB-safe,
tenant-aware, `event_version = 1`): `EquipmentCreated`, `EquipmentUpdated`,
`EquipmentActivated`, `EquipmentDeactivated`, `EquipmentReserved`,
`EquipmentReleased`, `EquipmentAssignedToShipment`, `EquipmentInTransit`,
`EquipmentDelivered`, `EquipmentMaintenanceStarted`,
`EquipmentMaintenanceCompleted`, `EquipmentDecommissioned`, `EquipmentDeleted`,
`EquipmentRestored`, `EquipmentStatusChanged`, `EquipmentAvailabilityChanged`,
`EquipmentLocationChanged`, `EquipmentSpecificationChanged`,
`EquipmentCategoryCreated`, `EquipmentModelCreated`. Every status transition
emits its specific event(s), a general `EquipmentStatusChanged`, and an
`EquipmentAvailabilityChanged` when availability changes; updates emit
location/specification/general events partitioned by changed-field group.

## 6a. Categories & models

`EquipmentCategory` (with an `is_active` flag) and `EquipmentModel` are
tenant-scoped reference entities. The service exposes `create_category` /
`update_category` / `list_categories` and `create_model` / `update_model` /
`list_models` (codes are unique per tenant; a model's category is validated
tenant-owned), emitting `EquipmentCategoryCreated` / `EquipmentModelCreated`.
The API surfaces `POST`/`GET /equipment/categories` and
`POST`/`GET /equipment/models`, declared **before** `/equipment/{id}` so the
literal paths win over the UUID converter.

## 7. Repository & service pattern

Repository: constructor takes `Session`; **never commits/rolls back**; returns
aggregates; no FastAPI; RLS-scoped reads; `get_by_id_or_raise`, `get_by_code`,
`get_by_asset_tag`, `get_by_serial_number`, `list_equipment` → `(items, total)`
with filter/sort/paginate. Service owns the UoW and follows
`validate → load → validate rules → mutate → flush → event → append → commit`.

## 8. API contract

`POST /equipment` · `GET /equipment` · `GET /equipment/search` (declared before
`/{id}`) · `GET /equipment/{id}` · `PATCH /equipment/{id}` · `DELETE
/equipment/{id}` · `POST /equipment/{id}/restore` · `.../activate` ·
`.../deactivate` · `.../reserve` · `.../release` · `.../maintenance/start` ·
`.../maintenance/complete` · `.../decommission`. Thin handlers, RBAC via
`require_roles` (write = ADMIN/MANAGER; maintenance adds DRIVER; read adds
CLIENT/DRIVER; delete/restore = ADMIN), response schemas, no business logic.

## 9. Shipment integration

`ShipmentService` now validates `equipment_id` (create & update) via a read-only
`EquipmentRepository` (no circular dependency — services depend on repositories,
repositories on models). When provided, the equipment must:

1. exist and belong to the current tenant;
2. not be `decommissioned`;
3. be in an assignable status (not inactive/maintenance/decommissioned);
4. not already be bound to another **non-terminal** shipment (exclusivity);
5. be dimensionally compatible — the shipment's declared weight/volume must cover
   the equipment unit when both are known.

### 9a. Equipment FK migration strategy

`shipments.equipment_id` already existed as an opaque nullable UUID (added in
migration 0008, before any equipment rows could exist). Migration 0009 upgrades
it to a real FK **safely and staged** on PostgreSQL:

```sql
ALTER TABLE shipments ADD CONSTRAINT fk_shipments_equipment_id_equipment
  FOREIGN KEY (equipment_id) REFERENCES equipment (id) ON DELETE SET NULL NOT VALID;
ALTER TABLE shipments VALIDATE CONSTRAINT fk_shipments_equipment_id_equipment;
```

`NOT VALID` adds the constraint without scanning existing rows under an
`ACCESS EXCLUSIVE` lock; `VALIDATE CONSTRAINT` then checks existing data with a
weaker lock. All historical `equipment_id` values are NULL (equipment did not
exist pre-Sprint-6), so validation is effectively a no-op — but the staged form
keeps the migration safe even with data present. The column stays nullable
(shipments without equipment remain valid). On SQLite (tests) the FK is created
from the ORM model via `create_all`; the `ALTER`-based path is PostgreSQL-only
(`_is_postgres()` guard), so no unsupported SQLite `ALTER` is issued.

The `assign_to_shipment` service operation emits `EquipmentAssignedToShipment` +
`EquipmentAvailabilityChanged` and sets availability to `assigned` for the future
reserve→assign→move→deliver saga (ADR-009 follow-up).

## 9b. Compliance integration (Sprint 7)

The equipment **transport profile** — `requires_permit`, `requires_escort`,
`hazardous`, `insurance_required`, and dimensions/weight (oversize triggers) — is
consumed by the **Compliance & Permits domain** (#16, `docs/21`) to evaluate
compliance and gate shipment dispatch. Equipment **does not own** the permit,
escort, or compliance-check lifecycle; it is a referenced input. The permit
lifecycle lives entirely in context #16.

## 10. Security & tenant isolation

`tenant_id` is sourced from request context, never the client. All three tables
are born under RLS (migration 0009, PG-guarded). Cross-tenant category/model/
warehouse/shipment references are rejected (`_require_tenant_owned`). RBAC on
every endpoint; actor attribution captured (`created_by`/`updated_by`/`deleted_by`,
event `user_id`).

## 11. Database

Migration **`0009_equipment_domain`** (head `0008_shipment_domain`) creates
`equipment_categories`, `equipment_models`, `equipment` with FKs, per-tenant
unique constraints, value CHECKs, indexes (`status`, `availability_status`,
`category_id`, `model_id`, `current_warehouse_id`, `tenant_id`), a PG partial
unique index on serial number, RLS policies, and the shipment FK. Fully
reversible (3/3 tables, 10/10 indexes). All PG-specific ops guarded by
`_is_postgres()`.

## 12. Test summary

Seven suites, **~95% coverage** of the equipment modules (events 100%, model
100%, policies 100%, repository 92%, schemas 96%, service 91%):
`test_equipment_{model,events,repository,service,routes,state_machine}.py` and
`test_shipment_equipment_integration.py` — covering category/model CRUD, the
`EquipmentAvailabilityChanged` emission, and route ordering. Full regression:
**817 passed, 13 skipped**.

## 12a. Insurance & Claims linkage (Sprint 8)

Damaged equipment **may be linked to an insurance claim** in the Insurance &
Claims domain (context #17, `docs/22-insurance-claims-domain.md`). A `Claim`
references equipment by `equipment_id` only (validated tenant-owned and not
soft-deleted); an `equipment_damage` claim **requires** an `equipment_id`, and
damage reports may also reference equipment. Claim creation does **not** mutate
the equipment record, and the **Equipment context does not own the claim
lifecycle** — all claim state, approvals, and liability handling live in
`ClaimsService`. Equipment is referenced by id, never the reverse.

## 13. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| ~~No `EquipmentCategory`/`EquipmentModel` management API.~~ **RESOLVED** — `POST`/`GET /equipment/categories` and `/equipment/models` ship with this sprint. | — | Codes unique per tenant; tenant-owned validation enforced. |
| Equipment↔Shipment binding has no shipment-event consumer yet (manual `assign_to_shipment`/`mark_in_transit`). | MEDIUM | The reserve→assign→move→deliver saga reacting to `ShipmentPickedUp`/`ShipmentDelivered` is the ADR-009 follow-up. |
| Weight/volume compatibility is a simple "shipment ≥ equipment" guard, not a full transport/oversize profile. | MEDIUM | Compliance & Permits (#16) owns oversize/axle/permit rules (docs/08 Part 2) — a future sprint. |
| Equipment exclusivity enforced in-service (no hard DB constraint linking equipment↔active shipment). | LOW | Query-backed; a future partial unique index could harden it. |
