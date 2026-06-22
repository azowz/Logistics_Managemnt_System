# ADR-008 — Heavy-Equipment Logistics Domain & Bounded Contexts

- **Status:** Accepted — **2026-06-20** (Phase 5 heavy-equipment domain design; extends the
  approved 14-context model with the equipment-specialized contexts)
- **Date:** 2026-06-20
- **Deciders:** Program lead
- **Builds on:** ADR-001 (tenancy/RLS), ADR-004 (CQRS-lite events), ADR-006 (projections),
  ADR-007 (UUIDv7 + event store + outbox). Companion: ADR-009 (Equipment↔Fleet boundary).

## Context
Mesaar today models generic parcel/freight: a `Shipment` carries cargo described only by
`weight_kg` + `volume_m3` (+ planned `cargo_type`). The target customers — **Aramco, SABIC,
NEOM, EPC contractors, construction, mining, industrial operators** — move **heavy equipment**
(excavators, cranes, generators, …) whose movement is governed by **physical dimensions, axle
weights, oversize/overweight permits, escorts, route restrictions, operator certifications, and
high-value insurance/claims.** None of this is modeled. The Phase 4.5 audit
(`docs/06`) flagged this as the platform's largest **P0 product gap** and named a future
Equipment/Asset context. This ADR ratifies the heavy-equipment domain and the contexts that own it.

## Decision
Extend the domain with **three new bounded contexts**, all consistent with the locked
architecture (tenant-scoped, event-driven via the outbox, Clean/DDD layering, additive to `app/`):

1. **Equipment & Asset (#15)** — the physical heavy asset: catalog, categories, specifications,
   dimensions, weight, transport requirements, condition, and the **Equipment lifecycle** (ADR-009).
2. **Compliance & Permits (#16)** — oversize/overweight classification, **permit management**
   (government + municipal), **axle-weight** profiles, **route restrictions** (height/weight/bridge/
   tunnel/hazard), **escort/pilot-car** planning, and the **compliance rule engine** (Hard rules
   that gate movement).
3. **Insurance & Claims (#17)** — insurance policies, coverage rules, claims workflow, damage
   reporting, liability tracking. *Refines* the audit's grouping (these were incubated inside
   Contract Management #14); promoted to a standalone context given enterprise claim value/volume.
   **Contract Management (#14) retains** contracts, pricing rules, SLA, penalties, carrier &
   **rental** agreements; it *references* policies/claims by id.

**Modeling stance.** Equipment is **first-class and dimensional**: a `Shipment`/`Order` moving
equipment is *enriched* (it references an `Equipment` unit and inherits oversize/permit/escort
requirements) but the **approved 8-state `Shipment` machine is NOT changed** — equipment movement
runs *through* a shipment, it does not replace it. Operator certifications gate driver/operator
eligibility (extending the existing assignment guards, not rewriting them).

## Consequences
- (+) Credible heavy-equipment platform for the named enterprise segment; basis for permit/escort/
  compliance differentiation that generic TMS (and Uber Freight) lack.
- (+) Compliance becomes **enforceable**: movement is gated on approved permits, validated routes,
  and current operator certs — a Hard-rule safety/regulatory backbone.
- (+) Reuses the event store/outbox, projections, AI substrate, tenancy, and audit unchanged.
- (−) Three new contexts → more aggregates, services, routers, integrations (permit authorities,
  insurers, route-restriction data). Sequenced in Phase 5 M4–M5.
- (−) Equipment vs Vehicle boundary needs discipline (ADR-009) to avoid double-modeling trucks/
  trailers.
- (−) Jurisdiction-specific permit/route data (KSA: MoT & Roads General Authority, municipalities)
  must be configurable, not hard-coded.

## Alternatives considered
| Option | Verdict |
|---|---|
| **Three specialized contexts (chosen)** | Clean ownership; compliance/insurance are deep enough to be Core |
| Bolt equipment fields onto `Shipment` | Rejected: explodes the Shipment aggregate; no compliance/permit lifecycle |
| Single mega "HeavyEquipment" context | Rejected: conflates asset, regulatory, and insurance concerns |
| Keep insurance/claims inside Contract Mgmt #14 | Viable, but enterprise claim volume/SLA justifies a standalone context #17 |
| Buy a 3rd-party permit/compliance module only | Rejected as core: integrate via ACL, but own the rules/state |

## Migration Plan (additive, Phase 5 M4–M5; no redesign)
1. Add tenant-scoped reference tables (equipment catalog/specs) — UUIDv4 acceptable (low-churn).
2. Add `Equipment` unit aggregate + lifecycle (ADR-009); enrich `Shipment` with nullable
   `equipment_id`, oversize/escort/permit-class flags (additive columns, `/v1` stays additive — ADR-005).
3. Add Compliance (#16) + Insurance & Claims (#17) aggregates; wire events through the outbox (ADR-007).
4. Backfill is N/A (new domain); all tables born with `tenant_id` + RLS (ADR-001).
5. Compliance Hard-rules enter the assignment/dispatch path as guards (extend, don't replace).

## Rollback Plan
New contexts are **additive and isolated**: feature-flag the equipment/compliance/insurance routers
off; the generic shipment flow is unaffected (equipment fields are nullable). No destructive change
to existing tables, so rollback = disable routers + stop consumers; reference/event tables can be
left in place (RLS-scoped, inert) or dropped in a later additive migration.

## Follow-ups
- ADR-009 (Equipment↔Fleet boundary & lifecycle) — companion, same date.
- Compliance rule catalog + jurisdiction config; permit-authority & insurer ACLs (`app/integrations`).
- AI substrate reuse: demand/availability forecasting, permit-delay & route-risk prediction (`docs/08` Part 8).

*Companion artifacts:* `docs/08-heavy-equipment-domain-design.md` · ADR-009 · ADR-007 · `docs/06` Phase E/F.
