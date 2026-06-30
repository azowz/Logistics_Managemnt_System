# 22 — Insurance & Claims Domain (Sprint 8)

> Status: **IMPLEMENTED & VERIFIED**. Implements bounded context **#17 — Insurance
> & Claims** (ADR-008, `docs/08` Part 5). Provides financial/operational risk
> protection: policies, coverage rules, the claim workflow, damage reports, and
> liability records.

---

## 1. Domain purpose

Owns insurance **policies** and **coverage rules**, the **claim** lifecycle,
**damage reports**, and **liability records** for high-value movements. Claims
reference Shipment / Order / Customer / Equipment / Compliance by id; those
contexts do not own the claim lifecycle. Billing consumes approved outcomes
later but does not own the workflow.

## 2. Aggregate ownership

| Concern | Owner |
| --- | --- |
| Policies | `InsurancePolicy` + `PolicyStateMachine` (`app/services/insurance_policies.py`) |
| Coverage rules | `CoverageRule` |
| Claim workflow | `Claim` + `ClaimStateMachine` |
| Damage reports | `DamageReport` |
| Liability | `LiabilityRecord` |
| Services | `InsuranceService` (policies/rules), `ClaimsService` (claims/damage/liability) |
| Repositories | `app/repositories/insurance_repository.py` (5) |
| Events | `app/events/insurance_events.py` (20) |
| API | `app/api/routes/insurance.py`, `app/api/routes/claims.py` |
| Schemas | `app/schemas/insurance.py` |

## 3. Policy lifecycle

```
draft → active → {suspended, expired, cancelled}
suspended → {active, expired, cancelled}
```
Terminal: `expired`, `cancelled`. Only an **active** policy can back a claim
approval (`PolicyStateMachine.can_cover`).

## 4. Claim lifecycle

```
created → under_review → {approved, rejected}
approved → settled → closed
rejected → closed
closed → under_review   (explicit reopen)
```
Terminal: `closed` (reopenable). Rules enforced by `ClaimsService`:
- **approved** requires an active linked policy that *covers the claim type*,
  and an `approved_amount`; `approved_amount > claimed_amount` needs an
  authorized (ADMIN) override.
- **rejected** requires a `rejection_reason`.
- **settled** requires `settlement_notes` and a prior `approved_amount`.
- liability percentages are 0–100 and sum to ≤100 per claim unless overridden.
Illegal transitions raise `StatusTransitionError` (409).

## 5. Damage reports & liability records

`DamageReport` (cargo/equipment/vehicle/property/missing/delay) and
`LiabilityRecord` (customer/carrier/driver/company/third_party/unknown) are
children of a claim, created via `POST /claims/{id}/damage-reports` and
`POST /claims/{id}/liability-records`. Liability distribution is validated
against the running total for the claim.

## 6. Shipment integration

Claims may reference a failed/returned shipment (`shipment_id`, validated
tenant-owned). Shipment already emits `ShipmentFailed`/`ShipmentReturned`;
claim creation is **not** automatic and does not mutate the shipment. Shipment
does not own the claim lifecycle.

## 7. Equipment integration

Claims may reference `equipment_id` (validated tenant-owned, not soft-deleted);
`equipment_damage` claims **require** an `equipment_id`, and damage reports may
reference equipment. Equipment does not own the claim lifecycle.

## 8. Compliance evidence integration

Claims may reference a `compliance_check_id` and/or `permit_id` (validated
tenant-owned) as supporting evidence; `compliance_violation` claims typically
reference a failed compliance check. Compliance does not own the claim lifecycle.

## 9. Events (20)

Policy: `InsurancePolicyCreated/Activated/Suspended/Expired/Cancelled`.
Coverage: `CoverageRuleCreated/Updated`. Claim:
`ClaimCreated/SubmittedForReview/Approved/Rejected/Settled/Closed/Reopened/
Deleted/Restored`. Children: `DamageReportCreated`, `LiabilityRecordCreated`.
Linkage: `ClaimLinkedToShipment`, `ClaimLinkedToEquipment`. All frozen/slots,
`@register_event`, JSONB-safe, tenant-aware, versioned.

## 10. API contract

Policies: `POST/GET /insurance/policies`, `GET /insurance/policies/search`,
`GET/PATCH /insurance/policies/{id}`, lifecycle `activate/suspend/expire/cancel`.
Coverage rules: `POST/GET /insurance/coverage-rules`, `PATCH .../{id}`. Claims:
`POST/GET /claims`, `GET /claims/search`, `GET/PATCH/DELETE /claims/{id}`,
`POST /claims/{id}/{restore,review,approve,reject,settle,close,reopen}`. Damage:
`POST/GET /claims/{id}/damage-reports`. Liability:
`POST/GET /claims/{id}/liability-records`. Literal paths precede `{id}`; routes
are thin with RBAC (write = ADMIN/MANAGER; over-claim/liability override = ADMIN;
read adds CLIENT/DRIVER; delete/restore = ADMIN).

## 11. Security model & tenant isolation

`tenant_id` from context only; RLS on all five tables; cross-tenant
policy/shipment/order/customer/equipment/compliance references rejected; per-tenant
unique policy & claim numbers; over-claim and liability-override gated to ADMIN;
actor attribution captured.

## 12. Migration summary

`0011_insurance_claims_domain` (down_revision `0010`, single head) — additive:
creates `insurance_policies`, `coverage_rules`, `claims`, `damage_reports`,
`liability_records` with named PK/FK/unique/check constraints, soft-delete +
audit + `version`, JSONB (`terms`, `exclusions`, `evidence`, `photos`), indexes,
and RLS policies. PG-specific operations guarded by `_is_postgres()`; reversible
(5/5 tables). No existing table is modified.

## 13. Test summary

Nine suites (`test_insurance_{model,events,repository,service,routes}.py`,
`test_claim_state_machine.py`, `test_claims_{shipment,equipment,compliance}_integration.py`),
**~93% coverage** of the insurance/claims modules (events/model 100%, policies
97%, repository 95%, insurance_service 95%, claims_service 94%, schemas 92%).
Full regression: **1051 passed, 13 skipped**.

## 13a. Billing & Settlements consumption (Sprint 9)

The Billing & Settlements domain (context #18, `docs/23-billing-settlements-domain.md`)
**consumes approved claim outcomes** to create settlement records: a settlement
may reference a `claim_id`, and a claim-backed settlement requires the claim to
be **approved or settled** with an amount **bounded by the claim's approved
amount** (ADMIN override aside). Billing uses a **read-only** `ClaimRepository`
for validation — it never mutates the claim, and **Claims does not own the
settlement lifecycle**. The claim continues to emit `ClaimSettled`; Billing emits
`ClaimSettlementConsumed` when it draws against the claim.

## 13b. Notifications linkage (Sprint 10)

Claim events are **notification triggers** consumed by the Notifications &
Communications domain (context #19, `docs/24-notifications-communications-domain.md`):
`ClaimCreated`, `ClaimApproved`, `ClaimRejected`, and `ClaimSettled` each produce
an in-app notification. The dependency is one-way (events out); **Claims does not
own the notification lifecycle**.

## 13c. Reporting & Analytics linkage (Sprint 11)

Claim events feed **`proj_claims_metrics`** (context #20, `docs/25-...`).
One-way (events out); Claims owns no projection.

## 14. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| No automatic claim creation on `ShipmentFailed`/`ShipmentReturned` (manual today). | LOW | Events exist; an FNOL consumer (docs/08 Part 5.2) is a follow-up. |
| ~~Billing settlement consumption not wired.~~ **RESOLVED in Sprint 9** — `SettlementService` consumes approved claim outcomes (`docs/23`). | ~~MEDIUM~~ | Settlements reference claims by id, bounded by approved amount; automatic invoice-adjustment on `ClaimSettled` remains a follow-up. |
| Coverage-rule matching (cargo type / category / limits) is modelled but not yet enforced at approval (only policy active + covers-type flag). | MEDIUM | Coverage rules are stored and queryable; richer rule evaluation is a follow-up. |
| Policy expiry is not auto-swept. | LOW | `expire_policy` exists; a scheduled sweep (ADR-003) is a follow-up. |
