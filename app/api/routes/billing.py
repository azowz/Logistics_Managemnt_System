"""Billing & Settlements API routes — quotes, invoices, payments, settlements,
penalties (thin handlers, RBAC).

Literal paths are declared before dynamic ``{id}`` paths so they take precedence.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.pagination import Page
from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import (
    InvoiceStatus,
    PenaltyType,
    QuoteStatus,
    SettlementStatus,
    SettlementType,
    UserRole,
)
from app.schemas.billing import (
    InvoiceCancelRequest,
    InvoiceCreate,
    InvoiceLineRead,
    InvoiceListParams,
    InvoiceRead,
    InvoiceUpdate,
    InvoiceVoidRequest,
    PaymentCreate,
    PaymentRead,
    PayoutCreate,
    PayoutRead,
    PenaltyCreate,
    PenaltyListParams,
    PenaltyRead,
    QuoteCreate,
    QuoteListParams,
    QuoteRead,
    QuoteRejectRequest,
    QuoteUpdate,
    SettlementCancelRequest,
    SettlementCreate,
    SettlementListParams,
    SettlementRead,
    SettlementUpdate,
)
from app.services.billing_service import BillingService
from app.services.settlement_service import SettlementService

router = APIRouter(prefix="/billing", tags=["billing"])

_WRITE = (UserRole.ADMIN, UserRole.MANAGER)
_READ = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)
_OVERRIDE = (UserRole.ADMIN,)  # over-balance payment, void-paid, over-claim settlement


def _quote_page(p) -> Page[QuoteRead]:
    return Page[QuoteRead](items=[QuoteRead.model_validate(x) for x in p.items],
                           total=p.total, page=p.page, size=p.size, pages=p.pages)


def _invoice_page(p) -> Page[InvoiceRead]:
    return Page[InvoiceRead](items=[InvoiceRead.model_validate(x) for x in p.items],
                             total=p.total, page=p.page, size=p.size, pages=p.pages)


def _settlement_page(p) -> Page[SettlementRead]:
    return Page[SettlementRead](items=[SettlementRead.model_validate(x) for x in p.items],
                                total=p.total, page=p.page, size=p.size, pages=p.pages)


def _penalty_page(p) -> Page[PenaltyRead]:
    return Page[PenaltyRead](items=[PenaltyRead.model_validate(x) for x in p.items],
                             total=p.total, page=p.page, size=p.size, pages=p.pages)


# ============================ Quotes ============================


@router.post("/quotes", response_model=QuoteRead, status_code=status.HTTP_201_CREATED, summary="Create a quote.")
def create_quote(payload: QuoteCreate, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).create_quote(**payload.model_dump()))


@router.get("/quotes/search", response_model=Page[QuoteRead], summary="Search quotes.")
def search_quotes(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[QuoteStatus] = Query(default=None, alias="status"),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[QuoteRead]:
    params = QuoteListParams(q=q, status=status_filter, customer_id=customer_id, order_id=order_id,
                             shipment_id=shipment_id, include_deleted=include_deleted, sort_by=sort_by,
                             sort_dir=sort_dir, page=page, size=size)
    return _quote_page(BillingService(session).list_quotes(params))


@router.get("/quotes", response_model=Page[QuoteRead], summary="List quotes.")
def list_quotes(
    status_filter: Optional[QuoteStatus] = Query(default=None, alias="status"),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[QuoteRead]:
    params = QuoteListParams(status=status_filter, customer_id=customer_id, order_id=order_id,
                             shipment_id=shipment_id, include_deleted=include_deleted, sort_by=sort_by,
                             sort_dir=sort_dir, page=page, size=size)
    return _quote_page(BillingService(session).list_quotes(params))


@router.get("/quotes/{quote_id}", response_model=QuoteRead, summary="Get a quote.")
def get_quote(quote_id: uuid.UUID, include_deleted: bool = Query(default=False),
              session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).get_quote(quote_id, include_deleted=include_deleted))


@router.patch("/quotes/{quote_id}", response_model=QuoteRead, summary="Update a quote.")
def update_quote(quote_id: uuid.UUID, payload: QuoteUpdate, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).update_quote(quote_id, **payload.model_dump(exclude_unset=True)))


@router.post("/quotes/{quote_id}/issue", response_model=QuoteRead, summary="Issue a quote.")
def issue_quote(quote_id: uuid.UUID, session: Session = Depends(get_session),
                current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).issue_quote(quote_id))


@router.post("/quotes/{quote_id}/approve", response_model=QuoteRead, summary="Approve a quote.")
def approve_quote(quote_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).approve_quote(quote_id))


@router.post("/quotes/{quote_id}/reject", response_model=QuoteRead, summary="Reject a quote.")
def reject_quote(quote_id: uuid.UUID, payload: QuoteRejectRequest, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).reject_quote(quote_id, reason=payload.reason))


@router.post("/quotes/{quote_id}/expire", response_model=QuoteRead, summary="Expire a quote.")
def expire_quote(quote_id: uuid.UUID, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).expire_quote(quote_id))


@router.post("/quotes/{quote_id}/cancel", response_model=QuoteRead, summary="Cancel a quote.")
def cancel_quote(quote_id: uuid.UUID, payload: QuoteRejectRequest, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> QuoteRead:
    return QuoteRead.model_validate(BillingService(session).cancel_quote(quote_id, reason=payload.reason))


# ============================ Invoices ============================


@router.post("/invoices", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED, summary="Create an invoice.")
def create_invoice(payload: InvoiceCreate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_WRITE))) -> InvoiceRead:
    data = payload.model_dump()
    lines = data.pop("lines", [])
    return InvoiceRead.model_validate(BillingService(session).create_invoice(lines=lines, **data))


@router.get("/invoices/search", response_model=Page[InvoiceRead], summary="Search invoices.")
def search_invoices(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[InvoiceStatus] = Query(default=None, alias="status"),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    claim_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[InvoiceRead]:
    params = InvoiceListParams(q=q, status=status_filter, customer_id=customer_id, order_id=order_id,
                               shipment_id=shipment_id, claim_id=claim_id, include_deleted=include_deleted,
                               sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    return _invoice_page(BillingService(session).list_invoices(params))


@router.get("/invoices", response_model=Page[InvoiceRead], summary="List invoices.")
def list_invoices(
    status_filter: Optional[InvoiceStatus] = Query(default=None, alias="status"),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    claim_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[InvoiceRead]:
    params = InvoiceListParams(status=status_filter, customer_id=customer_id, order_id=order_id,
                               shipment_id=shipment_id, claim_id=claim_id, include_deleted=include_deleted,
                               sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    return _invoice_page(BillingService(session).list_invoices(params))


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead, summary="Get an invoice.")
def get_invoice(invoice_id: uuid.UUID, include_deleted: bool = Query(default=False),
                session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> InvoiceRead:
    return InvoiceRead.model_validate(BillingService(session).get_invoice(invoice_id, include_deleted=include_deleted))


@router.patch("/invoices/{invoice_id}", response_model=InvoiceRead, summary="Update a draft invoice.")
def update_invoice(invoice_id: uuid.UUID, payload: InvoiceUpdate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_WRITE))) -> InvoiceRead:
    return InvoiceRead.model_validate(BillingService(session).update_invoice(invoice_id, **payload.model_dump(exclude_unset=True)))


@router.get("/invoices/{invoice_id}/lines", response_model=list[InvoiceLineRead], summary="List invoice lines.")
def list_invoice_lines(invoice_id: uuid.UUID, session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_READ))) -> list[InvoiceLineRead]:
    return [InvoiceLineRead.model_validate(x) for x in BillingService(session).list_invoice_lines(invoice_id)]


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceRead, summary="Issue an invoice.")
def issue_invoice(invoice_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> InvoiceRead:
    return InvoiceRead.model_validate(BillingService(session).issue_invoice(invoice_id))


@router.post("/invoices/{invoice_id}/payments", response_model=PaymentRead, status_code=status.HTTP_201_CREATED,
             summary="Record a payment against an invoice.")
def record_payment(invoice_id: uuid.UUID, payload: PaymentCreate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_WRITE))) -> PaymentRead:
    allow = payload.allow_override and current_user.role == UserRole.ADMIN
    return PaymentRead.model_validate(BillingService(session).record_payment(
        invoice_id, amount=payload.amount, method=payload.method, currency_code=payload.currency_code,
        payment_reference=payload.payment_reference, notes=payload.notes, confirm=payload.confirm,
        allow_override=allow))


@router.get("/invoices/{invoice_id}/payments", response_model=list[PaymentRead], summary="List payments for an invoice.")
def list_payments(invoice_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_READ))) -> list[PaymentRead]:
    return [PaymentRead.model_validate(x) for x in BillingService(session).list_payments(invoice_id)]


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceRead, summary="Void an invoice.")
def void_invoice(invoice_id: uuid.UUID, payload: InvoiceVoidRequest, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> InvoiceRead:
    allow = payload.allow_override and current_user.role == UserRole.ADMIN
    return InvoiceRead.model_validate(BillingService(session).void_invoice(invoice_id, reason=payload.reason, allow_override=allow))


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceRead, summary="Cancel an invoice.")
def cancel_invoice(invoice_id: uuid.UUID, payload: InvoiceCancelRequest, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_WRITE))) -> InvoiceRead:
    return InvoiceRead.model_validate(BillingService(session).cancel_invoice(invoice_id, reason=payload.reason))


# ============================ Settlements ============================


@router.post("/settlements", response_model=SettlementRead, status_code=status.HTTP_201_CREATED, summary="Create a settlement.")
def create_settlement(payload: SettlementCreate, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_WRITE))) -> SettlementRead:
    data = payload.model_dump()
    allow = data.pop("allow_override", False) and current_user.role == UserRole.ADMIN
    return SettlementRead.model_validate(SettlementService(session).create_settlement(allow_override=allow, **data))


@router.get("/settlements/search", response_model=Page[SettlementRead], summary="Search settlements.")
def search_settlements(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[SettlementStatus] = Query(default=None, alias="status"),
    settlement_type: Optional[SettlementType] = Query(default=None),
    claim_id: Optional[uuid.UUID] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[SettlementRead]:
    params = SettlementListParams(q=q, status=status_filter, settlement_type=settlement_type, claim_id=claim_id,
                                  customer_id=customer_id, include_deleted=include_deleted, sort_by=sort_by,
                                  sort_dir=sort_dir, page=page, size=size)
    return _settlement_page(SettlementService(session).list_settlements(params))


@router.get("/settlements", response_model=Page[SettlementRead], summary="List settlements.")
def list_settlements(
    status_filter: Optional[SettlementStatus] = Query(default=None, alias="status"),
    settlement_type: Optional[SettlementType] = Query(default=None),
    claim_id: Optional[uuid.UUID] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[SettlementRead]:
    params = SettlementListParams(status=status_filter, settlement_type=settlement_type, claim_id=claim_id,
                                  customer_id=customer_id, include_deleted=include_deleted, sort_by=sort_by,
                                  sort_dir=sort_dir, page=page, size=size)
    return _settlement_page(SettlementService(session).list_settlements(params))


@router.get("/settlements/{settlement_id}", response_model=SettlementRead, summary="Get a settlement.")
def get_settlement(settlement_id: uuid.UUID, include_deleted: bool = Query(default=False),
                   session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> SettlementRead:
    return SettlementRead.model_validate(SettlementService(session).get_settlement(settlement_id, include_deleted=include_deleted))


@router.patch("/settlements/{settlement_id}", response_model=SettlementRead, summary="Update a settlement.")
def update_settlement(settlement_id: uuid.UUID, payload: SettlementUpdate, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_WRITE))) -> SettlementRead:
    return SettlementRead.model_validate(SettlementService(session).update_settlement(settlement_id, **payload.model_dump(exclude_unset=True)))


@router.post("/settlements/{settlement_id}/submit", response_model=SettlementRead, summary="Submit a settlement for approval.")
def submit_settlement(settlement_id: uuid.UUID, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_WRITE))) -> SettlementRead:
    return SettlementRead.model_validate(SettlementService(session).submit_settlement_for_approval(settlement_id))


@router.post("/settlements/{settlement_id}/approve", response_model=SettlementRead, summary="Approve a settlement.")
def approve_settlement(settlement_id: uuid.UUID, session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_OVERRIDE))) -> SettlementRead:
    return SettlementRead.model_validate(SettlementService(session).approve_settlement(settlement_id))


@router.post("/settlements/{settlement_id}/settle", response_model=SettlementRead, summary="Settle a settlement.")
def settle_settlement(settlement_id: uuid.UUID, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_OVERRIDE))) -> SettlementRead:
    return SettlementRead.model_validate(SettlementService(session).settle_settlement(settlement_id))


@router.post("/settlements/{settlement_id}/cancel", response_model=SettlementRead, summary="Cancel a settlement.")
def cancel_settlement(settlement_id: uuid.UUID, payload: SettlementCancelRequest, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_WRITE))) -> SettlementRead:
    return SettlementRead.model_validate(SettlementService(session).cancel_settlement(settlement_id, reason=payload.reason))


@router.post("/settlements/{settlement_id}/payouts", response_model=PayoutRead, status_code=status.HTTP_201_CREATED,
             summary="Create a payout for a settlement.")
def create_payout(settlement_id: uuid.UUID, payload: PayoutCreate, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_OVERRIDE))) -> PayoutRead:
    return PayoutRead.model_validate(SettlementService(session).create_payout(
        settlement_id, amount=payload.amount, method=payload.method,
        payout_reference=payload.payout_reference, notes=payload.notes))


@router.get("/settlements/{settlement_id}/payouts", response_model=list[PayoutRead], summary="List payouts for a settlement.")
def list_payouts(settlement_id: uuid.UUID, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_READ))) -> list[PayoutRead]:
    return [PayoutRead.model_validate(x) for x in SettlementService(session).list_payouts(settlement_id)]


# ============================ Penalties ============================


@router.post("/penalties", response_model=PenaltyRead, status_code=status.HTTP_201_CREATED, summary="Apply a penalty.")
def create_penalty(payload: PenaltyCreate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_WRITE))) -> PenaltyRead:
    data = payload.model_dump()
    if data["penalty_type"] == PenaltyType.CANCELLATION_FEE:
        penalty = BillingService(session).apply_cancellation_fee(
            amount=data["amount"], order_id=data.get("order_id"), shipment_id=data.get("shipment_id"),
            invoice_id=data.get("invoice_id"), reason=data.get("reason"), currency_code=data["currency_code"])
    else:
        penalty = BillingService(session).apply_penalty(**data)
    return PenaltyRead.model_validate(penalty)


@router.get("/penalties", response_model=Page[PenaltyRead], summary="List penalties.")
def list_penalties(
    penalty_type: Optional[PenaltyType] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    invoice_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[PenaltyRead]:
    params = PenaltyListParams(penalty_type=penalty_type, order_id=order_id, shipment_id=shipment_id,
                               invoice_id=invoice_id, include_deleted=include_deleted, sort_by=sort_by,
                               sort_dir=sort_dir, page=page, size=size)
    return _penalty_page(BillingService(session).list_penalties(params))
