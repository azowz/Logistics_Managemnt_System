"""ORM-level tests for Billing & Settlements models (SQLite)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.billing import Invoice, InvoiceLine, Payment, Payout, Penalty, Quote, Settlement
from billing_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def test_quote_defaults_and_persist(Session):
    s = Session()
    try:
        q = Quote(tenant_id=_TENANT, quote_number="QUO-M1", status="draft",
                  subtotal_amount=Decimal("100"), tax_amount=Decimal("15"),
                  discount_amount=Decimal("5"), total_amount=Decimal("110"))
        s.add(q)
        s.commit()
        s.refresh(q)
        assert q.id is not None and q.version == 1 and q.currency_code == "SAR"
        assert q.is_deleted is False
    finally:
        s.close()


def test_invoice_with_lines_and_payment(Session):
    s = Session()
    try:
        inv = Invoice(tenant_id=_TENANT, invoice_number="INV-M1", status="draft",
                      subtotal_amount=Decimal("0"), total_amount=Decimal("0"))
        s.add(inv)
        s.commit()
        line = InvoiceLine(tenant_id=_TENANT, invoice_id=inv.id, line_type="transport_fee",
                           quantity=Decimal("2"), unit_price=Decimal("50"), line_total=Decimal("100"))
        s.add(line)
        pay = Payment(tenant_id=_TENANT, invoice_id=inv.id, amount=Decimal("100"), method="cash", status="confirmed")
        s.add(pay)
        s.commit()
        assert line.id is not None
        assert pay.status == "confirmed"
    finally:
        s.close()


def test_settlement_payout_penalty(Session):
    s = Session()
    try:
        stl = Settlement(tenant_id=_TENANT, settlement_number="STL-M1", settlement_type="claim_payout",
                         status="draft", amount=Decimal("500"))
        s.add(stl)
        s.commit()
        po = Payout(tenant_id=_TENANT, settlement_id=stl.id, amount=Decimal("500"), method="bank_transfer",
                    status="pending")
        s.add(po)
        pen = Penalty(tenant_id=_TENANT, penalty_type="late_delivery", amount=Decimal("25"))
        s.add(pen)
        s.commit()
        assert po.settlement_id == stl.id
        assert pen.penalty_type == "late_delivery"
    finally:
        s.close()


def test_soft_delete_roundtrip(Session):
    s = Session()
    try:
        inv = Invoice(tenant_id=_TENANT, invoice_number="INV-M2", status="draft", total_amount=Decimal("0"))
        s.add(inv)
        s.commit()
        inv.soft_delete()
        s.commit()
        assert inv.is_deleted is True
        inv.restore()
        s.commit()
        assert inv.is_deleted is False
    finally:
        s.close()


def test_enum_values_stored_lowercase(Session):
    s = Session()
    try:
        q = Quote(tenant_id=_TENANT, quote_number="QUO-M2", status="issued", total_amount=Decimal("1"))
        s.add(q)
        s.commit()
        raw = s.execute(
            __import__("sqlalchemy").text("SELECT status FROM quotes WHERE quote_number='QUO-M2'")
        ).scalar()
        assert raw == "issued"
    finally:
        s.close()
