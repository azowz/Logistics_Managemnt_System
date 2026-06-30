# 23 — Billing & Settlements Domain (Sprint 9)

> Status: **IMPLEMENTED & VERIFIED**. Implements bounded context **#18 — Billing
> & Settlements** (docs/09, docs/10). Closes the commercial loop: quotes,
> invoices, payments, settlements, payouts, penalties, and consumption of
> approved claim outcomes.

---

## 1. Domain purpose

Owns the platform's **commercial/financial state**: **quotes**, **invoices** +
**invoice lines**, **payments**, **settlements**, **payouts**, and **penalties /
cancellation fees**. Billing references Customer / Order / Shipment / Quote /
Claim **by id**; those contexts do not own the billing lifecycle. Billing
**consumes** approved/settled claim outcomes (Sprint 8) to create settlement
records — Claims keeps ownership of the claim lifecycle.

## 2. Aggregate ownership

| Concern | Owner |
| --- | --- |
| Quotes | `Quote` + `QuoteStateMachine` (`app/services/billing_policies.py`) |
| Invoices + lines | `Invoice` + `InvoiceLine` + `InvoiceStateMachine` |
| Payments | `Payment` |
| Settlements | `Settlement` + `SettlementStateMachine` |
| Payouts | `Payout` |
| Penalties / cancellation fees | `Penalty` |
| Services | `BillingService` (quotes/invoices/payments/penalties), `SettlementService` (settlements/payouts/claim consumption) |
| Repositories | `app/repositories/billing_repository.py` (7) |
| Events | `app/events/billing_events.py` (24) |
| API | `app/api/routes/billing.py` |
| Schemas | `app/schemas/billing.py` |

## 3. Quote lifecycle

```
draft → issued → {approved, rejected, expired, cancelled}
approved → cancelled
```
Terminal: `rejected`, `expired`, `cancelled`. A quote past its `valid_until`
cannot be approved (expire it instead); an **expired** quote cannot be converted
to an invoice. Quote `total_amount = subtotal + tax − discount` (computed).

## 4. Invoice lifecycle

```
draft → {issued, cancelled}
issued → {partially_paid, paid, overdue, voided, cancelled}
partially_paid → paid
overdue → {partially_paid, paid}
```
Terminal: `paid`, `voided`, `cancelled`. Rules enforced by `BillingService`:
- issue requires a **positive total** unless the invoice is a credit note.
- `total = subtotal + tax + penalty_amount − claim_adjustment_amount`, where
  subtotal/tax/discount are recomputed from the invoice lines.
- a **paid** invoice cannot be voided without an authorized (ADMIN) override.

## 5. Payment handling

`record_payment` creates a `confirmed` payment by default; payment currency must
match the invoice and the amount may not exceed the remaining balance (unless an
ADMIN override is set). After a confirmed payment the invoice advances to
`paid` (balance ≤ 0) or `partially_paid`. A `pending` payment (`confirm=false`)
does not move the invoice and may later be marked **failed**
(`PaymentFailed`). Balance = `total − Σ confirmed payments`.

## 6. Settlement lifecycle

```
draft → pending_approval → approved → settled
{draft, pending_approval, approved} → cancelled
```
Terminal: `settled`, `cancelled`. A settlement cannot be settled before
approval. A claim-backed settlement (`claim_payout` / `claim_offset`) requires an
**approved or settled** claim and an amount **≤ the claim's approved amount**
unless an ADMIN override is set. `create_payout` is only valid for an approved
or settled settlement.

## 7. Claim settlement consumption

`SettlementService.consume_claim_settlement` (and `create_settlement` with a
`claim_id`) validates the claim is approved/settled and bounded, creates the
settlement, and emits `ClaimSettlementConsumed`. A **read-only**
`ClaimRepository` is used for validation — there is **no** dependency on
`ClaimsService`, so no circular dependency is introduced, and the claim
aggregate is never mutated by Billing.

## 8. Order integration

Quotes, invoices, penalties, and cancellation fees may reference `order_id`
(validated tenant-owned, SET NULL FK). Order does not own the billing lifecycle.

## 9. Shipment integration

Quotes, invoices, penalties, and settlements may reference `shipment_id`
(validated tenant-owned, SET NULL FK). Shipment does not own the billing lifecycle.

## 10. Events (24)

Quote: `QuoteCreated/Issued/Approved/Rejected/Expired/Cancelled`. Invoice:
`InvoiceCreated/Issued/PartiallyPaid/Paid/Overdue/Voided/Cancelled`. Payment:
`PaymentRecorded/Failed`. Settlement: `SettlementCreated/SubmittedForApproval/
Approved/Settled/Cancelled`. Plus `PayoutCreated`, `PenaltyApplied`,
`CancellationFeeApplied`, `ClaimSettlementConsumed`. All frozen/slots,
`@register_event`, JSONB-safe, tenant-aware, versioned.

## 11. API contract

Quotes: `POST/GET /billing/quotes`, `GET /billing/quotes/search`,
`GET/PATCH /billing/quotes/{id}`, lifecycle `issue/approve/reject/expire/cancel`.
Invoices: `POST/GET /billing/invoices`, `GET /billing/invoices/search`,
`GET/PATCH /billing/invoices/{id}`, `GET .../lines`, `issue`, `POST/GET
.../payments`, `void`, `cancel`. Settlements: `POST/GET /billing/settlements`,
`GET .../search`, `GET/PATCH .../{id}`, `submit/approve/settle/cancel`, `POST/GET
.../payouts`. Penalties: `POST/GET /billing/penalties`. Literal paths precede
`{id}`; routes are thin with RBAC.

## 12. Security model & tenant isolation

`tenant_id` from context only; RLS on all seven tables; cross-tenant
customer/order/shipment/quote/claim references rejected; per-tenant unique
quote, invoice, and settlement numbers; over-balance payment, void-of-paid, and
over-claim/settlement approval & payout gated to **ADMIN**; write =
ADMIN/MANAGER; read adds CLIENT/DRIVER; optimistic locking via `version`.

## 13. Migration summary

`0012_billing_settlements_domain` (down_revision `0011`, single head) —
additive: creates `quotes`, `invoices`, `invoice_lines`, `payments`,
`settlements`, `payouts`, `penalties` with named PK/FK/unique/check constraints,
soft-delete + audit + `version`, JSONB (`quotes.terms`), indexes, and RLS
policies. PG-specific operations guarded by `_is_postgres()`; reversible
(7 create / 7 drop). No existing table is modified.

## 14. Test summary

Ten suites (`test_billing_{model,events,repository,service,routes}.py`,
`test_{quote,invoice,settlement}_state_machine.py`,
`test_billing_{claims,order_shipment}_integration.py`), **92% coverage** of the
billing modules (events/model/policies 100%, repository 90%, schemas 92%,
billing_service 92%, settlement_service 93%, routes 91%). Full regression:
**1186 passed, 13 skipped**.

## 15. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| `quote_lines` omitted — quote totals are direct fields (no per-line quote breakdown). | LOW | "If needed" per the spec; invoice lines are fully modelled. Add later if itemized quotes are required. |
| Invoice `overdue` is set via an internal `mark_overdue` method, not a public route. | LOW | A scheduled sweep (ADR-003) reading `due_date` is the follow-up; the event + transition exist. |
| Claim adjustment is recorded as an invoice-level amount; no automatic invoice creation on `ClaimSettled`. | MEDIUM | `ClaimSettlementConsumed` is emitted; an automatic invoice-adjustment consumer is a follow-up. |
| Payout has no settle/fail lifecycle endpoint (created `pending`). | LOW | `PayoutStatus` supports paid/failed; a payout-confirmation flow is a follow-up. |
| No external accounting/ERP export yet. | MEDIUM | Events are the integration seam; an accounting projection is a future sprint. |
