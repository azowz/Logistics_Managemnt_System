# 21 — Compliance & Permits Domain (Sprint 7)

> Status: **IMPLEMENTED & VERIFIED**. Implements bounded context **#16 — Compliance
> & Permits** per ADR-008 and `docs/08` Parts 2–4. Converts heavy-equipment
> constraints into enforceable, dispatch-blocking logistics rules.

---

## 1. Domain purpose

Owns the regulatory envelope for heavy/oversize movements: the **permit
lifecycle**, **escorts**, **route restrictions**, **axle-weight profiles**,
**compliance checks**, and **operator certifications** — plus a **dispatch gate**
that decides whether a shipment may proceed. Compliance owns rule evaluation and
the permit lifecycle; Equipment provides the transport profile; Shipment asks the
gate whether dispatch is allowed. These concerns are not merged.

## 2. Aggregate ownership

| Concern | Owner |
| --- | --- |
| Permit lifecycle | `Permit` + `PermitStateMachine` (`app/services/compliance_policies.py`) |
| Escorts | `Escort` |
| Route restrictions | `RouteRestriction` |
| Axle-weight profiles | `AxleWeightProfile` |
| Compliance checks | `ComplianceCheck` |
| Operator certifications | `OperatorCertification` |
| Application service / UoW | `ComplianceService` (`app/services/compliance_service.py`) |
| Dispatch gate (read-only port) | `ComplianceValidationService` |
| Repositories | `app/repositories/compliance_repository.py` (6) |
| Events | `app/events/compliance_events.py` (24) |
| API | `app/api/routes/compliance.py` |
| Schemas | `app/schemas/compliance.py` |

## 3. Permit state machine

```
draft → submitted → under_review → approved → active → expired
  │         │            │            │          │
  └─────────┴────────────┴────────────┴──────────┴──→ cancelled
                         └──→ rejected
```

Terminal: `rejected`, `expired`, `cancelled`. Only `active` permits authorize
dispatch (`is_dispatchable`). Illegal transitions raise `StatusTransitionError`
(HTTP 409); same-state is an idempotent no-op.

## 4. Compliance check model

A `ComplianceCheck` records one evaluation for a movement: `check_type`
(permit_required / permit_validity / escort_required / axle_weight / oversize /
route_restriction / operator_certification / insurance_required /
hazardous_material), `status` (pending / passed / failed / warning / overridden),
`blocking`, and `failure_reasons` (JSONB). `evaluate_compliance(shipment_id)`
derives checks from the equipment transport profile, persists them, and emits
`ComplianceCheckCreated` + `Passed`/`Failed`.

## 5. Dispatch gate

`ComplianceValidationService.validate_dispatch(shipment, stage)` is **read-only**
(no events, no commit) and returns a `DispatchGateResult` (`allowed`,
`blocking_reasons`, `warnings`, `required_permits`, `required_escorts`,
`compliance_check_ids`). It **fails closed** for permit-required / hazardous /
oversize equipment lacking an active, in-window permit, or a required escort, and
honours any persisted failed-blocking checks (oversize / route / axle). Shipments
with no equipment, or equipment with no compliance conditions, pass through.

## 6. Equipment integration

Equipment supplies the inputs — `requires_permit`, `requires_escort`,
`hazardous`, `insurance_required`, and dimensions/weight (which drive oversize
classification at `width>2.6m`, `height>4.5m`, `length>16m`, `weight>45000kg`).
Equipment does **not** own the permit lifecycle; it is a referenced input only.

## 7. Shipment integration

`ShipmentService` calls the gate before **assign**, **pickup**, and **transit**
(`_enforce_dispatch_gate`). On a block it persists `DispatchBlockedByCompliance`
and raises `ConflictError` (HTTP 409); on clearance it persists
`DispatchClearedByCompliance`. Normal (no-equipment) shipments are unaffected.
Compliance rules live entirely in the Compliance context — `ShipmentService`
depends only on the thin `ComplianceValidationService` port (no circular
dependency; the gate reads compliance + equipment repositories).

## 8. Events (24)

Permit: `PermitCreated/Submitted/UnderReview/Approved/Rejected/Activated/Expired/
Cancelled/Deleted/Restored`. Escort: `EscortCreated/Scheduled/Cancelled`. Route:
`RouteRestrictionCreated/Updated`. Axle: `AxleWeightProfileCreated`. Checks:
`ComplianceCheckCreated/Passed/Failed`, `ComplianceOverrideApplied`. Certs:
`OperatorCertificationCreated/Expired`. Dispatch: `DispatchBlockedByCompliance`,
`DispatchClearedByCompliance`. All frozen/slots, `@register_event`, JSONB-safe,
tenant-aware, versioned.

## 9. API contract

Permits: `POST/GET /compliance/permits`, `GET /compliance/permits/search`,
`GET/PATCH/DELETE /compliance/permits/{id}`, and lifecycle actions
`submit/review/approve/reject/activate/expire/cancel/restore`. Checks:
`POST /compliance/checks/evaluate`, `GET /compliance/checks`,
`GET /compliance/checks/{id}`, `POST /compliance/checks/{id}/override`. Escorts:
`POST/GET /compliance/escorts`, `.../{id}/schedule|cancel`. Route restrictions:
`POST/GET /compliance/route-restrictions`, `PATCH .../{id}`. Axle:
`POST /compliance/axle-weight-profiles`. Operator certifications:
`POST/GET /compliance/operator-certifications`, `.../{id}/expire`. Literal paths
(`/permits/search`, `/checks`, `/escorts`, `/route-restrictions`,
`/operator-certifications`) precede dynamic `{id}` paths. Routes are thin with
RBAC; override requires ADMIN/MANAGER.

## 10. Security & tenant isolation

`tenant_id` from context only; RLS on all six tables; cross-tenant
shipment/equipment/vehicle/user references rejected (`_require_tenant_owned`);
per-tenant unique permit numbers; RBAC on every endpoint; actor attribution
captured. Override is restricted to authorized roles (ADMIN/MANAGER).

## 11. Migration summary

`0010_compliance_permits_domain` (down_revision `0009_equipment_domain`, single
head) — additive: creates `permits`, `escorts`, `route_restrictions`,
`axle_weight_profiles`, `compliance_checks`, `operator_certifications` with named
PK/FK/unique/check constraints, soft-delete + audit + `version`, JSONB
(`conditions`, `axle_weights`, `failure_reasons`), indexes, and RLS policies.
PostgreSQL-specific operations guarded by `_is_postgres()`; reversible (6/6
tables). No existing table is modified.

## 12. Test summary

Eight suites (`test_compliance_{model,events,repository,service,routes}.py`,
`test_permit_state_machine.py`, `test_dispatch_gate.py`,
`test_shipment_compliance_integration.py`), **~94% coverage** of the compliance
modules (events/model/policies 100%, schemas 95%, repository 94%, service 93%).
Full regression: **934 passed, 13 skipped**. Covered: permit lifecycle + invalid
transitions, dispatch gate (no-equipment / permit-required / expired permit /
escort-required / failed-blocking-check / hazardous), shipment dispatch blocking
& clearing, evaluate + override, cross-tenant validation, RBAC, route ordering,
UUID/Decimal/datetime serialization.

## 12a. Insurance & Claims linkage (Sprint 8)

A failed compliance check or a permit **may be used as supporting evidence on an
insurance claim** in the Insurance & Claims domain (context #17,
`docs/22-insurance-claims-domain.md`). A `Claim` references them by
`compliance_check_id` and/or `permit_id` only (validated tenant-owned); a
`compliance_violation` claim typically references a failed compliance check.
Claim creation does **not** mutate the compliance check or permit, and the
**Compliance & Permits context does not own the claim lifecycle** — claim
state, approvals, and liability all live in `ClaimsService`. Compliance is
referenced by id, never the reverse.

## 12b. Notifications linkage (Sprint 10)

Compliance events are **notification triggers** consumed by the Notifications &
Communications domain (context #19, `docs/24-notifications-communications-domain.md`):
`DispatchBlockedByCompliance`, `DispatchClearedByCompliance`, `PermitApproved`,
`PermitRejected`, and `PermitExpired` each produce an in-app notification. The
dependency is one-way (events out); **Compliance does not own the notification
lifecycle**.

## 13. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Route-restriction matching is attribute/region-based (no PostGIS geofencing yet). | MEDIUM | Persisted-check model supports it; PostGIS adoption is the docs/08 Part 4 follow-up. |
| Check override clears persisted blocking checks but not live permit/escort gate requirements. | LOW | Intentional — a missing permit is obtained/cancelled, not overridden; documented. |
| Permit/cert expiry is not yet swept automatically (no celery-beat job). | MEDIUM | `expire_permit`/`expire_operator_certification` exist; a scheduled sweep (ADR-003) is a follow-up. |
| Operator-certification eligibility is modelled but not yet wired into driver-assignment guards. | LOW | Data + repository (`get_valid_operator_certification`) ready; assignment-time enforcement is a follow-up. |
