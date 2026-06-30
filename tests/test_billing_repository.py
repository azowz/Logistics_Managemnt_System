"""Tests for billing repositories: no-commit, query helpers, balances."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import InvoiceStatus, PaymentStatus, QuoteStatus, SettlementStatus
from app.repositories.billing_repository import (
    InvoiceLineRepository,
    InvoiceRepository,
    PaymentRepository,
    PayoutRepository,
    PenaltyRepository,
    QuoteRepository,
    SettlementRepository,
)
from app.repositories.errors import NotFoundError
from billing_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def test_quote_no_commit_and_lookup(Session):
    s = Session()
    try:
        repo = QuoteRepository(s)
        q = repo.create(tenant_id=_TENANT, quote_number="QUO-NC", status=QuoteStatus.DRAFT, total_amount=Decimal("0"))
        qid = q.id
        s.rollback()
        assert repo.get_by_id(qid) is None
        with pytest.raises(NotFoundError):
            repo.get_by_id_or_raise(uuid.uuid4())
    finally:
        s.close()


def test_quote_get_by_number_and_list(Session):
    s = Session()
    try:
        repo = QuoteRepository(s)
        repo.create(tenant_id=_TENANT, quote_number="QUO-FIND", status=QuoteStatus.ISSUED, total_amount=Decimal("10"))
        s.commit()
        assert repo.get_by_number("QUO-FIND") is not None
        items, total = repo.list_quotes(status=QuoteStatus.ISSUED, limit=1)
        assert total >= 1 and len(items) == 1
    finally:
        s.close()


def test_invoice_balance_and_listings(Session):
    s = Session()
    try:
        irepo = InvoiceRepository(s)
        cust = uuid.uuid4()
        inv = irepo.create(tenant_id=_TENANT, invoice_number="INV-BAL", status=InvoiceStatus.ISSUED,
                           customer_id=cust, total_amount=Decimal("300"))
        s.commit()
        prepo = PaymentRepository(s)
        prepo.create(tenant_id=_TENANT, invoice_id=inv.id, amount=Decimal("120"), method="cash",
                     status=PaymentStatus.CONFIRMED)
        s.commit()
        assert irepo.get_invoice_balance(inv) == Decimal("180")
        assert prepo.confirmed_total_for_invoice(inv.id) == Decimal("120")
        assert len(prepo.list_payments_for_invoice(inv.id)) == 1
        assert len(irepo.list_invoices_for_customer(cust)) == 1
        items, total = irepo.list_invoices(status=InvoiceStatus.ISSUED)
        assert total >= 1
    finally:
        s.close()


def test_invoice_lines_for_invoice(Session):
    s = Session()
    try:
        irepo = InvoiceRepository(s)
        inv = irepo.create(tenant_id=_TENANT, invoice_number="INV-LN", status=InvoiceStatus.DRAFT, total_amount=Decimal("0"))
        s.commit()
        lrepo = InvoiceLineRepository(s)
        lrepo.create(tenant_id=_TENANT, invoice_id=inv.id, line_type="transport_fee",
                     quantity=Decimal("1"), unit_price=Decimal("50"), line_total=Decimal("50"))
        s.commit()
        assert len(lrepo.list_lines_for_invoice(inv.id)) == 1
    finally:
        s.close()


def test_settlement_and_payout_listings(Session):
    s = Session()
    try:
        srepo = SettlementRepository(s)
        claim = uuid.uuid4()
        stl = srepo.create(tenant_id=_TENANT, settlement_number="STL-FIND", settlement_type="claim_payout",
                           status=SettlementStatus.APPROVED, claim_id=claim, amount=Decimal("400"))
        s.commit()
        assert srepo.get_by_number("STL-FIND") is not None
        assert len(srepo.list_settlements_for_claim(claim)) == 1
        items, total = srepo.list_settlements(status=SettlementStatus.APPROVED)
        assert total >= 1
        porepo = PayoutRepository(s)
        porepo.create(tenant_id=_TENANT, settlement_id=stl.id, amount=Decimal("400"), method="bank_transfer")
        s.commit()
        assert len(porepo.list_payouts_for_settlement(stl.id)) == 1
    finally:
        s.close()


def test_penalty_listings(Session):
    s = Session()
    try:
        repo = PenaltyRepository(s)
        order = uuid.uuid4()
        ship = uuid.uuid4()
        repo.create(tenant_id=_TENANT, penalty_type="late_delivery", amount=Decimal("10"), order_id=order)
        repo.create(tenant_id=_TENANT, penalty_type="damage", amount=Decimal("20"), shipment_id=ship)
        s.commit()
        assert len(repo.list_penalties_for_order(order)) == 1
        assert len(repo.list_penalties_for_shipment(ship)) == 1
        items, total = repo.list_penalties(penalty_type="late_delivery")
        assert total >= 1
    finally:
        s.close()


def test_soft_delete_and_restore(Session):
    s = Session()
    try:
        repo = InvoiceRepository(s)
        inv = repo.create(tenant_id=_TENANT, invoice_number="INV-SD", status=InvoiceStatus.DRAFT, total_amount=Decimal("0"))
        s.commit()
        repo.soft_delete(inv, deleted_by=_USER)
        s.commit()
        assert inv.is_deleted is True and inv.deleted_by == _USER
        repo.restore(inv)
        s.commit()
        assert inv.is_deleted is False
    finally:
        s.close()
