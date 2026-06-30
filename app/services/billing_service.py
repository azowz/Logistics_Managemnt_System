"""Billing service — quotes, invoices + lines, payments, penalties (context #18,
Sprint 9).

Owns the unit of work and outbox emission for the `Quote` and `Invoice`
aggregates, their `InvoiceLine` / `Payment` children, and `Penalty` records.
Billing references Customer / Order / Shipment / Quote / Claim by id (validated
tenant-owned); those contexts do not own the billing lifecycle. No FastAPI;
failures are domain exceptions.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.billing_events import (
    CancellationFeeApplied,
    InvoiceCancelled,
    InvoiceCreated,
    InvoiceIssued,
    InvoiceOverdue,
    InvoicePaid,
    InvoicePartiallyPaid,
    InvoiceVoided,
    PaymentFailed,
    PaymentRecorded,
    PenaltyApplied,
    QuoteApproved,
    QuoteCancelled,
    QuoteCreated,
    QuoteExpired,
    QuoteIssued,
    QuoteRejected,
)
from app.models.billing import Invoice, InvoiceLine, Payment, Penalty, Quote
from app.models.enums import InvoiceStatus, PaymentStatus, PenaltyType, QuoteStatus
from app.repositories.billing_repository import (
    InvoiceLineRepository,
    InvoiceRepository,
    PaymentRepository,
    PenaltyRepository,
    QuoteRepository,
)
from app.repositories.customer_repository import CustomerRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.insurance_repository import ClaimRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.services.billing_policies import InvoiceStateMachine, QuoteStateMachine
from app.services.exceptions import ConflictError, NotFoundError, ValidationError

_CENTS = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _str(value) -> Optional[str]:
    return str(value) if value is not None else None


class BillingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._quotes = QuoteRepository(session)
        self._invoices = InvoiceRepository(session)
        self._lines = InvoiceLineRepository(session)
        self._payments = PaymentRepository(session)
        self._penalties = PenaltyRepository(session)
        self._customers = CustomerRepository(session)
        self._orders = OrderRepository(session)
        self._shipments = ShipmentRepository(session)
        self._claims = ClaimRepository(session)
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
    def _gen(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"

    # --- validation ops ---

    def validate_customer_reference(self, tenant_id, customer_id) -> None:
        if customer_id is not None:
            self._owned(self._customers.get_by_id(customer_id), tenant_id, "Customer", customer_id)

    def validate_order_reference(self, tenant_id, order_id) -> None:
        if order_id is not None:
            self._owned(self._orders.get_by_id(order_id), tenant_id, "Order", order_id)

    def validate_shipment_reference(self, tenant_id, shipment_id) -> None:
        if shipment_id is not None:
            self._owned(self._shipments.get_by_id(shipment_id), tenant_id, "Shipment", shipment_id)

    def validate_claim_reference(self, tenant_id, claim_id) -> None:
        if claim_id is not None:
            self._owned(self._claims.get_by_id(claim_id), tenant_id, "Claim", claim_id)

    def _validate_commercial_refs(self, tenant_id, data) -> None:
        self.validate_customer_reference(tenant_id, data.get("customer_id"))
        self.validate_order_reference(tenant_id, data.get("order_id"))
        self.validate_shipment_reference(tenant_id, data.get("shipment_id"))
        self.validate_claim_reference(tenant_id, data.get("claim_id"))

    # ===================== Quotes =====================

    def create_quote(self, *, quote_number: Optional[str] = None, **data) -> Quote:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_commercial_refs(tenant_id, data)
        number = quote_number or self._gen("QUO")
        if self._quotes.get_by_number(number, include_deleted=True):
            raise ConflictError(f"Quote number '{number}' already exists in this tenant.")
        subtotal = _money(data.pop("subtotal_amount", 0))
        tax = _money(data.pop("tax_amount", 0))
        discount = _money(data.pop("discount_amount", 0))
        data.pop("total_amount", None)
        data.pop("status", None)
        total = _money(subtotal + tax - discount)
        if total < 0:
            raise ValidationError("Quote total cannot be negative (discount exceeds subtotal + tax).")
        quote = self._quotes.create(
            tenant_id=tenant_id, quote_number=number, status=QuoteStatus.DRAFT,
            subtotal_amount=subtotal, tax_amount=tax, discount_amount=discount, total_amount=total,
            created_by=actor_id, updated_by=actor_id, **data,
        )
        self._session.flush()
        self._emit(
            QuoteCreated(quote_id=quote.id, tenant_id=tenant_id, quote_number=number,
                         status=quote.status.value, total_amount=_str(total)),
            aggregate_id=quote.id, aggregate_type="Quote", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(quote)
        return quote

    def _quote_transition(self, quote_id, new_status, *, mutate=None, extra_events=None) -> Quote:
        self._tenant_id()
        actor_id = self._actor_id()
        quote = self._quotes.get_by_id_or_raise(quote_id)
        if quote.is_deleted:
            raise NotFoundError(f"Quote {quote_id} not found (deleted).")
        previous = quote.status
        if new_status == previous:
            return quote
        QuoteStateMachine.validate_transition(previous, new_status)
        if mutate is not None:
            mutate(quote)
        quote.status = new_status
        quote.updated_by = actor_id
        self._session.flush()
        for factory in extra_events or []:
            self._emit(factory(quote, previous), aggregate_id=quote.id, aggregate_type="Quote",
                       tenant_id=quote.tenant_id)
        self._session.commit()
        self._session.refresh(quote)
        return quote

    def issue_quote(self, quote_id):
        def _m(q: Quote):
            q.issued_at = utcnow()
        return self._quote_transition(
            quote_id, QuoteStatus.ISSUED, mutate=_m,
            extra_events=[lambda q, prev: QuoteIssued(quote_id=q.id, tenant_id=q.tenant_id, previous_status=prev.value)],
        )

    def approve_quote(self, quote_id):
        quote = self._quotes.get_by_id_or_raise(quote_id)
        if not quote.is_deleted and quote.valid_until is not None and _aware(quote.valid_until) < utcnow():
            raise ValidationError("Quote has passed its valid_until date and cannot be approved (expire it instead).")

        def _m(q: Quote):
            q.approved_at = utcnow()
        return self._quote_transition(
            quote_id, QuoteStatus.APPROVED, mutate=_m,
            extra_events=[lambda q, prev: QuoteApproved(quote_id=q.id, tenant_id=q.tenant_id, previous_status=prev.value)],
        )

    def reject_quote(self, quote_id, *, reason=None):
        def _m(q: Quote):
            q.rejected_at = utcnow()
        return self._quote_transition(
            quote_id, QuoteStatus.REJECTED, mutate=_m,
            extra_events=[lambda q, prev: QuoteRejected(quote_id=q.id, tenant_id=q.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def expire_quote(self, quote_id):
        def _m(q: Quote):
            q.expired_at = utcnow()
        return self._quote_transition(
            quote_id, QuoteStatus.EXPIRED, mutate=_m,
            extra_events=[lambda q, prev: QuoteExpired(quote_id=q.id, tenant_id=q.tenant_id, previous_status=prev.value)],
        )

    def cancel_quote(self, quote_id, *, reason=None):
        def _m(q: Quote):
            q.cancelled_at = utcnow()
        return self._quote_transition(
            quote_id, QuoteStatus.CANCELLED, mutate=_m,
            extra_events=[lambda q, prev: QuoteCancelled(quote_id=q.id, tenant_id=q.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def get_quote(self, quote_id, *, include_deleted=False) -> Quote:
        quote = self._quotes.get_by_id(quote_id)
        if quote is None or (quote.is_deleted and not include_deleted):
            raise NotFoundError(f"Quote {quote_id} not found.")
        return quote

    def update_quote(self, quote_id, **data) -> Quote:
        self._tenant_id()
        actor_id = self._actor_id()
        quote = self._quotes.get_by_id_or_raise(quote_id)
        if quote.is_deleted:
            raise NotFoundError(f"Quote {quote_id} not found (deleted).")
        if QuoteStateMachine.is_terminal(quote.status):
            raise ValidationError(f"Quote {quote_id} is terminal and cannot be edited.")
        for key in ("subtotal_amount", "tax_amount", "discount_amount"):
            if data.get(key) is not None:
                data[key] = _money(data[key])
        data["updated_by"] = actor_id
        self._quotes.update(quote, **data)
        quote.total_amount = _money(quote.subtotal_amount + quote.tax_amount - quote.discount_amount)
        self._session.commit()
        self._session.refresh(quote)
        return quote

    def list_quotes(self, params) -> Page[Quote]:
        items, total = self._quotes.list_quotes(
            q=params.q, status=params.status, customer_id=params.customer_id, order_id=params.order_id,
            shipment_id=params.shipment_id, include_deleted=params.include_deleted,
            sort_by=params.sort_by, sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    # ===================== Invoices =====================

    def _line_amounts(self, line: dict):
        qty = _money(line.get("quantity", 1))
        unit = _money(line.get("unit_price", 0))
        disc = _money(line.get("discount_amount", 0))
        rate = Decimal(str(line.get("tax_rate", 0) or 0))
        net = _money(qty * unit - disc)
        if net < 0:
            net = Decimal("0.00")
        tax = _money(net * rate / Decimal("100"))
        return net, tax, _money(net + tax)

    def calculate_invoice_totals(self, invoice: Invoice) -> None:
        """Recompute subtotal/tax/discount/total from the invoice's lines + adjustments."""
        lines = self._lines.list_lines_for_invoice(invoice.id)
        subtotal = Decimal("0.00")
        tax = Decimal("0.00")
        discount = Decimal("0.00")
        for ln in lines:
            net, ln_tax, _ = self._line_amounts({
                "quantity": ln.quantity, "unit_price": ln.unit_price,
                "discount_amount": ln.discount_amount, "tax_rate": ln.tax_rate,
            })
            subtotal += net
            tax += ln_tax
            discount += _money(ln.discount_amount)
        invoice.subtotal_amount = _money(subtotal)
        invoice.tax_amount = _money(tax)
        invoice.discount_amount = _money(discount)
        invoice.total_amount = _money(
            subtotal + tax + _money(invoice.penalty_amount) - _money(invoice.claim_adjustment_amount)
        )
        if invoice.total_amount < 0:
            invoice.total_amount = Decimal("0.00")

    def calculate_invoice_balance(self, invoice: Invoice) -> Decimal:
        return _money(self._invoices.get_invoice_balance(invoice))

    def create_invoice(self, *, invoice_number: Optional[str] = None, lines: Optional[List[dict]] = None, **data) -> Invoice:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_commercial_refs(tenant_id, data)
        if data.get("quote_id") is not None:
            quote = self._owned(self._quotes.get_by_id(data["quote_id"]), tenant_id, "Quote", data["quote_id"])
            if quote.status == QuoteStatus.EXPIRED:
                raise ValidationError("An expired quote cannot be converted to an invoice.")
        number = invoice_number or self._gen("INV")
        if self._invoices.get_by_number(number, include_deleted=True):
            raise ConflictError(f"Invoice number '{number}' already exists in this tenant.")
        data.pop("status", None)
        invoice = self._invoices.create(
            tenant_id=tenant_id, invoice_number=number, status=InvoiceStatus.DRAFT,
            created_by=actor_id, updated_by=actor_id, **data,
        )
        self._session.flush()
        for ln in lines or []:
            _, _, line_total = self._line_amounts(ln)
            self._lines.create(tenant_id=tenant_id, invoice_id=invoice.id, line_total=line_total, **ln)
        self._session.flush()
        self.calculate_invoice_totals(invoice)
        self._session.flush()
        self._emit(
            InvoiceCreated(invoice_id=invoice.id, tenant_id=tenant_id, invoice_number=number,
                           status=invoice.status.value, total_amount=_str(invoice.total_amount)),
            aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(invoice)
        return invoice

    def get_invoice(self, invoice_id, *, include_deleted=False) -> Invoice:
        invoice = self._invoices.get_by_id(invoice_id)
        if invoice is None or (invoice.is_deleted and not include_deleted):
            raise NotFoundError(f"Invoice {invoice_id} not found.")
        return invoice

    def list_invoice_lines(self, invoice_id) -> List[InvoiceLine]:
        self.get_invoice(invoice_id)
        return self._lines.list_lines_for_invoice(invoice_id)

    def list_payments(self, invoice_id) -> List[Payment]:
        self.get_invoice(invoice_id)
        return self._payments.list_payments_for_invoice(invoice_id)

    def update_invoice(self, invoice_id, **data) -> Invoice:
        self._tenant_id()
        actor_id = self._actor_id()
        invoice = self._invoices.get_by_id_or_raise(invoice_id)
        if invoice.is_deleted:
            raise NotFoundError(f"Invoice {invoice_id} not found (deleted).")
        if invoice.status != InvoiceStatus.DRAFT:
            raise ValidationError("Only draft invoices can be edited.")
        data["updated_by"] = actor_id
        self._invoices.update(invoice, **data)
        self._session.commit()
        self._session.refresh(invoice)
        return invoice

    def issue_invoice(self, invoice_id):
        self._tenant_id()
        actor_id = self._actor_id()
        invoice = self._invoices.get_by_id_or_raise(invoice_id)
        if invoice.is_deleted:
            raise NotFoundError(f"Invoice {invoice_id} not found (deleted).")
        self.calculate_invoice_totals(invoice)
        if _money(invoice.total_amount) <= 0 and not invoice.is_credit_note:
            raise ValidationError("An invoice must have a positive total to be issued (unless it is a credit note).")
        if invoice.due_date is not None and invoice.issued_at is None and _aware(invoice.due_date) < utcnow():
            raise ValidationError("due_date cannot be in the past at issue time.")
        previous = invoice.status
        InvoiceStateMachine.validate_transition(previous, InvoiceStatus.ISSUED)
        invoice.status = InvoiceStatus.ISSUED
        invoice.issued_at = utcnow()
        invoice.updated_by = actor_id
        self._session.flush()
        self._emit(
            InvoiceIssued(invoice_id=invoice.id, tenant_id=invoice.tenant_id, previous_status=previous.value,
                          total_amount=_str(invoice.total_amount)),
            aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=invoice.tenant_id,
        )
        self._session.commit()
        self._session.refresh(invoice)
        return invoice

    def validate_payment(self, invoice: Invoice, amount: Decimal, currency_code: str, *,
                         allow_override=False, check_balance=True) -> None:
        """Validate a payment against an invoice.

        Currency-match and invoice-status guards apply to **every** payment,
        confirmed or pending. Only the confirmed-balance (over-payment) check is
        gated behind ``check_balance`` so a pending payment can be staged without
        being capped by the live balance — but never in the wrong currency nor
        against a draft/voided/cancelled/paid invoice.
        """
        if invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.VOIDED, InvoiceStatus.CANCELLED, InvoiceStatus.PAID):
            raise ValidationError(f"Cannot record a payment against a '{invoice.status.value}' invoice.")
        if _money(amount) <= 0:
            raise ValidationError("Payment amount must be positive.")
        if currency_code is not None and currency_code.upper() != (invoice.currency_code or "").upper():
            raise ValidationError("Payment currency must match the invoice currency.")
        if check_balance:
            balance = self.calculate_invoice_balance(invoice)
            if not allow_override and _money(amount) > balance:
                raise ValidationError(
                    f"Payment amount {amount} exceeds the remaining balance {balance} (override required)."
                )

    def record_payment(self, invoice_id, *, amount, method, currency_code=None, payment_reference=None,
                       notes=None, confirm=True, allow_override=False) -> Payment:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        invoice = self._invoices.get_by_id_or_raise(invoice_id)
        if invoice.is_deleted:
            raise NotFoundError(f"Invoice {invoice_id} not found (deleted).")
        currency = (currency_code or invoice.currency_code)
        # Currency + invoice-status guards apply to every payment; the balance
        # (over-payment) check is only meaningful for a confirmed payment.
        self.validate_payment(invoice, amount, currency, allow_override=allow_override, check_balance=confirm)
        status = PaymentStatus.CONFIRMED if confirm else PaymentStatus.PENDING
        payment = self._payments.create(
            tenant_id=tenant_id, invoice_id=invoice.id, amount=_money(amount), currency_code=currency.upper(),
            method=method, status=status, paid_at=utcnow() if confirm else None, received_by=actor_id,
            payment_reference=payment_reference, notes=notes, created_by=actor_id, updated_by=actor_id,
        )
        self._session.flush()
        self._emit(
            PaymentRecorded(payment_id=payment.id, tenant_id=tenant_id, invoice_id=invoice.id,
                            amount=_str(_money(amount)), method=payment.method.value if hasattr(payment.method, "value") else str(payment.method)),
            aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=tenant_id,
        )
        if confirm:
            self._recompute_invoice_payment_status(invoice)
        self._session.commit()
        self._session.refresh(payment)
        return payment

    def _recompute_invoice_payment_status(self, invoice: Invoice) -> None:
        """After a confirmed payment, advance the invoice toward partially_paid / paid."""
        balance = self.calculate_invoice_balance(invoice)
        previous = invoice.status
        target = InvoiceStatus.PAID if balance <= 0 else InvoiceStatus.PARTIALLY_PAID
        if target == previous:
            return
        if not InvoiceStateMachine.can_transition(previous, target):
            return
        invoice.status = target
        if target == InvoiceStatus.PAID:
            invoice.paid_at = utcnow()
            event = InvoicePaid(invoice_id=invoice.id, tenant_id=invoice.tenant_id, previous_status=previous.value)
        else:
            event = InvoicePartiallyPaid(invoice_id=invoice.id, tenant_id=invoice.tenant_id,
                                         previous_status=previous.value, balance=_str(balance))
        self._session.flush()
        self._emit(event, aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=invoice.tenant_id)

    def mark_payment_failed(self, payment_id, *, reason=None) -> Payment:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        payment = self._payments.get_by_id_or_raise(payment_id)
        if payment.is_deleted:
            raise NotFoundError(f"Payment {payment_id} not found (deleted).")
        if payment.status != PaymentStatus.PENDING:
            raise ValidationError(f"Only pending payments can be marked failed (was '{payment.status.value}').")
        payment.status = PaymentStatus.FAILED
        payment.updated_by = actor_id
        self._session.flush()
        self._emit(
            PaymentFailed(payment_id=payment.id, tenant_id=tenant_id, invoice_id=payment.invoice_id, reason=reason),
            aggregate_id=payment.invoice_id, aggregate_type="Invoice", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(payment)
        return payment

    def void_invoice(self, invoice_id, *, reason=None, allow_override=False):
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        invoice = self._invoices.get_by_id_or_raise(invoice_id)
        if invoice.is_deleted:
            raise NotFoundError(f"Invoice {invoice_id} not found (deleted).")
        previous = invoice.status
        if previous == InvoiceStatus.PAID:
            if not allow_override:
                raise ValidationError("A paid invoice cannot be voided without an authorized override.")
        elif not InvoiceStateMachine.can_transition(previous, InvoiceStatus.VOIDED):
            InvoiceStateMachine.validate_transition(previous, InvoiceStatus.VOIDED)
        invoice.status = InvoiceStatus.VOIDED
        invoice.voided_at = utcnow()
        invoice.updated_by = actor_id
        self._session.flush()
        self._emit(
            InvoiceVoided(invoice_id=invoice.id, tenant_id=tenant_id, previous_status=previous.value, reason=reason),
            aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(invoice)
        return invoice

    def cancel_invoice(self, invoice_id, *, reason=None):
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        invoice = self._invoices.get_by_id_or_raise(invoice_id)
        if invoice.is_deleted:
            raise NotFoundError(f"Invoice {invoice_id} not found (deleted).")
        previous = invoice.status
        InvoiceStateMachine.validate_transition(previous, InvoiceStatus.CANCELLED)
        invoice.status = InvoiceStatus.CANCELLED
        invoice.cancelled_at = utcnow()
        invoice.updated_by = actor_id
        self._session.flush()
        self._emit(
            InvoiceCancelled(invoice_id=invoice.id, tenant_id=tenant_id, previous_status=previous.value, reason=reason),
            aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(invoice)
        return invoice

    def mark_overdue(self, invoice_id):
        """Advance an unpaid/partially-paid invoice to overdue (for a future scheduled sweep)."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        invoice = self._invoices.get_by_id_or_raise(invoice_id)
        if invoice.is_deleted:
            raise NotFoundError(f"Invoice {invoice_id} not found (deleted).")
        previous = invoice.status
        if previous == InvoiceStatus.OVERDUE:
            return invoice
        InvoiceStateMachine.validate_transition(previous, InvoiceStatus.OVERDUE)
        invoice.status = InvoiceStatus.OVERDUE
        invoice.updated_by = actor_id
        self._session.flush()
        self._emit(
            InvoiceOverdue(invoice_id=invoice.id, tenant_id=tenant_id, previous_status=previous.value),
            aggregate_id=invoice.id, aggregate_type="Invoice", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(invoice)
        return invoice

    def list_invoices(self, params) -> Page[Invoice]:
        items, total = self._invoices.list_invoices(
            q=params.q, status=params.status, customer_id=params.customer_id, order_id=params.order_id,
            shipment_id=params.shipment_id, claim_id=params.claim_id, include_deleted=params.include_deleted,
            sort_by=params.sort_by, sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    search_invoices = list_invoices

    # ===================== Penalties / cancellation fees =====================

    def apply_penalty(self, *, penalty_type, amount, order_id=None, shipment_id=None, invoice_id=None,
                     reason=None, currency_code="SAR") -> Penalty:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        if _money(amount) < 0:
            raise ValidationError("Penalty amount must be non-negative.")
        self.validate_order_reference(tenant_id, order_id)
        self.validate_shipment_reference(tenant_id, shipment_id)
        invoice = None
        if invoice_id is not None:
            invoice = self._owned(self._invoices.get_by_id(invoice_id), tenant_id, "Invoice", invoice_id)
        penalty = self._penalties.create(
            tenant_id=tenant_id, penalty_type=penalty_type, amount=_money(amount), currency_code=currency_code.upper(),
            order_id=order_id, shipment_id=shipment_id, invoice_id=invoice_id, reason=reason,
            applied_at=utcnow(), created_by=actor_id, updated_by=actor_id,
        )
        self._session.flush()
        if invoice is not None and not InvoiceStateMachine.is_terminal(invoice.status):
            invoice.penalty_amount = _money(invoice.penalty_amount) + _money(amount)
            self.calculate_invoice_totals(invoice)
            self._session.flush()
        self._emit(
            PenaltyApplied(penalty_id=penalty.id, tenant_id=tenant_id,
                           penalty_type=penalty.penalty_type.value if hasattr(penalty.penalty_type, "value") else str(penalty.penalty_type),
                           amount=_str(_money(amount)), order_id=order_id, shipment_id=shipment_id, invoice_id=invoice_id),
            aggregate_id=penalty.id, aggregate_type="Penalty", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(penalty)
        return penalty

    def apply_cancellation_fee(self, *, amount, order_id=None, shipment_id=None, invoice_id=None,
                              reason=None, currency_code="SAR") -> Penalty:
        if order_id is None and shipment_id is None:
            raise ValidationError("A cancellation fee must be linked to an order or a shipment.")
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        if _money(amount) < 0:
            raise ValidationError("Cancellation fee must be non-negative.")
        self.validate_order_reference(tenant_id, order_id)
        self.validate_shipment_reference(tenant_id, shipment_id)
        invoice = None
        if invoice_id is not None:
            invoice = self._owned(self._invoices.get_by_id(invoice_id), tenant_id, "Invoice", invoice_id)
        penalty = self._penalties.create(
            tenant_id=tenant_id, penalty_type=PenaltyType.CANCELLATION_FEE, amount=_money(amount),
            currency_code=currency_code.upper(), order_id=order_id, shipment_id=shipment_id, invoice_id=invoice_id,
            reason=reason, applied_at=utcnow(), created_by=actor_id, updated_by=actor_id,
        )
        self._session.flush()
        if invoice is not None and not InvoiceStateMachine.is_terminal(invoice.status):
            invoice.penalty_amount = _money(invoice.penalty_amount) + _money(amount)
            self.calculate_invoice_totals(invoice)
            self._session.flush()
        self._emit(
            CancellationFeeApplied(penalty_id=penalty.id, tenant_id=tenant_id, amount=_str(_money(amount)),
                                   order_id=order_id, shipment_id=shipment_id),
            aggregate_id=penalty.id, aggregate_type="Penalty", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(penalty)
        return penalty

    def list_penalties(self, params) -> Page[Penalty]:
        items, total = self._penalties.list_penalties(
            penalty_type=params.penalty_type, order_id=params.order_id, shipment_id=params.shipment_id,
            invoice_id=params.invoice_id, include_deleted=params.include_deleted,
            sort_by=params.sort_by, sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))


def _aware(dt):
    """Treat naive datetimes (SQLite) as UTC for safe comparison with utcnow()."""
    from datetime import timezone

    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
