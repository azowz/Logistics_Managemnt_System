"""Repositories for the Billing & Settlements domain (Sprint 9).

Constructor takes ``Session``; never commit/rollback; no FastAPI; no events;
tenant-scoped reads via RLS; soft-delete aware.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.models.billing import (
    Invoice,
    InvoiceLine,
    Payment,
    Payout,
    Penalty,
    Quote,
    Settlement,
)
from app.models.enums import PaymentStatus
from app.repositories.errors import NotFoundError


def _coerce_uuid(value: Union[str, uuid.UUID]) -> Optional[uuid.UUID]:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class _BaseRepo:
    model = None

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **data):
        obj = self.model(**data)
        self._session.add(obj)
        return obj

    def update(self, obj, **data):
        for field, value in data.items():
            if value is not None:
                setattr(obj, field, value)
        return obj

    def get_by_id(self, obj_id):
        oid = _coerce_uuid(obj_id)
        if oid is None:
            return None
        return self._session.get(self.model, oid)

    def get_by_id_or_raise(self, obj_id):
        obj = self.get_by_id(obj_id)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} {obj_id} not found.")
        return obj

    def soft_delete(self, obj, *, deleted_by=None):
        obj.soft_delete()
        obj.deleted_by = deleted_by
        return obj

    def restore(self, obj):
        obj.restore()
        obj.deleted_by = None
        return obj


class QuoteRepository(_BaseRepo):
    model = Quote

    def get_by_number(self, quote_number: str) -> Optional[Quote]:
        stmt = select(Quote).where(Quote.quote_number == quote_number, Quote.deleted_at.is_(None))
        return self._session.scalars(stmt).first()

    def list_quotes(
        self, *, q=None, status=None, customer_id=None, order_id=None, shipment_id=None,
        include_deleted=False, sort_by="created_at", sort_dir="desc", limit=50, offset=0,
    ) -> Tuple[List[Quote], int]:
        stmt = select(Quote)
        if not include_deleted:
            stmt = stmt.where(Quote.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Quote.status == status)
        if customer_id is not None:
            stmt = stmt.where(Quote.customer_id == customer_id)
        if order_id is not None:
            stmt = stmt.where(Quote.order_id == order_id)
        if shipment_id is not None:
            stmt = stmt.where(Quote.shipment_id == shipment_id)
        if q:
            stmt = stmt.where(Quote.quote_number.ilike(f"%{q}%"))
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Quote, sort_by, Quote.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class InvoiceRepository(_BaseRepo):
    model = Invoice

    def get_by_number(self, invoice_number: str) -> Optional[Invoice]:
        stmt = select(Invoice).where(
            Invoice.invoice_number == invoice_number, Invoice.deleted_at.is_(None)
        )
        return self._session.scalars(stmt).first()

    def list_invoices_for_customer(self, customer_id: uuid.UUID) -> List[Invoice]:
        stmt = select(Invoice).where(Invoice.customer_id == customer_id, Invoice.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_invoices_for_order(self, order_id: uuid.UUID) -> List[Invoice]:
        stmt = select(Invoice).where(Invoice.order_id == order_id, Invoice.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_invoices_for_shipment(self, shipment_id: uuid.UUID) -> List[Invoice]:
        stmt = select(Invoice).where(Invoice.shipment_id == shipment_id, Invoice.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def get_invoice_balance(self, invoice: Invoice) -> Decimal:
        """Outstanding balance = total - sum(confirmed payments)."""
        paid = self._session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == invoice.id,
                Payment.status == PaymentStatus.CONFIRMED,
                Payment.deleted_at.is_(None),
            )
        ) or Decimal("0")
        return Decimal(str(invoice.total_amount or 0)) - Decimal(str(paid))

    def list_invoices(
        self, *, q=None, status=None, customer_id=None, order_id=None, shipment_id=None, claim_id=None,
        include_deleted=False, sort_by="created_at", sort_dir="desc", limit=50, offset=0,
    ) -> Tuple[List[Invoice], int]:
        stmt = select(Invoice)
        if not include_deleted:
            stmt = stmt.where(Invoice.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Invoice.status == status)
        if customer_id is not None:
            stmt = stmt.where(Invoice.customer_id == customer_id)
        if order_id is not None:
            stmt = stmt.where(Invoice.order_id == order_id)
        if shipment_id is not None:
            stmt = stmt.where(Invoice.shipment_id == shipment_id)
        if claim_id is not None:
            stmt = stmt.where(Invoice.claim_id == claim_id)
        if q:
            stmt = stmt.where(Invoice.invoice_number.ilike(f"%{q}%"))
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Invoice, sort_by, Invoice.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class InvoiceLineRepository(_BaseRepo):
    model = InvoiceLine

    def list_lines_for_invoice(self, invoice_id: uuid.UUID) -> List[InvoiceLine]:
        stmt = select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.created_at)
        return list(self._session.scalars(stmt).all())


class PaymentRepository(_BaseRepo):
    model = Payment

    def list_payments_for_invoice(self, invoice_id: uuid.UUID, *, include_deleted: bool = False) -> List[Payment]:
        stmt = select(Payment).where(Payment.invoice_id == invoice_id)
        if not include_deleted:
            stmt = stmt.where(Payment.deleted_at.is_(None))
        return list(self._session.scalars(stmt.order_by(Payment.created_at)).all())

    def confirmed_total_for_invoice(self, invoice_id: uuid.UUID) -> Decimal:
        total = self._session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == invoice_id,
                Payment.status == PaymentStatus.CONFIRMED,
                Payment.deleted_at.is_(None),
            )
        )
        return Decimal(str(total or 0))


class SettlementRepository(_BaseRepo):
    model = Settlement

    def get_by_number(self, settlement_number: str) -> Optional[Settlement]:
        stmt = select(Settlement).where(
            Settlement.settlement_number == settlement_number, Settlement.deleted_at.is_(None)
        )
        return self._session.scalars(stmt).first()

    def list_settlements_for_claim(self, claim_id: uuid.UUID) -> List[Settlement]:
        stmt = select(Settlement).where(Settlement.claim_id == claim_id, Settlement.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_settlements(
        self, *, q=None, status=None, settlement_type=None, claim_id=None, customer_id=None,
        include_deleted=False, sort_by="created_at", sort_dir="desc", limit=50, offset=0,
    ) -> Tuple[List[Settlement], int]:
        stmt = select(Settlement)
        if not include_deleted:
            stmt = stmt.where(Settlement.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Settlement.status == status)
        if settlement_type is not None:
            stmt = stmt.where(Settlement.settlement_type == settlement_type)
        if claim_id is not None:
            stmt = stmt.where(Settlement.claim_id == claim_id)
        if customer_id is not None:
            stmt = stmt.where(Settlement.customer_id == customer_id)
        if q:
            stmt = stmt.where(Settlement.settlement_number.ilike(f"%{q}%"))
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Settlement, sort_by, Settlement.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class PayoutRepository(_BaseRepo):
    model = Payout

    def list_payouts_for_settlement(self, settlement_id: uuid.UUID) -> List[Payout]:
        stmt = select(Payout).where(Payout.settlement_id == settlement_id, Payout.deleted_at.is_(None))
        return list(self._session.scalars(stmt.order_by(Payout.created_at)).all())


class PenaltyRepository(_BaseRepo):
    model = Penalty

    def list_penalties_for_order(self, order_id: uuid.UUID) -> List[Penalty]:
        stmt = select(Penalty).where(Penalty.order_id == order_id, Penalty.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_penalties_for_shipment(self, shipment_id: uuid.UUID) -> List[Penalty]:
        stmt = select(Penalty).where(Penalty.shipment_id == shipment_id, Penalty.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_penalties(
        self, *, penalty_type=None, order_id=None, shipment_id=None, invoice_id=None,
        include_deleted=False, sort_by="created_at", sort_dir="desc", limit=50, offset=0,
    ) -> Tuple[List[Penalty], int]:
        stmt = select(Penalty)
        if not include_deleted:
            stmt = stmt.where(Penalty.deleted_at.is_(None))
        if penalty_type is not None:
            stmt = stmt.where(Penalty.penalty_type == penalty_type)
        if order_id is not None:
            stmt = stmt.where(Penalty.order_id == order_id)
        if shipment_id is not None:
            stmt = stmt.where(Penalty.shipment_id == shipment_id)
        if invoice_id is not None:
            stmt = stmt.where(Penalty.invoice_id == invoice_id)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Penalty, sort_by, Penalty.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total
