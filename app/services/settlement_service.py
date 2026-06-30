"""Settlement service — settlements, payouts, claim-settlement consumption
(context #18, Sprint 9).

Owns the unit of work and outbox emission for the `Settlement` aggregate and its
`Payout` children. Billing **consumes** approved/settled claim outcomes (Sprint 8)
to create settlement records; the Claims context retains ownership of the claim
lifecycle. A read-only :class:`ClaimRepository` is used for validation — there is
no dependency on `ClaimsService`, so no circular dependency is introduced.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.billing_events import (
    ClaimSettlementConsumed,
    PayoutCreated,
    SettlementApproved,
    SettlementCancelled,
    SettlementCreated,
    SettlementSettled,
    SettlementSubmittedForApproval,
)
from app.events.envelope import EventEnvelope
from app.models.billing import Payout, Settlement
from app.models.enums import ClaimStatus, InvoiceStatus, PayoutStatus, SettlementStatus, SettlementType
from app.repositories.billing_repository import (
    InvoiceRepository,
    PayoutRepository,
    SettlementRepository,
)
from app.repositories.customer_repository import CustomerRepository
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.insurance_repository import ClaimRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.services.billing_policies import SettlementStateMachine
from app.services.exceptions import ConflictError, NotFoundError, ValidationError

_CENTS = Decimal("0.01")

# Settlement types that draw against a claim's approved amount.
_CLAIM_BACKED = frozenset({SettlementType.CLAIM_PAYOUT, SettlementType.CLAIM_OFFSET})


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _str(value) -> Optional[str]:
    return str(value) if value is not None else None


class SettlementService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._settlements = SettlementRepository(session)
        self._payouts = PayoutRepository(session)
        self._invoices = InvoiceRepository(session)
        self._claims = ClaimRepository(session)
        self._customers = CustomerRepository(session)
        self._equipment = EquipmentRepository(session)
        self._shipments = ShipmentRepository(session)
        self._event_repo = EventStoreRepository(session)

    # --- context helpers ---

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self):
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id, aggregate_type, tenant_id):
        nv = self._event_repo.next_aggregate_version(aggregate_id)
        env = EventEnvelope.create(event, tenant_id=tenant_id, aggregate_id=aggregate_id,
                                   aggregate_version=nv, aggregate_type=aggregate_type, user_id=self._actor_id())
        self._event_repo.append(env)

    def _owned(self, obj, tenant_id, label, ident):
        if obj is None or getattr(obj, "is_deleted", False) or getattr(obj, "tenant_id", None) != tenant_id:
            raise ValidationError(f"{label} {ident} does not exist in this tenant.")
        return obj

    @staticmethod
    def _gen() -> str:
        return f"STL-{uuid.uuid4().hex[:12].upper()}"

    # --- validation ops ---

    def validate_settlement_amount(self, *, claim_id, settlement_type, amount, tenant_id, allow_override=False):
        """A claim-backed settlement must reference an approved/settled claim and
        must not exceed its approved amount unless an authorized override is set."""
        if claim_id is None:
            return
        claim = self._owned(self._claims.get_by_id(claim_id), tenant_id, "Claim", claim_id)
        if settlement_type in _CLAIM_BACKED:
            if claim.status not in (ClaimStatus.APPROVED, ClaimStatus.SETTLED):
                raise ValidationError(
                    f"Claim {claim_id} is '{claim.status.value}'; a claim settlement requires an "
                    "approved or settled claim."
                )
            approved = claim.approved_amount
            if approved is not None and not allow_override and _money(amount) > _money(approved):
                raise ValidationError(
                    f"Settlement amount {_money(amount)} exceeds the approved claim amount "
                    f"{_money(approved)} (override required)."
                )

    def _validate_refs(self, tenant_id, data) -> None:
        if data.get("invoice_id") is not None:
            self._owned(self._invoices.get_by_id(data["invoice_id"]), tenant_id, "Invoice", data["invoice_id"])
        if data.get("customer_id") is not None:
            self._owned(self._customers.get_by_id(data["customer_id"]), tenant_id, "Customer", data["customer_id"])
        if data.get("equipment_id") is not None:
            self._owned(self._equipment.get_by_id(data["equipment_id"]), tenant_id, "Equipment", data["equipment_id"])
        if data.get("shipment_id") is not None:
            self._owned(self._shipments.get_by_id(data["shipment_id"]), tenant_id, "Shipment", data["shipment_id"])

    # ===================== Settlements =====================

    def create_settlement(self, *, settlement_number: Optional[str] = None, allow_override=False, **data) -> Settlement:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_refs(tenant_id, data)
        self.validate_settlement_amount(
            claim_id=data.get("claim_id"), settlement_type=data["settlement_type"],
            amount=data.get("amount", 0), tenant_id=tenant_id, allow_override=allow_override,
        )
        number = settlement_number or self._gen()
        if self._settlements.get_by_number(number, include_deleted=True):
            raise ConflictError(f"Settlement number '{number}' already exists in this tenant.")
        data.pop("status", None)
        if "amount" in data:
            data["amount"] = _money(data["amount"])
        settlement = self._settlements.create(
            tenant_id=tenant_id, settlement_number=number, status=SettlementStatus.DRAFT,
            created_by=actor_id, updated_by=actor_id, **data,
        )
        self._session.flush()
        self._emit(
            SettlementCreated(settlement_id=settlement.id, tenant_id=tenant_id, settlement_number=number,
                              settlement_type=settlement.settlement_type.value, status=settlement.status.value,
                              amount=_str(settlement.amount), claim_id=settlement.claim_id),
            aggregate_id=settlement.id, aggregate_type="Settlement", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(settlement)
        return settlement

    def consume_claim_settlement(self, *, claim_id, amount, settlement_type=SettlementType.CLAIM_PAYOUT,
                                 invoice_id=None, allow_override=False, notes=None) -> Settlement:
        """Create a settlement that consumes an approved claim outcome.

        Validates the claim is approved/settled and the amount is bounded, then
        creates the settlement and emits ``ClaimSettlementConsumed``. The claim's
        own lifecycle is left untouched.
        """
        if claim_id is None:
            raise ValidationError("consume_claim_settlement requires a claim_id.")
        settlement = self.create_settlement(
            claim_id=claim_id, amount=amount, settlement_type=settlement_type,
            invoice_id=invoice_id, notes=notes, allow_override=allow_override,
        )
        adjustment = None
        if invoice_id is not None:
            adjustment = self._apply_invoice_claim_adjustment(invoice_id, settlement.amount)
        self._emit(
            ClaimSettlementConsumed(
                settlement_id=settlement.id, tenant_id=settlement.tenant_id, claim_id=claim_id,
                invoice_id=invoice_id, amount=_str(settlement.amount),
                adjustment_amount=_str(adjustment) if adjustment is not None else None,
                currency_code=settlement.currency_code,
            ),
            aggregate_id=settlement.id, aggregate_type="Settlement", tenant_id=settlement.tenant_id,
        )
        self._session.commit()
        self._session.refresh(settlement)
        return settlement

    def _apply_invoice_claim_adjustment(self, invoice_id, amount):
        """Increment an invoice's claim_adjustment_amount and recompute its total.

        A claim settlement consumed against an invoice reduces the amount owed by
        the customer. Only an open invoice may be adjusted — a paid, voided, or
        cancelled invoice is finalized.
        """
        tenant_id = self._tenant_id()
        invoice = self._owned(self._invoices.get_by_id(invoice_id), tenant_id, "Invoice", invoice_id)
        if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.VOIDED, InvoiceStatus.CANCELLED):
            raise ValidationError(
                f"Cannot apply a claim adjustment to a '{invoice.status.value}' invoice."
            )
        invoice.claim_adjustment_amount = _money(invoice.claim_adjustment_amount) + _money(amount)
        total = (
            _money(invoice.subtotal_amount) + _money(invoice.tax_amount)
            + _money(invoice.penalty_amount) - _money(invoice.claim_adjustment_amount)
        )
        invoice.total_amount = _money(total) if total > 0 else Decimal("0.00")
        invoice.updated_by = self._actor_id()
        self._session.flush()
        return _money(amount)

    def _transition(self, settlement_id, new_status, *, mutate=None, extra_events=None) -> Settlement:
        self._tenant_id()
        actor_id = self._actor_id()
        settlement = self._settlements.get_by_id_or_raise(settlement_id)
        if settlement.is_deleted:
            raise NotFoundError(f"Settlement {settlement_id} not found (deleted).")
        previous = settlement.status
        if new_status == previous:
            return settlement
        SettlementStateMachine.validate_transition(previous, new_status)
        if mutate is not None:
            mutate(settlement)
        settlement.status = new_status
        settlement.updated_by = actor_id
        self._session.flush()
        for factory in extra_events or []:
            self._emit(factory(settlement, previous), aggregate_id=settlement.id,
                       aggregate_type="Settlement", tenant_id=settlement.tenant_id)
        self._session.commit()
        self._session.refresh(settlement)
        return settlement

    def submit_settlement_for_approval(self, settlement_id):
        return self._transition(
            settlement_id, SettlementStatus.PENDING_APPROVAL,
            extra_events=[lambda s, prev: SettlementSubmittedForApproval(
                settlement_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value)],
        )

    def approve_settlement(self, settlement_id):
        def _m(s: Settlement):
            s.approved_at = utcnow()
        return self._transition(
            settlement_id, SettlementStatus.APPROVED, mutate=_m,
            extra_events=[lambda s, prev: SettlementApproved(
                settlement_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value)],
        )

    def settle_settlement(self, settlement_id):
        def _m(s: Settlement):
            s.settled_at = utcnow()
        settlement = self._transition(
            settlement_id, SettlementStatus.SETTLED, mutate=_m,
            extra_events=[lambda s, prev: SettlementSettled(
                settlement_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value, amount=_str(s.amount),
                currency_code=s.currency_code)],
        )
        return settlement

    def cancel_settlement(self, settlement_id, *, reason=None):
        def _m(s: Settlement):
            s.cancelled_at = utcnow()
        return self._transition(
            settlement_id, SettlementStatus.CANCELLED, mutate=_m,
            extra_events=[lambda s, prev: SettlementCancelled(
                settlement_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def get_settlement(self, settlement_id, *, include_deleted=False) -> Settlement:
        settlement = self._settlements.get_by_id(settlement_id)
        if settlement is None or (settlement.is_deleted and not include_deleted):
            raise NotFoundError(f"Settlement {settlement_id} not found.")
        return settlement

    def update_settlement(self, settlement_id, **data) -> Settlement:
        self._tenant_id()
        actor_id = self._actor_id()
        settlement = self._settlements.get_by_id_or_raise(settlement_id)
        if settlement.is_deleted:
            raise NotFoundError(f"Settlement {settlement_id} not found (deleted).")
        if settlement.status not in (SettlementStatus.DRAFT, SettlementStatus.PENDING_APPROVAL):
            raise ValidationError("Only draft or pending settlements can be edited.")
        if data.get("amount") is not None:
            data["amount"] = _money(data["amount"])
        data["updated_by"] = actor_id
        self._settlements.update(settlement, **data)
        self._session.commit()
        self._session.refresh(settlement)
        return settlement

    def list_settlements(self, params) -> Page[Settlement]:
        items, total = self._settlements.list_settlements(
            q=params.q, status=params.status, settlement_type=params.settlement_type,
            claim_id=params.claim_id, customer_id=params.customer_id, include_deleted=params.include_deleted,
            sort_by=params.sort_by, sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    search_settlements = list_settlements

    # ===================== Payouts =====================

    def create_payout(self, settlement_id, *, amount, method, payout_reference=None, notes=None) -> Payout:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        settlement = self._settlements.get_by_id(settlement_id)
        if settlement is None or settlement.is_deleted or settlement.tenant_id != tenant_id:
            raise NotFoundError(f"Settlement {settlement_id} not found.")
        if settlement.status not in (SettlementStatus.APPROVED, SettlementStatus.SETTLED):
            raise ValidationError("A payout can only be created for an approved or settled settlement.")
        if _money(amount) < 0:
            raise ValidationError("Payout amount must be non-negative.")
        payout = self._payouts.create(
            tenant_id=tenant_id, settlement_id=settlement.id, amount=_money(amount),
            currency_code=settlement.currency_code, method=method, status=PayoutStatus.PENDING,
            payout_reference=payout_reference, notes=notes, created_by=actor_id, updated_by=actor_id,
        )
        self._session.flush()
        self._emit(
            PayoutCreated(payout_id=payout.id, tenant_id=tenant_id, settlement_id=settlement.id,
                          amount=_str(_money(amount)),
                          method=payout.method.value if hasattr(payout.method, "value") else str(payout.method)),
            aggregate_id=settlement.id, aggregate_type="Settlement", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(payout)
        return payout

    def list_payouts(self, settlement_id) -> List[Payout]:
        self.get_settlement(settlement_id)
        return self._payouts.list_payouts_for_settlement(settlement_id)
