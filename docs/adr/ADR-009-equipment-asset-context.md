# ADR-009 — Equipment↔Fleet Boundary & Equipment Lifecycle Ownership

- **Status:** Accepted — **2026-06-20** (Phase 5; companion to ADR-008)
- **Date:** 2026-06-20
- **Deciders:** Program lead
- **Builds on:** ADR-008 (heavy-equipment domain), ADR-004/007 (events/outbox), ADR-001 (tenancy).

## Context
Heavy-equipment logistics involves two physically similar but semantically distinct asset kinds:
the **machine being moved/rented** (excavator, crane, generator) and the **transport asset doing
the moving** (heavy-haul truck, lowboy/flatbed trailer). Worse, **trucks and trailers appear in
both roles** — a trailer can be the *carrier* of an excavator, or itself the *subject* of a
relocation/rental order. The existing `Vehicle` (Fleet) aggregate already models transport assets.
Without an explicit boundary we risk double-modeling, ambiguous ownership of the lifecycle, and
broken assignment guards.

## Decision
1. **Two distinct aggregates, one owning context each.**
   - **`Vehicle`** (Fleet Management, EXISTS) = the **transport asset performing the haul** (prime
     mover + trailer used to carry equipment). Unchanged. Its `active/maintenance/decommissioned`
     machine stays as approved.
   - **`Equipment`** (Equipment & Asset context #15, NEW) = the **heavy asset that is the subject of
     an order** (moved, delivered, and — for rentals — returned). Owns the **Equipment lifecycle**
     state machine (`docs/08` Part 6).
2. **Role, not type, decides ownership.** A given physical trailer is a `Vehicle` when it *carries*
   and an `Equipment` unit when it is the *subject* of the order. The two are linked **by id**, never
   merged. (Most fleets keep distinct inventory anyway.)
3. **Equipment lifecycle is owned by context #15**, separate from and complementary to the
   `Shipment` machine: a `Shipment` *moves* an `Equipment` unit; `Equipment.InTransit` is entered
   when its carrying shipment reaches `in_transit`. The approved **Shipment 8-state machine is not
   modified** (ADR-008).
4. **Rental agreements are owned by Contract Management (#14)**, not Equipment. Equipment exposes
   availability/condition; the `RentalContract` governs hire terms; the `Shipment`/`Order` governs
   movement. Three aggregates, three owners, linked by id + domain events (ADR-004/007).
5. **Operator certifications (context #15/Driver)** gate assignment: an operator/driver lacking a
   current required certification fails eligibility — an **extension of** the existing exclusivity/
   capacity guards, enforced in the owning service, not a rewrite.

## Consequences
- (+) No double-modeling; clear answer to "is this row a vehicle or equipment?" (its role in the order).
- (+) Equipment gets a rich logistics lifecycle (Reserved→…→Returned) without polluting Fleet or Shipment.
- (+) Rental, movement, and asset condition evolve independently (separate aggregates).
- (−) Cross-aggregate orchestration (reserve equipment → create shipment → bind rental) is a saga in
  the owning services; must be idempotent and outbox-driven (ADR-007).
- (−) Reporting must join Vehicle + Equipment for "all assets"; acceptable (projections, ADR-006).

## Alternatives considered
| Option | Verdict |
|---|---|
| **Distinct Equipment aggregate, role-based ownership (chosen)** | Cleanest DDD boundary; reuses Fleet/Shipment unchanged |
| Extend `Vehicle` to cover all assets | Rejected: conflates carrier vs subject; bloats Fleet; breaks Shipment-move semantics |
| Single polymorphic `Asset` table | Rejected: type-switch logic, weak invariants, RLS/index complexity |
| Equipment owns its own rental terms | Rejected: duplicates Contract Mgmt #14; splits commercial truth |

## Migration Plan (additive)
1. Create `Equipment` (+ catalog/spec references) in context #15, tenant-scoped, born under RLS.
2. Add nullable `equipment_id` (and equipment-derived flags) to `Shipment` (additive, ADR-005).
3. Introduce the Equipment lifecycle consumers that react to shipment events
   (`ShipmentPickedUp`→`EquipmentInTransit`, `ShipmentDelivered`→`EquipmentDelivered`).
4. Bind `RentalContract` (#14) ↔ `Equipment` ↔ `Shipment` by id via saga; no schema change to Fleet.

## Rollback Plan
Equipment is additive and nullable on `Shipment`; disable context #15 routers/consumers and the
generic flow continues. No change to `Vehicle`/`Shipment` schemas is required to roll back.

## Follow-ups
- Equipment lifecycle state machine + event catalog (`docs/08` Parts 6–7).
- Saga: reserve → assign → move → deliver → return → re-available/inspect (idempotent, outbox).
- Projection `proj_equipment_availability` (ADR-006) for demand/availability forecasting (Part 8).

*Companion artifacts:* `docs/08-heavy-equipment-domain-design.md` · ADR-008 · ADR-007 · `docs/05` §4 (aggregate ownership).
