"""Pydantic schemas for the Billing & Settlements domain (Sprint 9)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    InvoiceLineType,
    InvoiceStatus,
    LineReferenceType,
    PaymentMethod,
    PayoutStatus,
    PenaltyType,
    QuoteStatus,
    SettlementStatus,
    SettlementType,
)
from app.schemas.common import IdModel, TimestampMixin

_QUOTE_SORT = frozenset({"quote_number", "status", "total_amount", "valid_until", "created_at", "updated_at"})
_INVOICE_SORT = frozenset({"invoice_number", "status", "total_amount", "due_date", "created_at", "updated_at"})
_SETTLEMENT_SORT = frozenset({"settlement_number", "status", "settlement_type", "amount", "created_at", "updated_at"})
_PENALTY_SORT = frozenset({"penalty_type", "amount", "applied_at", "created_at", "updated_at"})


def _currency(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.upper()
    if not re.fullmatch(r"[A-Z]{3}", v):
        raise ValueError("currency_code must be a 3-letter ISO-4217 code.")
    return v


def _tz(v: Optional[datetime]) -> Optional[datetime]:
    if v is not None and v.tzinfo is None:
        raise ValueError("Datetime fields must be timezone-aware (UTC).")
    return v


# --- Quote -----------------------------------------------------------------


class QuoteCreate(BaseModel):
    quote_number: Optional[str] = Field(default=None, max_length=64)
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    subtotal_amount: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    valid_until: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)
    terms: Optional[dict] = None

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @field_validator("valid_until")
    @classmethod
    def tz(cls, v):
        return _tz(v)


class QuoteUpdate(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    subtotal_amount: Optional[Decimal] = Field(default=None, ge=0)
    tax_amount: Optional[Decimal] = Field(default=None, ge=0)
    discount_amount: Optional[Decimal] = Field(default=None, ge=0)
    valid_until: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)
    terms: Optional[dict] = None

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @model_validator(mode="after")
    def at_least_one(self) -> "QuoteUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class QuoteRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    quote_number: str
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    status: QuoteStatus
    currency_code: str
    subtotal_amount: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    valid_until: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    notes: Optional[str] = None
    terms: Optional[dict] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class QuoteListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[QuoteStatus] = None
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _QUOTE_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_QUOTE_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class QuoteRejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


# --- Invoice ---------------------------------------------------------------


class InvoiceLineCreate(BaseModel):
    line_type: InvoiceLineType
    description: Optional[str] = Field(default=None, max_length=512)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    reference_type: Optional[LineReferenceType] = None
    reference_id: Optional[uuid.UUID] = None


class InvoiceLineRead(IdModel):
    tenant_id: uuid.UUID
    invoice_id: uuid.UUID
    line_type: InvoiceLineType
    description: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    discount_amount: Decimal
    line_total: Decimal
    reference_type: Optional[LineReferenceType] = None
    reference_id: Optional[uuid.UUID] = None
    model_config = ConfigDict(from_attributes=True)


class InvoiceCreate(BaseModel):
    invoice_number: Optional[str] = Field(default=None, max_length=64)
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    quote_id: Optional[uuid.UUID] = None
    claim_id: Optional[uuid.UUID] = None
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    is_credit_note: bool = False
    due_date: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)
    lines: List[InvoiceLineCreate] = Field(default_factory=list)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @field_validator("due_date")
    @classmethod
    def tz(cls, v):
        return _tz(v)


class InvoiceUpdate(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    due_date: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @model_validator(mode="after")
    def at_least_one(self) -> "InvoiceUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class InvoiceRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    invoice_number: str
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    quote_id: Optional[uuid.UUID] = None
    claim_id: Optional[uuid.UUID] = None
    status: InvoiceStatus
    currency_code: str
    subtotal_amount: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    penalty_amount: Decimal
    claim_adjustment_amount: Decimal
    total_amount: Decimal
    is_credit_note: bool
    due_date: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class InvoiceListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[InvoiceStatus] = None
    customer_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    claim_id: Optional[uuid.UUID] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _INVOICE_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_INVOICE_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class InvoiceVoidRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)
    allow_override: bool = False


class InvoiceCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


# --- Payment ---------------------------------------------------------------


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    payment_reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=4000)
    confirm: bool = True
    allow_override: bool = False

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)


class PaymentRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    invoice_id: uuid.UUID
    payment_reference: Optional[str] = None
    amount: Decimal
    currency_code: str
    method: PaymentMethod
    status: str
    paid_at: Optional[datetime] = None
    received_by: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


# --- Settlement ------------------------------------------------------------


class SettlementCreate(BaseModel):
    settlement_number: Optional[str] = Field(default=None, max_length=64)
    settlement_type: SettlementType
    claim_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    notes: Optional[str] = Field(default=None, max_length=4000)
    allow_override: bool = False

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)


class SettlementUpdate(BaseModel):
    amount: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    invoice_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @model_validator(mode="after")
    def at_least_one(self) -> "SettlementUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class SettlementRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    settlement_number: str
    claim_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    status: SettlementStatus
    settlement_type: SettlementType
    amount: Decimal
    currency_code: str
    approved_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class SettlementListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[SettlementStatus] = None
    settlement_type: Optional[SettlementType] = None
    claim_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _SETTLEMENT_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_SETTLEMENT_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class SettlementCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


# --- Payout ----------------------------------------------------------------


class PayoutCreate(BaseModel):
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    method: PaymentMethod
    payout_reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=4000)


class PayoutRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    settlement_id: uuid.UUID
    payout_reference: Optional[str] = None
    amount: Decimal
    currency_code: str
    method: PaymentMethod
    status: PayoutStatus
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


# --- Penalty ---------------------------------------------------------------


class PenaltyCreate(BaseModel):
    penalty_type: PenaltyType
    amount: Decimal = Field(ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    reason: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)


class PenaltyRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    penalty_type: PenaltyType
    amount: Decimal
    currency_code: str
    reason: Optional[str] = None
    applied_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class PenaltyListParams(BaseModel):
    penalty_type: Optional[PenaltyType] = None
    order_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _PENALTY_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_PENALTY_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
