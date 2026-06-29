# Mesaar — Execution Roadmap

**Document:** `docs/17-execution-roadmap.md`
**Date:** 2026-06-27
**Based On:** `docs/07` (Phase 5 execution plan), `docs/12` (implementation plan), `docs/15` (code audit), `docs/16` (readiness report)
**Sprint length:** 2 weeks
**Total roadmap:** 12 sprints (24 weeks / ~6 months)
**Team model:** Two squads (Backend A: domain build-out; Backend B: infrastructure + hardening)

---

## Table of Contents

1. [Roadmap Overview](#1-roadmap-overview)
2. [Sprint 1 — Foundation Hardening](#2-sprint-1--foundation-hardening)
3. [Sprint 2 — Customer & Orders Core](#3-sprint-2--customer--orders-core)
4. [Sprint 3 — Shipment Saga & Order Fulfillment](#4-sprint-3--shipment-saga--order-fulfillment)
5. [Sprint 4 — Heavy Equipment Domain](#5-sprint-4--heavy-equipment-domain)
6. [Sprint 5 — Compliance, Permits & Route Compliance](#6-sprint-5--compliance-permits--route-compliance)
7. [Sprint 6 — Contract Management & Pricing](#7-sprint-6--contract-management--pricing)
8. [Sprint 7 — Billing, Insurance & Claims](#8-sprint-7--billing-insurance--claims)
9. [Sprint 8 — Projections & Control Tower](#9-sprint-8--projections--control-tower)
10. [Sprint 9 — Driver Self-Service & Route Management](#10-sprint-9--driver-self-service--route-management)
11. [Sprint 10 — Notifications & Analytics](#11-sprint-10--notifications--analytics)
12. [Sprint 11 — AI Operations](#12-sprint-11--ai-operations)
13. [Sprint 12 — Scale, Security & GA](#13-sprint-12--scale-security--ga)
14. [Critical Path & Dependencies](#14-critical-path--dependencies)
15. [Governance & Definition of Done](#15-governance--definition-of-done)

---

## 1. Roadmap Overview

### Sprint Timeline

```
Week:    1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
Sprint:  [──S1──][──S2──][──S3──][──S4──][──S5──][──S6──][──S7──][──S8──][──S9──][─S10─][─S11─][─S12─]
         Foundation   │  M3 Customer+Orders │  M4 Heavy-Eq+Permits  │  M5 Contract+Billing │  M6 Proj │  M7 │  M8 AI │  M9 GA
```

### Milestone-to-Sprint Mapping

| Milestone | Sprints | Theme |
|---|---|---|
| Foundation Hardening | S1 | Close M2→M3 gaps; CI; test uplift |
| M3 Customer + Orders | S2, S3 | Customer context; order lifecycle; saga |
| M4 Heavy Equipment | S4, S5 | Equipment catalog; compliance; permits; route compliance |
| M5 Contract + Billing | S6, S7 | Contracts; pricing rules; billing; insurance; claims |
| M6 Projections + Control Tower | S8 | proj_* tables; read models; lag SLO; control tower API |
| M7 Driver Self-Service + Route + Notifications | S9, S10 | OTP; accept/decline; route management; notifications fan-out |
| M8 AI Operations | S11 | pgvector; embeddings; ETA/SLA/pricing advisory; feedback loop |
| M9 Scale + Security + GA | S12 | Load test; pen-test; KMS; DR; EDI gateway; GA |

### Train Releases

| Train | Sprints | Internal GA Candidate |
|---|---|---|
| Train 1 (Foundation) | S1 | Internal — foundation hardened; M1+M2 verified |
| Train 2 (Core Logistics) | S2–S5 | Customer-facing — full shipment + equipment lifecycle |
| Train 3 (Commercial) | S6–S8 | Revenue-ready — contracts, billing, projections |
| Train 4 (Intelligence) | S9–S12 | Full GA — AI, self-service, scale |

---

## 2. Sprint 1 — Foundation Hardening

**Duration:** Weeks 1–2  
**Theme:** Close all M2→M3 pre-entry conditions; CI automation; test uplift  
**Exit Gate:** M3 Pre-Entry Checklist (docs/16 §3) fully green

### Squad A (Domain)

#### Task 1.A.1 — Wire ShipmentService Domain Events

**Priority:** P0 — BLOCKING M3  
**Effort:** 0.5 day  
**Files:** `app/services/shipment_service.py`, `app/repositories/event_store_repository.py`

Every `transition()` call must write a domain event to the outbox in the same transaction:

```python
# In transition():
event = ShipmentStatusChanged(
    shipment_id=shipment.id,
    from_status=old_status,
    to_status=new_status,
)
envelope = EventEnvelope.create(
    event,
    tenant_id=shipment.tenant_id,
    aggregate_id=shipment.id,
    aggregate_version=shipment.version,
    aggregate_type="Shipment",
    user_id=current_user_id,
)
EventStoreRepository(session).append(envelope)
```

Domain events to define and register:
- `ShipmentCreated` (v1)
- `ShipmentStatusChanged` (v1) — emitted on every allowed transition
- `ShipmentAssigned` (v1) — when driver + vehicle assigned
- `ShipmentDelivered` (v1) — with POD reference
- `ShipmentCancelled` (v1) — with cancellation reason

#### Task 1.A.2 — Define and Register Shipment Domain Events

**Files:** `app/events/shipment_events.py` (new), `app/events/__init__.py`

Create `@register_event` decorated dataclasses for all 5 shipment events. Register in process-wide `event_registry`.

#### Task 1.A.3 — Service Unit Tests

**Effort:** 2 days  
**Files:** `tests/test_auth_service.py` (new), `tests/test_driver_service.py` (new), `tests/test_shipment_service.py` (new)

Minimum 10 unit tests per service using DB-free fake sessions (same pattern as `test_projection_engine.py`):
- `AuthService`: valid login, invalid password, user not found, inactive user, JWT payload correctness
- `DriverService`: create driver, update availability, not-found, duplicate, tenant scoping
- `ShipmentService`: all allowed transitions, all forbidden transitions raise error, event emitted per transition, optimistic lock conflict

#### Task 1.A.4 — Celery Beat Schedule

**Files:** `app/workers/celery_app.py`

Add `beat_schedule` to the Celery app:

```python
app.conf.beat_schedule = {
    "relay-outbox-every-30s": {
        "task": "app.workers.tasks.relay_outbox",
        "schedule": 30.0,
    },
}
```

Verify relay runs in docker-compose environment with `make docker-up`.

### Squad B (Infrastructure)

#### Task 1.B.1 — CI Pipeline

**Files:** `.github/workflows/ci.yml` (new)

```yaml
jobs:
  test:
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: test, POSTGRES_DB: mesaar_test }
    steps:
      - run: pip install -r requirements.txt
      - run: alembic upgrade head
        env: { DATABASE_URL: postgresql://postgres:test@localhost/mesaar_test }
      - run: pytest --cov=app --cov-fail-under=30
        env: { DATABASE_URL: postgresql://postgres:test@localhost/mesaar_test }
  lint:
    steps:
      - run: ruff check app/ tests/
      - run: mypy app/
```

**Critical:** PostgreSQL service must use a non-superuser application role. Create a `mesaar_app` role without superuser in CI:

```sql
CREATE ROLE mesaar_app LOGIN PASSWORD 'test';
GRANT CONNECT ON DATABASE mesaar_test TO mesaar_app;
-- After alembic upgrade:
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mesaar_app;
```

The integration tests must connect as `mesaar_app` to validate RLS is enforced.

#### Task 1.B.2 — Coverage Gate

Set `--cov-fail-under=30` in `pytest.ini` for Sprint 1. Increase to 50% by Sprint 3, 65% by Sprint 6, 80% by Sprint 12.

#### Task 1.B.3 — OpenAPI Spec Export

Add a Makefile target that exports the FastAPI OpenAPI JSON:

```makefile
openapi:
    python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" > docs/openapi.json
```

Include in CI to ensure the spec is always current.

### Sprint 1 Exit Criteria

- [ ] All 5 shipment domain events defined and registered
- [ ] `ShipmentService.transition()` emits event in same transaction
- [ ] PG integration test: `test_shipment_emits_events_on_transition`
- [ ] Service unit tests: ≥10 per service (Auth, Driver, Shipment)
- [ ] CI pipeline green with non-superuser PostgreSQL role
- [ ] Celery beat schedule confirmed in docker-compose
- [ ] Coverage ≥ 30%
- [ ] `docs/openapi.json` committed

---

## 3. Sprint 2 — Customer & Orders Core

**Duration:** Weeks 3–4  
**Theme:** M3 — Customer Management + Order lifecycle core  
**Prerequisites:** Sprint 1 exit criteria all green

### Deliverables

#### Models (Migration 0006)

```python
# app/models/customer.py
class Customer(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "customers"
    tenant_id: Mapped[UUID]
    name: Mapped[str]
    tax_id: Mapped[Optional[str]]          # VAT registration
    credit_limit: Mapped[Decimal]
    credit_used: Mapped[Decimal]
    status: Mapped[str]                    # VARCHAR+CHECK: active/suspended/blacklisted
    version: Mapped[int]

class CustomerContact(BaseModel, TimestampMixin):
    __tablename__ = "customer_contacts"
    customer_id: Mapped[UUID]              # FK → customers
    tenant_id: Mapped[UUID]
    name: Mapped[str]
    email: Mapped[str]
    phone: Mapped[str]
    role: Mapped[str]                      # VARCHAR+CHECK: primary/billing/operations
```

```python
# app/models/order.py
class Order(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "orders"
    tenant_id: Mapped[UUID]
    customer_id: Mapped[UUID]              # FK → customers
    status: Mapped[str]                    # open/submitted/approved/fulfilling/completed/cancelled
    origin_address: Mapped[dict]           # JSONB
    destination_address: Mapped[dict]      # JSONB
    requested_pickup_at: Mapped[datetime]
    cargo_description: Mapped[str]
    total_weight_kg: Mapped[Decimal]
    total_volume_cbm: Mapped[Decimal]
    special_requirements: Mapped[dict]    # JSONB
    version: Mapped[int]

class OrderLine(BaseModel, TimestampMixin):
    __tablename__ = "order_lines"
    order_id: Mapped[UUID]                 # FK → orders
    tenant_id: Mapped[UUID]
    description: Mapped[str]
    quantity: Mapped[int]
    unit_weight_kg: Mapped[Decimal]
    unit_volume_cbm: Mapped[Decimal]
    cargo_type: Mapped[str]               # VARCHAR+CHECK
```

RLS + FORCE on both tables. tenant_id GUC policy.

#### Repositories

- `CustomerRepository` — CRUD + credit check + suspend/blacklist
- `OrderRepository` — CRUD + status filter + customer filter

#### Services

- `CustomerService` — create, update, credit-check, suspend
- `OrderService` — submit, approve (credit-gated), cancel (CF1 compensation)

#### Domain Events

```
OrderCreated (v1)
OrderSubmitted (v1)
OrderApproved (v1)
OrderCancelled (v1)
CustomerCreated (v1)
CustomerCreditChecked (v1)
```

#### API Routes

`/v1/customers` — CRUD (dispatcher, platform_admin)  
`/v1/orders` — CRUD + status transitions (dispatcher, customer)

#### Tests

- `CustomerRepository` — create, duplicate tax_id, credit check
- `OrderService` — approve with credit, approve over credit limit → reject
- API: `POST /customers`, `GET /customers/{id}`, `POST /orders`, `GET /orders/{id}`

### Sprint 2 Exit Criteria

- [ ] Migration 0006 applied; `customers`, `customer_contacts`, `orders`, `order_lines` tables with RLS
- [ ] `CustomerRepository` + `OrderRepository` with full CRUD
- [ ] `CustomerService` + `OrderService` with credit gate
- [ ] 6 domain events registered and emitted on state changes
- [ ] `/v1/customers` and `/v1/orders` routes operational with RBAC
- [ ] ≥ 15 new tests (unit + integration)
- [ ] Coverage ≥ 35%

---

## 4. Sprint 3 — Shipment Saga & Order Fulfillment

**Duration:** Weeks 5–6  
**Theme:** M3 complete — Order→Shipment fan-out saga; CF1 compensation

### Deliverables

#### Order→Shipment Fan-Out Saga

When `OrderApproved` event is dispatched, a Celery task fan-out creates one `Shipment` per `OrderLine` (or per logical grouping). Each shipment FK references `order_id`.

Add `order_id` FK to shipments (additive migration 0007):

```sql
ALTER TABLE shipments ADD COLUMN order_id uuid REFERENCES orders(id) ON DELETE RESTRICT;
CREATE INDEX ix_shipments_order ON shipments (tenant_id, order_id) WHERE order_id IS NOT NULL;
```

#### CF1 Compensation Workflow

When an order in `fulfilling` status is cancelled (`OrderCancelled` with `from_status=fulfilling`):

1. Fan-out `ShipmentCancelled` to all linked shipments (Celery chord)
2. Emit `OrderFulfilmentFailed` event
3. Calculate and emit `OrderCancellationFeeApplied` if fee applies
4. Audit all steps in audit_log

```python
# app/services/order_service.py
def cancel_with_compensation(self, order_id, *, reason: str, cancellation_fee: Decimal) -> None:
    ...
```

#### Shipment State Machine Wire-Up (Full)

Connect all 8 shipment states to domain events and verify full replay. State transitions:

```
pending → assigned          → ShipmentAssigned
assigned → in_transit       → ShipmentPickedUp
in_transit → delivered      → ShipmentDelivered (+ POD reference)
* → cancelled               → ShipmentCancelled (+ CF1 compensation if from fulfilling)
in_transit → failed         → ShipmentFailed
failed → pending            → ShipmentRetried
```

#### Tests

- Full saga: `test_order_approved_creates_shipments`
- CF1: `test_fulfilling_order_cancel_cascades_shipment_cancel`
- Idempotency: saga re-played from event log produces same result
- API: `POST /orders/{id}/approve`, `POST /orders/{id}/cancel`

### Sprint 3 Exit Criteria

- [ ] Migration 0007: `order_id` FK on shipments
- [ ] `OrderApproved` → Celery saga → Shipment fan-out working
- [ ] CF1 compensation saga implemented and tested
- [ ] All 8 shipment states wired to domain events
- [ ] Saga idempotency test green
- [ ] M3 milestone COMPLETE
- [ ] Coverage ≥ 40%

---

## 5. Sprint 4 — Heavy Equipment Domain

**Duration:** Weeks 7–8  
**Theme:** M4 — Equipment catalog; unit lifecycle; operator certifications

### Deliverables

#### Models (Migration 0008)

```python
# Per docs/11 §1.4 column specs
class EquipmentCategory(BaseModel, TimestampMixin):
    __tablename__ = "equipment_categories"
    # name, description, oversize_class

class EquipmentModel(BaseModel, TimestampMixin):
    __tablename__ = "equipment_models"
    # category_id, manufacturer, model_name, max_payload_kg, dimensions JSONB

class Equipment(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "equipment"
    # tenant_id, model_id, serial_number, status, oversize_class
    # transport_requirements JSONB, current_operator_id, version
```

Equipment status CHECK: `available`, `reserved`, `assigned`, `in_transit`, `delivered`, `returned`, `out_of_service`.

```python
class OperatorCertification(BaseModel, TimestampMixin):
    __tablename__ = "operator_certifications"
    # tenant_id, driver_id, cert_type, issued_at, expires_at, issuing_authority, status
```

#### Services

- `EquipmentService` — catalog CRUD, reserve, assign, lifecycle transitions
- Cert expiry sweep Celery task (daily): finds certs expiring within 30 days, emits `CertificationExpiringSoon`

#### Domain Events

```
EquipmentRegistered (v1)
EquipmentStatusChanged (v1)
EquipmentReserved (v1)
EquipmentAssigned (v1)
CertificationIssued (v1)
CertificationExpired (v1)
CertificationExpiringSoon (v1)
```

#### API Routes

`/v1/equipment` — CRUD + lifecycle (fleet_admin, dispatcher)  
`/v1/equipment/categories` — category management (platform_admin)  
`/v1/operator-certifications` — cert CRUD (fleet_admin)

#### Tests

- Equipment lifecycle transitions (all allowed, all forbidden)
- Cert expiry sweep emits event for certs expiring in 29 days
- Reserve equipment prevents double-reservation (exclusivity index)
- API: equipment CRUD + lifecycle endpoints

### Sprint 4 Exit Criteria

- [ ] Migration 0008: equipment tables with RLS
- [ ] Equipment lifecycle state machine (7 states)
- [ ] Operator certification CRUD + expiry sweep
- [ ] 7 domain events registered and emitted
- [ ] Exclusivity index: one active assignment per equipment unit
- [ ] `/v1/equipment` routes operational
- [ ] Coverage ≥ 44%

---

## 6. Sprint 5 — Compliance, Permits & Route Compliance

**Duration:** Weeks 9–10  
**Theme:** M4 complete — Permit workflow; axle weight; route compliance hard gate

### Deliverables

#### Models (Migration 0009)

```python
class Permit(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "permits"
    # tenant_id, shipment_id, equipment_id, permit_type, status
    # issuing_authority, valid_from, valid_until, conditions JSONB, version

class Escort(BaseModel, TimestampMixin):
    __tablename__ = "escorts"
    # permit_id, tenant_id, escort_type, assigned_vehicle_id, status

class AxleWeightProfile(BaseModel, TimestampMixin):
    __tablename__ = "axle_weight_profiles"
    # equipment_id, axle_config JSONB, max_gcw_kg, legal_limit_kg

class RouteRestriction(BaseModel, TimestampMixin):
    __tablename__ = "route_restrictions"
    # restriction_type (height/weight/bridge/tunnel/hazmat), geometry JSONB
    # max_height_cm, max_weight_kg, applies_to_oversize, active

class ComplianceCheck(BaseModel, TimestampMixin):
    __tablename__ = "compliance_checks"
    # shipment_id, equipment_id, checked_at, result, violations JSONB
```

#### Compliance Service (Hard Gate)

`ComplianceService.check_dispatch_eligibility(shipment_id, equipment_id)` — raises `ComplianceViolationError` if ANY of:
- No valid permit for oversize equipment
- Transport height > route clearance
- Axle/GCW over legal limit
- Escort not assigned (if required by permit)
- Required operator certifications expired
- Permit expires before scheduled delivery

This gate is inserted into `ShipmentService.transition(→ in_transit)` before allowing the transition.

#### Domain Events

```
PermitRequested (v1)
PermitApproved (v1)
PermitRejected (v1)
PermitExpired (v1)
RouteComplianceChecked (v1)
ComplianceViolationDetected (v1)
EscortAssigned (v1)
```

#### API Routes

`/v1/permits` — CRUD + approval workflow (dispatcher, compliance_officer)  
`/v1/compliance/check` — on-demand compliance check (dispatcher)

#### Tests

- `ComplianceService.check_dispatch_eligibility()` — all 6 hard gate conditions
- Attempting `in_transit` transition without compliance check → `ComplianceViolationError`
- Permit expiry sweep emits `PermitExpired`
- API: permit lifecycle endpoints

### Sprint 5 Exit Criteria

- [ ] Migration 0009: permit, escort, axle-profile, route-restriction, compliance-check tables
- [ ] `ComplianceService` with all 6 hard gates
- [ ] Dispatch gate wired into `ShipmentService.transition(→ in_transit)`
- [ ] Permit lifecycle (6 states) with domain events
- [ ] M4 milestone COMPLETE
- [ ] Coverage ≥ 48%

---

## 7. Sprint 6 — Contract Management & Pricing

**Duration:** Weeks 11–12  
**Theme:** M5 — Contract core; pricing rules; SLA definitions

### Deliverables

#### Models (Migration 0010)

```python
class Contract(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "contracts"
    # tenant_id, customer_id, carrier_id(FK users), status
    # Contract state machine: draft → negotiation → active ⇄ suspended → expired|terminated

class PricingRule(BaseModel, TimestampMixin):
    __tablename__ = "pricing_rules"
    # contract_id, rule_type, base_rate, distance_rate, weight_rate
    # cargo_type_surcharges JSONB, effective_from, effective_until

class SLA(BaseModel, TimestampMixin):
    __tablename__ = "slas"
    # contract_id, metric_type (on_time_delivery/document_submission/etc)
    # target_value, measurement_window, penalty_rate

class Penalty(BaseModel, TimestampMixin):
    __tablename__ = "penalties"
    # contract_id, shipment_id, penalty_type, amount, currency_code
    # triggered_by_event_id, applied_at

class CarrierAgreement(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "carrier_agreements"
    # tenant_id, carrier_id, terms JSONB, effective_from, effective_until
```

#### Services

- `ContractService` — draft, negotiate, activate, suspend, expire
- `PricingService` — `calculate_quote(shipment_spec)` → price breakdown
- `SLAService` — evaluate SLA compliance on delivery; trigger penalties

#### Domain Events

```
ContractDrafted (v1)
ContractActivated (v1)
ContractSuspended (v1)
ContractTerminated (v1)
PricingRuleDefined (v1)
SLADefined (v1)
SLAViolationDetected (v1)
SLAPenaltyApplied (v1)
```

#### API Routes

`/v1/contracts` — CRUD + lifecycle (platform_admin, contract_manager)  
`/v1/pricing/quote` — rate calculation (dispatcher)  
`/v1/slas` — SLA management (contract_manager)

### Sprint 6 Exit Criteria

- [ ] Migration 0010: contract, pricing_rule, sla, penalty, carrier_agreement tables
- [ ] Contract state machine (5 states) with domain events
- [ ] `PricingService.calculate_quote()` with rule evaluation
- [ ] SLA evaluation on `ShipmentDelivered` event
- [ ] 8 domain events registered and emitted
- [ ] Coverage ≥ 52%

---

## 8. Sprint 7 — Billing, Insurance & Claims

**Duration:** Weeks 13–14  
**Theme:** M5 complete — Settlement; insurance policies; claims FNOL→close

### Deliverables

#### Models (Migration 0011)

```python
class InsurancePolicy(BaseModel, TimestampMixin, AuditMixin):
    __tablename__ = "insurance_policies"
    # tenant_id, policy_number, insured_value, premium, deductible
    # coverage_type, valid_from, valid_until

class Claim(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "claims"
    # tenant_id, policy_id, shipment_id, status
    # Claim states: created → under_review → approved|rejected → settled → closed (+ reopened)
    # reported_at, settled_at, claim_amount, approved_amount, currency_code, version

class DamageReport(BaseModel, TimestampMixin):
    __tablename__ = "damage_reports"
    # claim_id, description, photos JSONB, estimated_value, surveyor_id

# Billing / Settlement
class SettlementRecord(BaseModel, TimestampMixin):
    __tablename__ = "settlement_records"
    # tenant_id, shipment_id, contract_id, amount, currency_code
    # status (pending/approved/paid/disputed), settled_at
```

#### Services

- `BillingService` — `generate_invoice(shipment_id)`, settle, dispute
- `InsuranceService` — policy attach, FNOL filing, claim assessment
- `ClaimsService` — claim lifecycle (created→reviewed→approved/rejected→settled→closed)

#### Domain Events

```
InsurancePolicyAttached (v1)
ClaimFiled (v1)
ClaimAssessed (v1)
ClaimApproved (v1)
ClaimRejected (v1)
ClaimSettled (v1)
SettlementGenerated (v1)
PaymentFailed (v1)
```

#### Integration with Contract

`ShipmentDelivered` → `SLAService.evaluate()` → if SLA breach → `SLAPenaltyApplied` → `BillingService.add_penalty_to_invoice()`

### Sprint 7 Exit Criteria

- [ ] Migration 0011: insurance_policies, claims, damage_reports, settlement_records
- [ ] Claim lifecycle (6 states) with domain events
- [ ] `BillingService.generate_invoice()` + settlement flow
- [ ] `InsuranceService` FNOL + assessment flow
- [ ] Full M5 milestone COMPLETE
- [ ] Coverage ≥ 55%

---

## 9. Sprint 8 — Projections & Control Tower

**Duration:** Weeks 15–16  
**Theme:** M6 — Read models; lag SLO; control tower API

### Deliverables

#### Projection Tables (Migration 0012)

```sql
-- Per docs/03 §read-models
CREATE TABLE proj_active_shipments (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    shipment_id UUID UNIQUE NOT NULL,
    status TEXT NOT NULL,
    driver_name TEXT,
    vehicle_plate TEXT,
    origin_city TEXT,
    destination_city TEXT,
    eta TIMESTAMPTZ,
    sla_risk_score REAL,
    last_updated TIMESTAMPTZ NOT NULL
);

CREATE TABLE proj_driver_status (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    driver_id UUID UNIQUE NOT NULL,
    availability TEXT,
    current_shipment_id UUID,
    last_location JSONB,
    last_updated TIMESTAMPTZ
);

CREATE TABLE proj_warehouse_load (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    warehouse_id UUID UNIQUE NOT NULL,
    current_load_cbm NUMERIC,
    capacity_cbm NUMERIC,
    utilization_pct REAL,
    last_updated TIMESTAMPTZ
);

CREATE TABLE proj_sla_risk (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    shipment_id UUID UNIQUE NOT NULL,
    risk_score REAL,
    breach_probability REAL,
    factors JSONB,
    evaluated_at TIMESTAMPTZ
);

-- RLS on all proj_* tables (same tenant_isolation policy)
```

#### Projection Builders (EventHandlers)

```python
# app/projections/active_shipments.py
class ActiveShipmentsProjection(Projection):
    name = "active-shipments"
    event_types = frozenset({"ShipmentCreated", "ShipmentStatusChanged", "ShipmentAssigned", "ShipmentDelivered", "ShipmentCancelled"})
    
    def handle(self, event, envelope, session) -> None:
        # Upsert proj_active_shipments row
        ...
    
    def reset(self, session, tenant_id=None) -> None:
        # DELETE FROM proj_active_shipments WHERE tenant_id = :tid
        ...
```

Register all projection builders in the event bus. Wire Celery task for projection rebuild.

#### Control Tower API

`/v1/control-tower/shipments` — active shipment dashboard (p95 < 100ms — read from proj_active_shipments)  
`/v1/control-tower/exceptions` — SLA-at-risk shipments (from proj_sla_risk)  
`/v1/control-tower/drivers` — driver availability map (from proj_driver_status)  
`/v1/control-tower/warehouses` — warehouse load summary (from proj_warehouse_load)

#### Lag Monitoring

Celery beat task: every 60s, query `OUTBOX_DEPTH` + projection staleness; alert if lag > 5 minutes.

### Sprint 8 Exit Criteria

- [ ] Migration 0012: all 4 proj_* tables with RLS
- [ ] 4 projection builders registered + wired to event bus
- [ ] `ProjectionRebuilder.rebuild_by_tenant()` tested for all 4 projections
- [ ] Control Tower API with p95 < 100ms (measured with k6)
- [ ] Lag gauge and staleness alert wired
- [ ] M6 milestone COMPLETE
- [ ] Coverage ≥ 58%

---

## 10. Sprint 9 — Driver Self-Service & Route Management

**Duration:** Weeks 17–18  
**Theme:** M7 — OTP identity; driver accept/decline; route management

### Deliverables

#### ADR-011 — OTP Identity

Write and ratify ADR-011 before implementing. OTP strategy: time-based OTP via SMS (Twilio integration); 6-digit code; 5-minute TTL stored in Redis; max 3 attempts before lockout.

#### Driver Self-Service Enhancement

Current `driver_self.py` has basic `/drivers/me`. Extend:

`GET /drivers/me/shipments/nearby` — returns shipments within 50km of driver location (from proj_active_shipments or live query)  
`POST /drivers/me/shipments/{id}/accept` — driver accepts offer; triggers `ShipmentOfferAccepted` event  
`POST /drivers/me/shipments/{id}/decline` — driver declines; triggers `ShipmentOfferDeclined`; re-broadcast policy P-1

#### Route Management

```python
# app/models/route.py
class Route(BaseModel, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "routes"
    # tenant_id, shipment_id, waypoints JSONB, total_distance_km
    # estimated_duration_minutes, compliance_checked, validated_at, version

class RouteStop(BaseModel, TimestampMixin):
    __tablename__ = "route_stops"
    # route_id, tenant_id, sequence_no, location JSONB, stop_type
    # ETA, ATA, status
```

`RouteService` — create, validate (calls ComplianceService.check_route_compliance()), update, complete.

Domain events: `RouteCreated`, `RouteValidated`, `RouteRestricted`, `RouteCompleted`.

#### API Routes

`/v1/routes` — route CRUD + validation (dispatcher)  
`/v1/drivers/me/shipments/nearby` — nearby shipments (driver self-service)  
`/v1/drivers/me/shipments/{id}/accept` — accept offer  
`/v1/drivers/me/shipments/{id}/decline` — decline offer

### Sprint 9 Exit Criteria

- [ ] ADR-011 (OTP) ratified
- [ ] Driver nearby/accept/decline endpoints operational
- [ ] Route model + RouteService + RouteRepository
- [ ] Route compliance validation integrated with ComplianceService
- [ ] 4 route domain events registered and emitted
- [ ] Coverage ≥ 62%

---

## 11. Sprint 10 — Notifications & Analytics

**Duration:** Weeks 19–20  
**Theme:** M7 complete — Notification fan-out; analytics events; driver app foundation

### Deliverables

#### Notifications

```python
# app/models/notification.py
class Notification(BaseModel, TimestampMixin):
    __tablename__ = "notifications"
    # tenant_id, recipient_id, channel (sms/push/email/in_app)
    # event_type, title, body, status, sent_at, read_at
```

`NotificationService` — event-driven fan-out consumer. Subscribes to:
- `ShipmentAssigned` → notify driver (push + SMS)
- `ShipmentStatusChanged` → notify customer (email + in_app)
- `ShipmentDelivered` → notify dispatcher + customer (email)
- `SLAPenaltyApplied` → notify contract_manager (email)
- `PermitExpired` → notify fleet_admin (push + email)
- `CertificationExpiringSoon` → notify driver + fleet_admin

External channels: SMS (Twilio stub), Push (FCM stub), Email (SendGrid stub). ACL: one channel adapter per provider — easily swappable.

#### Analytics Events (Business Intelligence)

Extend `proj_driver_daily_stats`:

```sql
CREATE TABLE proj_driver_daily_stats (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    driver_id UUID NOT NULL,
    date DATE NOT NULL,
    shipments_completed INT DEFAULT 0,
    shipments_cancelled INT DEFAULT 0,
    total_km NUMERIC(12,2) DEFAULT 0,
    on_time_pct REAL,
    sla_breach_count INT DEFAULT 0,
    UNIQUE (tenant_id, driver_id, date)
);
```

`DriverStatsProjection` — aggregates `ShipmentDelivered` events per driver per day.

#### Mobile App Foundation (M7)

React Native scaffold with:
- Auth screen (email + password → JWT)
- Nearby shipments screen (list from `/drivers/me/shipments/nearby`)
- Accept/decline screen
- Shipment detail screen
- Push notification integration (FCM token registration)

### Sprint 10 Exit Criteria

- [ ] `NotificationService` fan-out for 6 event types
- [ ] External channel stubs (Twilio, FCM, SendGrid) with ACL wrappers
- [ ] `proj_driver_daily_stats` projection builder
- [ ] Mobile app: auth + nearby + accept/decline screens
- [ ] M7 milestone COMPLETE
- [ ] Coverage ≥ 65%

---

## 12. Sprint 11 — AI Operations

**Duration:** Weeks 21–22  
**Theme:** M8 — pgvector; embeddings; ETA/SLA/pricing advisory models

### Deliverables

#### pgvector + Embeddings (Migration 0013)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embeddings (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    model_id TEXT NOT NULL,
    embedding VECTOR(1536),           -- text-embedding-3-small dimension
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, entity_type, entity_id, model_id)
);
CREATE INDEX ix_embeddings_hnsw ON embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE documents (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    doc_type TEXT NOT NULL,
    title TEXT,
    content TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id),
    tenant_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1536)
);
CREATE INDEX ix_doc_chunks_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops);
```

#### ML Feature Store + Predictions

```sql
CREATE TABLE ml_features_shipment (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    shipment_id UUID NOT NULL,
    feature_version INT NOT NULL,
    features JSONB NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE ml_predictions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    shipment_id UUID NOT NULL,
    model_name TEXT NOT NULL,
    prediction_type TEXT NOT NULL,  -- eta/sla_risk/price/assignment_score
    predicted_value JSONB NOT NULL,
    confidence REAL,
    predicted_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE ml_feedback (
    id UUID PRIMARY KEY,
    prediction_id UUID NOT NULL REFERENCES ml_predictions(id),
    tenant_id UUID NOT NULL,
    actual_value JSONB,
    feedback_at TIMESTAMPTZ NOT NULL
);
```

#### AI Services (Advisory — Read-Only, No Side Effects)

- `ETAAdvisoryService.predict(shipment_id)` — returns ETA estimate with confidence interval
- `SLARiskAdvisoryService.score(shipment_id)` — returns breach probability 0–1
- `PricingAdvisoryService.suggest_rate(shipment_spec)` — returns suggested pricing
- `AssignmentAdvisoryService.rank_drivers(shipment_id)` — returns ranked driver list

All services read from `ml_features_shipment` + call ML runtime (external stub). Store prediction in `ml_predictions`. Feedback loop: on `ShipmentDelivered`, write actual vs predicted to `ml_feedback`.

#### API Routes

`/v1/advisory/eta/{shipment_id}` — ETA prediction  
`/v1/advisory/sla-risk/{shipment_id}` — SLA risk score  
`/v1/advisory/pricing` — pricing suggestion  
`/v1/advisory/assignments/{shipment_id}` — driver ranking

### Sprint 11 Exit Criteria

- [ ] pgvector extension + HNSW indexes deployed
- [ ] embeddings, documents, document_chunks, ml_features_shipment, ml_predictions, ml_feedback tables
- [ ] 4 advisory services with stubs returning mock ML predictions
- [ ] Feedback loop: `ShipmentDelivered` → ml_feedback write
- [ ] M8 milestone COMPLETE
- [ ] Coverage ≥ 68%

---

## 13. Sprint 12 — Scale, Security & GA

**Duration:** Weeks 23–24  
**Theme:** M9 — Load test; pen-test; KMS; DR; EDI gateway; General Availability

### Deliverables

#### Load Testing (k6)

```javascript
// tests/load/shipment_lifecycle.js
import http from 'k6/http';
export const options = {
  stages: [
    { duration: '5m', target: 100 },   // ramp-up
    { duration: '30m', target: 500 },  // sustained load
    { duration: '5m', target: 0 },     // ramp-down
  ],
  thresholds: {
    http_req_duration: ['p95<300'],    // all endpoints p95 < 300ms
    http_req_failed: ['rate<0.01'],    // < 1% error rate
  },
};
```

SLO targets:
- API p95 < 300ms
- Outbox lag < 5 minutes (99th percentile)
- Availability ≥ 99.5% per rolling 30 days

#### Security Hardening

- [ ] Penetration test (third-party or internal red team)
- [ ] KMS-backed SECRET_KEY (AWS KMS / Azure Key Vault via ADR-012)
- [ ] Refresh token rotation + Redis blacklist for logout
- [ ] Rate limiting: 100 req/min per user; 1000 req/min per tenant (nginx or API gateway)
- [ ] Dependency vulnerability scanning in CI (`pip audit` or `safety`)
- [ ] Brute-force lockout: 5 failed logins → 15-minute lockout (Redis counter)

#### Data Residency & Erasure (ADR-014)

- Tenant data residency tags (KSA / GCC)
- GDPR-aligned `right_to_erasure` endpoint: soft-delete + anonymize PII
- Audit log retention: 7 years (configurable per tenant)

#### DR / PITR Documentation

- Runbook: deploy, rollback, failover
- PITR: PostgreSQL WAL archiving to S3 / Azure Blob
- RTO target: < 4 hours; RPO target: < 15 minutes

#### EDI / Partner Gateway (ADR-013)

- Rate-limited API gateway (nginx + lua or Kong)
- Partner API keys (scope-limited JWT)
- Webhook delivery for external integrations
- EDI adapter stub (EDIFACT / X12 format adapters)

#### ADRs to Ratify

- [ ] ADR-010 (MLOps) — model registry, versioning, retraining
- [ ] ADR-011 (OTP identity) — from Sprint 9
- [ ] ADR-012 (KMS) — key management
- [ ] ADR-013 (API gateway / rate-limit)
- [ ] ADR-014 (data residency / erasure)
- [ ] ADR-015 (OLAP / analytics throughput)

### Sprint 12 Exit Criteria

- [ ] Load test passing: p95 < 300ms; error rate < 1%; sustained 500 concurrent users
- [ ] Pen-test complete; all P0/P1 findings resolved
- [ ] KMS-backed secret key in production environment
- [ ] Refresh token rotation + brute-force lockout
- [ ] Rate limiting enforced
- [ ] PITR configured + DR runbook written
- [ ] ADR-010–015 all ratified
- [ ] Coverage ≥ 80%
- [ ] **M9 milestone COMPLETE → General Availability**

---

## 14. Critical Path & Dependencies

```
S1 (Foundation) ──────────────────────────────────────────────────────┐
                                                                       │
S1 → S2 (Customer + Orders) → S3 (Saga + Fulfillment)               │
                                         │                             │
                                         ├─→ S4 (Heavy Equipment) ──┐ │
                                         │   → S5 (Compliance)      │ │
                                         │                           │ │
                                         └─→ S6 (Contracts) ─→ S7  │ │
                                                   (Billing+Claims)  │ │
                                                         │            │ │
S8 (Projections) ← requires S3+S5+S7 ─────────────────┘ │
                                                          │
S9 (Driver+Route) ──── can parallel S6/S7 ───────────────┤
→ S10 (Notifications+Analytics) ─────────────────────────┤
                                                          │
S11 (AI Ops) ← requires S8 + S10 ───────────────────────┘
→ S12 (Scale + Security + GA)
```

### Hard Dependencies

| Sprint | Requires | Why |
|---|---|---|
| S2 | S1 complete | ShipmentService must emit events before Order saga |
| S3 | S2 complete | Saga depends on OrderApproved event |
| S4 | S1 complete | M1+M2 gate for new aggregate |
| S5 | S4 complete | Compliance requires Equipment models |
| S6 | S3 complete | Contracts reference Orders and Customers |
| S7 | S6 complete | Claims reference Contracts and Policies |
| S8 | S3+S5+S7 | Projections need complete event stream |
| S9 | S1+S4 | Route compliance needs Equipment |
| S10 | S9 | Notifications depend on all event types being registered |
| S11 | S8+S10 | AI needs projection data and analytics events |
| S12 | S11 | GA requires all milestones complete |

### Two-Squad Parallelism

With two squads, the following pairs run concurrently:

| Weeks | Squad A | Squad B |
|---|---|---|
| 1–2 | S1 Domain tasks | S1 Infrastructure tasks |
| 3–4 | S2 (Customer+Orders) | S4 planning + ADR-008 implementation |
| 5–6 | S3 (Saga+Fulfillment) | S4 (Heavy Equipment) |
| 7–8 | S5 (Compliance) | S6 (Contract) |
| 9–10 | S7 (Billing+Claims) | S9 (Driver+Route) |
| 11–12 | S8 (Projections) | S10 (Notifications) |
| 13–14 | S11 (AI Ops) | S12 Security hardening |
| 15–16 | S12 Load test + DR | S12 ADRs + GA prep |

**Two-squad timeline: 16 weeks (4 months) vs 24 weeks single-squad**

---

## 15. Governance & Definition of Done

### Per-Story Definition of Done

A story is DONE only when ALL are true:

- [ ] Code reviewed and approved by a second engineer
- [ ] All new domain events registered in `event_registry`
- [ ] Domain events emitted in same transaction as aggregate write
- [ ] Migration is additive; no destructive column changes; passes `alembic upgrade head` on a clean DB
- [ ] Repository raises `NotFoundError` / `ConflictError` (not SQLAlchemy exceptions directly)
- [ ] Service has ≥ 5 unit tests covering happy path + 2 error paths
- [ ] Route has integration test covering 200 + at least one 4xx case
- [ ] Coverage does not drop below sprint threshold
- [ ] `make lint` passes (ruff, mypy)
- [ ] OpenAPI spec regenerated and committed

### Per-Milestone Definition of Done

A milestone (M3–M9) is DONE only when:

- [ ] All story DoD items complete for every story in the milestone
- [ ] PG integration test for every new aggregate's isolation
- [ ] Domain events verified end-to-end: emit → relay → dispatch → projection
- [ ] Milestone compliance report section written in `docs/14` (or new M-compliance doc)
- [ ] Coverage ≥ sprint threshold
- [ ] docker-compose `make docker-up` starts cleanly including all new services

### Branch Policy

```
main                ← only merge via PR; requires CI green + 1 reviewer
feature/<name>      ← all feature work
release/<M3|M4|…>  ← per-milestone integration branch (optional for train releases)
```

### Migration Policy

1. Every sprint produces at most ONE migration file
2. Migration file numbers are sequential (0006, 0007, …)
3. No `ALTER COLUMN … TYPE` that could lose data
4. No `DROP TABLE` or `DROP COLUMN` without a prior deprecation sprint
5. All new tables get RLS + tenant_isolation policy if they have a `tenant_id` column
6. All new FK columns must have a corresponding index

### Test Pyramid Targets

| Level | Sprint 3 | Sprint 6 | Sprint 9 | Sprint 12 (GA) |
|---|---|---|---|---|
| Unit tests | 80+ | 180+ | 280+ | 400+ |
| Integration (PG) | 20+ | 45+ | 70+ | 100+ |
| API integration | 15+ | 50+ | 80+ | 120+ |
| Load tests | 0 | 2 scenarios | 5 scenarios | 10 scenarios |
| Coverage | 40% | 55% | 65% | 80% |

### Observability Standards (all new code)

Every new service module must:
1. Emit Prometheus counter on each aggregate state transition
2. Emit Prometheus histogram on every external call (DB read, Redis, external API)
3. Log at INFO on every state transition with structured fields: `tenant_id`, `aggregate_id`, `from_status`, `to_status`, `user_id`
4. Log at WARNING on every retry
5. Log at ERROR on every DLQ exhaustion or compliance violation

---

*This roadmap supersedes the timeline section of `docs/07-phase-5-execution-plan.md` (which defined M0–M9 milestones) and provides the sprint-level breakdown for execution. The milestone definitions in `docs/07` and `docs/12` remain authoritative for milestone scope and exit criteria; this document provides the sprint-level scheduling and cross-sprint dependencies.*
