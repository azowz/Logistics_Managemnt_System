"""Service tests for BillingService & SettlementService (SQLite + patched ctx).

Exercises the real Unit of Work against an in-memory SQLite database; the
transactional-outbox EventStoreRepository is stubbed so tests focus on
aggregate behaviour and business rules.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Iterator
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import (
    InvoiceStatus,
    PaymentMethod,
    PenaltyType,
    QuoteStatus,
    SettlementStatus,
    SettlementType,
)
from app.services.billing_service import BillingService
from app.services.exceptions import ConflictError, StatusTransitionError, ValidationError
from app.services.settlement_service import SettlementService
from billing_sqlite import (
    make_engine,
    seed_claim,
    seed_customer,
    seed_order,
    seed_tenant_user,
)

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_CUSTOMER = uuid.uuid4()
_ORDER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)
    seed_customer(_Session, tenant_id=_TENANT, customer_id=_CUSTOMER)
    seed_order(_Session, tenant_id=_TENANT, order_id=_ORDER, customer_id=_CUSTOMER)


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.billing_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.billing_service.get_current_user_id", return_value=_USER),
        patch("app.services.billing_service.EventStoreRepository", autospec=True) as MB,
        patch("app.services.settlement_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.settlement_service.get_current_user_id", return_value=_USER),
        patch("app.services.settlement_service.EventStoreRepository", autospec=True) as MS,
    ):
        for M in (MB, MS):
            M.return_value.next_aggregate_version.return_value = 1
            M.return_value.append.return_value = None
        yield


def _svc() -> BillingService:
    return BillingService(_Session())


def _ssvc() -> SettlementService:
    return SettlementService(_Session())


# ===================== Quotes =====================


def test_quote_lifecycle_and_total_computation():
    svc = _svc()
    q = svc.create_quote(customer_id=_CUSTOMER, subtotal_amount=Decimal("100"),
                         tax_amount=Decimal("15"), discount_amount=Decimal("5"))
    assert q.total_amount == Decimal("110.00")
    assert q.status == QuoteStatus.DRAFT
    q = svc.issue_quote(q.id)
    assert q.status == QuoteStatus.ISSUED and q.issued_at is not None
    q = svc.approve_quote(q.id)
    assert q.status == QuoteStatus.APPROVED


def test_quote_duplicate_number_conflict():
    svc = _svc()
    svc.create_quote(quote_number="QUO-DUP", subtotal_amount=Decimal("1"))
    with pytest.raises(ConflictError):
        svc.create_quote(quote_number="QUO-DUP")


def test_quote_invalid_transition():
    svc = _svc()
    q = svc.create_quote(subtotal_amount=Decimal("10"))
    with pytest.raises(StatusTransitionError):
        svc.approve_quote(q.id)  # draft -> approved is illegal


def test_quote_reject_and_expire():
    svc = _svc()
    q = svc.issue_quote(svc.create_quote(subtotal_amount=Decimal("10")).id)
    rejected = svc.reject_quote(q.id, reason="too expensive")
    assert rejected.status == QuoteStatus.REJECTED
    q2 = svc.issue_quote(svc.create_quote(subtotal_amount=Decimal("10")).id)
    assert svc.expire_quote(q2.id).status == QuoteStatus.EXPIRED


def test_quote_cross_tenant_customer_rejected():
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.create_quote(customer_id=uuid.uuid4())  # unknown customer


def test_quote_update_recomputes_total():
    svc = _svc()
    q = svc.create_quote(subtotal_amount=Decimal("100"))
    q = svc.update_quote(q.id, tax_amount=Decimal("20"))
    assert q.total_amount == Decimal("120.00")


# ===================== Invoices & payments =====================


def _make_issued_invoice(svc, total_lines=None):
    lines = total_lines or [{"line_type": "transport_fee", "quantity": Decimal("1"),
                             "unit_price": Decimal("100"), "tax_rate": Decimal("0"),
                             "discount_amount": Decimal("0")}]
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=lines)
    return svc.issue_invoice(inv.id)


def test_invoice_create_totals_and_issue():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=[
        {"line_type": "transport_fee", "quantity": Decimal("2"), "unit_price": Decimal("50"),
         "tax_rate": Decimal("10"), "discount_amount": Decimal("0")},
    ])
    # net = 100, tax = 10 -> total 110
    assert inv.subtotal_amount == Decimal("100.00")
    assert inv.tax_amount == Decimal("10.00")
    assert inv.total_amount == Decimal("110.00")
    inv = svc.issue_invoice(inv.id)
    assert inv.status == InvoiceStatus.ISSUED


def test_invoice_cannot_issue_zero_total():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=[])
    with pytest.raises(ValidationError):
        svc.issue_invoice(inv.id)


def test_credit_note_can_issue_zero_total():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, is_credit_note=True, lines=[])
    inv = svc.issue_invoice(inv.id)
    assert inv.status == InvoiceStatus.ISSUED


def test_full_payment_marks_paid():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    pay = svc.record_payment(inv.id, amount=Decimal("100"), method=PaymentMethod.CASH)
    assert pay.status.value == "confirmed" if hasattr(pay.status, "value") else pay.status == "confirmed"
    refreshed = svc.get_invoice(inv.id)
    assert refreshed.status == InvoiceStatus.PAID and refreshed.paid_at is not None


def test_partial_payment_marks_partially_paid():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    svc.record_payment(inv.id, amount=Decimal("40"), method=PaymentMethod.CASH)
    assert svc.get_invoice(inv.id).status == InvoiceStatus.PARTIALLY_PAID


def test_payment_currency_mismatch_rejected():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CASH, currency_code="USD")


def test_payment_exceeds_balance_requires_override():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("500"), method=PaymentMethod.CASH)
    pay = svc.record_payment(inv.id, amount=Decimal("500"), method=PaymentMethod.CASH, allow_override=True)
    assert pay is not None


def test_void_paid_invoice_requires_override():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    svc.record_payment(inv.id, amount=Decimal("100"), method=PaymentMethod.CASH)
    with pytest.raises(ValidationError):
        svc.void_invoice(inv.id)
    voided = svc.void_invoice(inv.id, allow_override=True, reason="error")
    assert voided.status == InvoiceStatus.VOIDED


def test_cancel_draft_invoice():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=[])
    assert svc.cancel_invoice(inv.id).status == InvoiceStatus.CANCELLED


def test_pending_payment_can_be_failed():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    pay = svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CARD, confirm=False)
    failed = svc.mark_payment_failed(pay.id, reason="declined")
    assert failed.status.value == "failed" if hasattr(failed.status, "value") else failed.status == "failed"
    # invoice stays issued (pending payment never advanced it)
    assert svc.get_invoice(inv.id).status == InvoiceStatus.ISSUED


def test_mark_overdue():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    assert svc.mark_overdue(inv.id).status == InvoiceStatus.OVERDUE


def test_expired_quote_cannot_become_invoice():
    svc = _svc()
    q = svc.issue_quote(svc.create_quote(subtotal_amount=Decimal("10")).id)
    q = svc.expire_quote(q.id)
    with pytest.raises(ValidationError):
        svc.create_invoice(customer_id=_CUSTOMER, quote_id=q.id, lines=[])


# ===================== Penalties =====================


def test_apply_penalty_to_invoice_bumps_total():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    before = svc.get_invoice(inv.id).total_amount
    svc.apply_penalty(penalty_type=PenaltyType.LATE_DELIVERY, amount=Decimal("25"), invoice_id=inv.id)
    after = svc.get_invoice(inv.id).total_amount
    assert after == before + Decimal("25.00")


def test_cancellation_fee_requires_order_or_shipment():
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.apply_cancellation_fee(amount=Decimal("10"))
    fee = svc.apply_cancellation_fee(amount=Decimal("10"), order_id=_ORDER)
    assert fee.penalty_type == PenaltyType.CANCELLATION_FEE


# ===================== Settlements =====================


def test_settlement_lifecycle():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    svc = _ssvc()
    stl = svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("800"))
    assert stl.status == SettlementStatus.DRAFT
    stl = svc.submit_settlement_for_approval(stl.id)
    assert stl.status == SettlementStatus.PENDING_APPROVAL
    stl = svc.approve_settlement(stl.id)
    assert stl.status == SettlementStatus.APPROVED and stl.approved_at is not None
    stl = svc.settle_settlement(stl.id)
    assert stl.status == SettlementStatus.SETTLED


def test_settlement_rejects_unapproved_claim():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="under_review", approved_amount=0)
    svc = _ssvc()
    with pytest.raises(ValidationError):
        svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("100"))


def test_settlement_amount_bounded_by_claim():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=500)
    svc = _ssvc()
    with pytest.raises(ValidationError):
        svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("900"))
    # override allows it
    stl = svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid,
                                amount=Decimal("900"), allow_override=True)
    assert stl.amount == Decimal("900.00")


def test_settlement_cross_tenant_claim_rejected():
    svc = _ssvc()
    with pytest.raises(ValidationError):
        svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=uuid.uuid4(), amount=Decimal("1"))


def test_cannot_settle_before_approval():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="settled", approved_amount=1000)
    svc = _ssvc()
    stl = svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("100"))
    with pytest.raises(StatusTransitionError):
        svc.settle_settlement(stl.id)


def test_consume_claim_settlement():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    svc = _ssvc()
    stl = svc.consume_claim_settlement(claim_id=cid, amount=Decimal("700"))
    assert stl.claim_id == cid and stl.amount == Decimal("700.00")


def test_payout_requires_approved_settlement():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    svc = _ssvc()
    stl = svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("300"))
    with pytest.raises(ValidationError):
        svc.create_payout(stl.id, amount=Decimal("300"), method=PaymentMethod.BANK_TRANSFER)
    svc.submit_settlement_for_approval(stl.id)
    svc.approve_settlement(stl.id)
    payout = svc.create_payout(stl.id, amount=Decimal("300"), method=PaymentMethod.BANK_TRANSFER)
    assert payout.amount == Decimal("300.00")
    assert len(svc.list_payouts(stl.id)) == 1


def test_settlement_cancel():
    svc = _ssvc()
    stl = svc.create_settlement(settlement_type=SettlementType.CUSTOMER_REFUND, customer_id=_CUSTOMER, amount=Decimal("50"))
    assert svc.cancel_settlement(stl.id, reason="dup").status == SettlementStatus.CANCELLED


# ===================== Targeted coverage =====================


def test_get_invoice_not_found():
    from app.services.exceptions import NotFoundError
    svc = _svc()
    with pytest.raises(NotFoundError):
        svc.get_invoice(uuid.uuid4())


def test_update_invoice_draft_only():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=[])
    updated = svc.update_invoice(inv.id, notes="hello")
    assert updated.notes == "hello"
    issued = _make_issued_invoice(svc)
    with pytest.raises(ValidationError):
        svc.update_invoice(issued.id, notes="nope")


def test_void_issued_invoice_without_override():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    voided = svc.void_invoice(inv.id, reason="mistake")
    assert voided.status == InvoiceStatus.VOIDED


def test_cancel_quote_and_terminal_edit_guard():
    svc = _svc()
    q = svc.issue_quote(svc.create_quote(subtotal_amount=Decimal("10")).id)
    q = svc.cancel_quote(q.id, reason="changed mind")
    assert q.status == QuoteStatus.CANCELLED
    with pytest.raises(ValidationError):
        svc.update_quote(q.id, notes="late edit")


def test_mark_payment_failed_on_confirmed_rejected():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    pay = svc.record_payment(inv.id, amount=Decimal("50"), method=PaymentMethod.CASH)
    with pytest.raises(ValidationError):
        svc.mark_payment_failed(pay.id)


def test_calculate_invoice_balance_helper():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    svc.record_payment(inv.id, amount=Decimal("30"), method=PaymentMethod.CASH)
    assert svc.calculate_invoice_balance(svc.get_invoice(inv.id)) == Decimal("70.00")


def test_cancellation_fee_linked_to_invoice_bumps_total():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    before = svc.get_invoice(inv.id).total_amount
    svc.apply_cancellation_fee(amount=Decimal("15"), order_id=_ORDER, invoice_id=inv.id)
    assert svc.get_invoice(inv.id).total_amount == before + Decimal("15.00")


def test_list_helpers_with_params():
    from app.schemas.billing import InvoiceListParams, PenaltyListParams, QuoteListParams
    svc = _svc()
    svc.create_quote(subtotal_amount=Decimal("1"))
    assert svc.list_quotes(QuoteListParams(page=1, size=5)).total >= 1
    assert svc.list_invoices(InvoiceListParams(page=1, size=5)).total >= 1
    svc.apply_penalty(penalty_type=PenaltyType.OTHER, amount=Decimal("1"))
    assert svc.list_penalties(PenaltyListParams(page=1, size=5)).total >= 1


def test_settlement_update_and_list():
    from app.schemas.billing import SettlementListParams
    svc = _ssvc()
    stl = svc.create_settlement(settlement_type=SettlementType.CARRIER_PAYOUT, amount=Decimal("10"))
    updated = svc.update_settlement(stl.id, amount=Decimal("20"))
    assert updated.amount == Decimal("20.00")
    assert svc.list_settlements(SettlementListParams(page=1, size=5)).total >= 1


def test_quote_total_negative_rejected():
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.create_quote(subtotal_amount=Decimal("10"), discount_amount=Decimal("50"))


def test_invoice_line_negative_net_clamped():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=[
        {"line_type": "discount", "quantity": Decimal("1"), "unit_price": Decimal("10"),
         "tax_rate": Decimal("0"), "discount_amount": Decimal("50")},
    ])
    # net clamped to 0 -> subtotal 0
    assert inv.subtotal_amount == Decimal("0.00")


# ===================== M1 — claim adjustment wiring =====================


def test_consume_claim_settlement_adjusts_invoice_total():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    bsvc = _svc()
    inv = bsvc.issue_invoice(bsvc.create_invoice(customer_id=_CUSTOMER, lines=[
        {"line_type": "transport_fee", "quantity": Decimal("1"), "unit_price": Decimal("500"),
         "tax_rate": Decimal("0"), "discount_amount": Decimal("0")}]).id)
    assert inv.total_amount == Decimal("500.00")
    ssvc = _ssvc()
    ssvc.consume_claim_settlement(claim_id=cid, amount=Decimal("200"), invoice_id=inv.id)
    refreshed = _svc().get_invoice(inv.id)
    assert refreshed.claim_adjustment_amount == Decimal("200.00")
    assert refreshed.total_amount == Decimal("300.00")  # 500 − 200


def test_claim_adjustment_increments_on_repeat():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    bsvc = _svc()
    inv = bsvc.issue_invoice(bsvc.create_invoice(customer_id=_CUSTOMER, lines=[
        {"line_type": "transport_fee", "quantity": Decimal("1"), "unit_price": Decimal("400"),
         "tax_rate": Decimal("0"), "discount_amount": Decimal("0")}]).id)
    ssvc = _ssvc()
    ssvc.consume_claim_settlement(claim_id=cid, amount=Decimal("100"), invoice_id=inv.id)
    ssvc.consume_claim_settlement(claim_id=cid, amount=Decimal("50"), invoice_id=inv.id)
    refreshed = _svc().get_invoice(inv.id)
    assert refreshed.claim_adjustment_amount == Decimal("150.00")
    assert refreshed.total_amount == Decimal("250.00")  # 400 − 150


def test_claim_adjustment_rejected_on_paid_invoice():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    bsvc = _svc()
    inv = _make_issued_invoice(bsvc)  # total 100
    bsvc.record_payment(inv.id, amount=Decimal("100"), method=PaymentMethod.CASH)  # -> paid
    ssvc = _ssvc()
    with pytest.raises(ValidationError):
        ssvc.consume_claim_settlement(claim_id=cid, amount=Decimal("10"), invoice_id=inv.id)


def test_consume_without_invoice_leaves_adjustment_none():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    stl = _ssvc().consume_claim_settlement(claim_id=cid, amount=Decimal("300"))
    assert stl.claim_id == cid and stl.amount == Decimal("300.00")


# ===================== M2 — pending payment validation =====================


def test_pending_payment_rejects_currency_mismatch():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CARD,
                           currency_code="USD", confirm=False)


def test_pending_payment_rejects_draft_invoice():
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, lines=[])
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CARD, confirm=False)


def test_pending_payment_rejects_cancelled_invoice():
    svc = _svc()
    inv = svc.cancel_invoice(svc.create_invoice(customer_id=_CUSTOMER, lines=[]).id)
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CARD, confirm=False)


def test_pending_payment_rejects_voided_invoice():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    svc.void_invoice(inv.id, reason="x")
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CARD, confirm=False)


def test_valid_pending_payment_allowed_without_balance_cap():
    svc = _svc()
    inv = _make_issued_invoice(svc)  # total 100
    # over-balance amount is allowed for a *pending* payment (balance check skipped)
    pay = svc.record_payment(inv.id, amount=Decimal("999"), method=PaymentMethod.CARD, confirm=False)
    assert (pay.status.value if hasattr(pay.status, "value") else pay.status) == "pending"
    # invoice is not advanced by a pending payment
    assert svc.get_invoice(inv.id).status == InvoiceStatus.ISSUED


def test_confirmed_payment_behaviour_unchanged():
    svc = _svc()
    inv = _make_issued_invoice(svc)
    # currency mismatch still rejected for confirmed
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("10"), method=PaymentMethod.CASH, currency_code="USD")
    # over-balance still rejected for confirmed
    with pytest.raises(ValidationError):
        svc.record_payment(inv.id, amount=Decimal("500"), method=PaymentMethod.CASH)
    # valid confirmed payment advances the invoice
    svc.record_payment(inv.id, amount=Decimal("100"), method=PaymentMethod.CASH)
    assert svc.get_invoice(inv.id).status == InvoiceStatus.PAID


# ===================== L3 — soft-deleted number reuse =====================


def test_soft_deleted_invoice_number_reuse_returns_conflict():
    from app.repositories.billing_repository import InvoiceRepository
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, invoice_number="INV-DUPDEL", lines=[])
    s = _Session()
    try:
        repo = InvoiceRepository(s)
        repo.soft_delete(repo.get_by_id(inv.id))
        s.commit()
    finally:
        s.close()
    with pytest.raises(ConflictError):
        svc.create_invoice(customer_id=_CUSTOMER, invoice_number="INV-DUPDEL", lines=[])


# --- Sprint 12: emit-site enrichment assertions ---------------------------


def test_invoice_issue_emits_currency_code():
    """InvoiceIssued carries the invoice's own currency_code (no mixing / no default drift)."""
    svc = _svc()
    inv = svc.create_invoice(customer_id=_CUSTOMER, currency_code="USD", lines=[
        {"line_type": "transport_fee", "quantity": Decimal("1"), "unit_price": Decimal("100"),
         "tax_rate": Decimal("0"), "discount_amount": Decimal("0")}])
    svc.issue_invoice(inv.id)
    envs = [c.args[0] for c in svc._event_repo.append.call_args_list]
    issued = [e for e in envs if e.event_type == "InvoiceIssued"]
    assert issued, "InvoiceIssued was not emitted"
    assert issued[-1].payload["currency_code"] == "USD"


def test_payment_recorded_emits_currency_code():
    """PaymentRecorded carries the invoice currency_code."""
    svc = _svc()
    inv = _make_issued_invoice(svc)  # default SAR
    svc.record_payment(inv.id, amount=inv.total_amount, method=PaymentMethod.CASH)
    envs = [c.args[0] for c in svc._event_repo.append.call_args_list]
    paid = [e for e in envs if e.event_type == "PaymentRecorded"]
    assert paid, "PaymentRecorded was not emitted"
    assert paid[-1].payload["currency_code"] == "SAR"
