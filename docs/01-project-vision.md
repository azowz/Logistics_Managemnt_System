# Phase 1 — Project Vision (Mesaar Logistics Operations Platform)

> **Status:** Approved baseline (authored 2026-06-22, Phase 6.5 closure — fills the gap flagged in `docs/06` A.1 #1 and the Phase 6 ABSENT ledger). **Documentation only.**
> **Purpose:** The single consolidated product/vision anchor that every later phase (`docs/02`…`docs/09a`, ADR-001…009) builds on. Where this document and an earlier doc disagree on scope wording, this vision is the intent; the technical phases remain authoritative for *design*.

`Mesaar` (مسار, "route/path") is a multi-tenant SaaS platform for **heavy and specialized logistics operations** in Saudi Arabia and the wider GCC. It pairs an operations-grade core (shipment lifecycle, dispatch, tracking, control tower) with a **heavy-equipment specialization** (oversize/overweight permits, escorts, axle/route compliance, equipment rental, operator certification) that general freight platforms do not model.

---

## 1. Mission

**Move heavy, high-value, and time-critical cargo across the Kingdom with the planning rigor, regulatory compliance, and real-time visibility that megaprojects demand — on one auditable, multi-tenant platform.**

We exist to remove the operational friction (manual permit chasing, spreadsheet dispatch, blind ETAs, disputed deliveries, opaque settlement) that makes heavy logistics slow, risky, and expensive for industrial operators and their carriers.

## 2. Vision

**To be the system of record and the intelligence layer for heavy-equipment and project logistics in the GCC — the "control tower" megaprojects run their moves on.**

Three-horizon view:
- **H1 (now → next):** a production-grade, multi-tenant operations core — shipments, fleet/driver, warehouse capacity, append-only tracking, dispatch, and an Arabic-first driver app — that is verifiably correct and auditable.
- **H2:** the commercial + compliance layers — Orders, Contracts/SLAs/pricing, Billing/settlement, and the **heavy-equipment domain** (Equipment & Asset, Compliance & Permits, Insurance & Claims) — turning the core into an enterprise platform.
- **H3:** the intelligence layer — predictive ETA/SLA, AI dispatch and route optimization, permit-delay and equipment-availability forecasting, demand prediction — built on the immutable event log as a training stream, human-in-the-loop for safety-/regulatory-critical decisions.

## 3. Business Objectives

| # | Objective | What it means |
|---|---|---|
| O1 | **Operational reliability** | A correct, guarded shipment lifecycle with exclusivity/capacity invariants enforced in code; zero illegal state transitions; lossless audit. |
| O2 | **Regulatory compliance by construction** | No oversize/overweight movement dispatches without a valid permit, cleared route (height/axle/bridge), assigned escort, and certified operator — enforced as HARD dispatch gates. |
| O3 | **Real-time visibility & control tower** | Live location, predictive ETA, SLA-risk surfacing, and exception management for every active movement and asset. |
| O4 | **Commercial integrity** | Contract-based pricing/SLAs, automated settlement, driver/carrier payout, claims and penalties — money movement reconciled to delivered work. |
| O5 | **Asset & fleet utilization** | Maximize heavy-asset and vehicle utilization (reservation, backhaul, consolidation, predictive maintenance) — utilization is the primary cost lever. |
| O6 | **Multi-tenant trust & data isolation** | Strict per-tenant isolation (RLS), residency, immutability, and crypto-shred erasure — enterprise- and government-grade. |
| O7 | **Decision intelligence** | Predictive/optimization models that measurably beat manual planning, with reproducible, tenant-scoped, human-in-the-loop governance. |

## 4. Target Customers

**Primary (anchor):** industrial and megaproject operators and their logistics arms —
- **Energy & petrochemicals:** Aramco, SABIC and their EPC contractors.
- **Giga-projects & construction:** NEOM, Roshn, and large EPC / construction firms.
- **Mining & industrial:** Ma'aden-class operators and heavy-industry sites.

**Secondary:** specialized heavy-haul carriers, crane & equipment-rental companies, and 3PLs serving the above — who need permit/escort/compliance workflows and equipment-rental lifecycle, not just parcel/FTL tracking.

**User personas (RBAC roles today):** Admin (tenant/platform), Operations/Dispatch Manager, Driver/Operator (Arabic-RTL mobile app), Customer/Shipper (client portal), plus future Billing Officer, Compliance Officer, Warehouse Operator, Fleet Maintenance.

## 5. Competitive Positioning

| Versus | Their strength | Mesaar's differentiation |
|---|---|---|
| **Uber Freight / Convoy** | Carrier marketplace, spot matching, slick UX | **Heavy-equipment specialization** (permits, escorts, axle/route compliance, rental, operator certs) + KSA/Arabic-first + compliance-as-dispatch-gate, which they do not model. |
| **Flexport** | Global forwarding, customs, multimodal | Deep **domestic heavy/oversize project logistics** and equipment lifecycle rather than international forwarding. |
| **SAP TM / Oracle OTM** | Enterprise breadth, ERP integration | A **focused, event-sourced, AI-ready** platform that is faster to adopt, multi-tenant SaaS, and purpose-built for heavy/specialized moves and GCC regulation. |

**Positioning statement.** *For industrial operators and heavy-haul carriers in the GCC who must move oversize, high-value, and project cargo under strict regulatory and SLA constraints, Mesaar is a multi-tenant logistics operations platform that makes compliance, visibility, and settlement automatic — combining an operations-grade core with heavy-equipment, permit, and claims domains that general freight platforms lack.*

**Defensible moats:** (1) the heavy-equipment + compliance domain model and rule engine; (2) an immutable, multi-tenant event log that doubles as an AI training substrate; (3) KSA-regulatory and Arabic-RTL fluency; (4) compliance enforced as code-level dispatch gates, not advisory checklists.

## 6. Success Metrics

> Targets are directional baselines for the platform's first production cohorts; each tenant ratifies its own SLOs. Many metrics are computed from the projections/KPIs in ADR-006 once the event backbone (M2) ships.

| Category | Metric | Target (initial) |
|---|---|---|
| **Operations** | On-time delivery / SLA adherence | ≥ 95% of movements within the SLA window |
| | Illegal state transitions in production | **0** (guarded lifecycle; `StatusTransitionError`) |
| | Mean dispatch-to-pickup time | ↓ 30% vs the operator's manual baseline |
| **Compliance** | Movements dispatched without a valid permit/escort/cert | **0** (HARD gate) |
| | Permit approval lead time (predicted vs actual) | within ± 1 day; reduce expedite/idle by 20% |
| **Visibility** | Active movements with live ETA on the control tower | ≥ 99% |
| | Exception mean-time-to-acknowledge | < 15 min |
| **Commercial** | Settlement automation (delivered → invoiced) | ≥ 90% straight-through, no manual touch |
| | Billing/settlement disputes | ↓ 50% (POD + audit trail) |
| | Claims cycle time (FNOL → settled/closed) | ↓ 40% |
| **Asset** | Heavy-asset / vehicle utilization | ≥ 75% productive utilization |
| | Unplanned downtime (predictive maintenance) | ↓ 25% |
| **Platform** | Cross-tenant data-leak incidents | **0** (RLS + isolation test) |
| | API read p95 (control-tower projections) | < 300 ms (ADR-006 budget) |
| | Event-pipeline freshness (outbox lag) | < 1 s p95 |
| **Intelligence** | Predictive-ETA error (MAE) vs naive baseline | ↓ 40% |
| | AI-assisted dispatch acceptance rate | ≥ 70% of suggestions accepted |

---

## 7. Scope guardrails (what Mesaar is and is not — H1/H2)

- **Is:** multi-tenant SaaS; road heavy/oversize + general freight; equipment rental & mobilization; KSA-regulatory compliance; Arabic-RTL operations; event-sourced + auditable; AI-ready.
- **Is not (yet):** a public carrier spot marketplace (H3), full customs/cross-border forwarding (P2, Flexport territory), or multimodal ocean/air/rail (P2). These are tracked in the `docs/06` Phase F gap analysis with priorities, not promised here.

*Companion artifacts:* `docs/02-architecture.md` (architecture), `docs/04` (domain behavior), `docs/06` Phase F (enterprise gap analysis & positioning), `docs/08` (heavy-equipment domain), `docs/09-final-domain-model.md` (consolidated model), `docs/09a-reconciliation-and-closure.md` (closure).
