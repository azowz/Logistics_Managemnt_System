"""Billing & Settlements domain models (context #18, Sprint 9).

Owns quotes, invoices + invoice lines, payments, settlements, payouts, and
penalties — the commercial/financial state of the platform (docs/09, docs/10).
Billing references Customer / Order / Shipment / Equipment / Claim by id;
those contexts do not own the billing lifecycle. Billing *consumes* approved
claim outcomes (Sprint 8) to create settlement records.

All tables are tenant-scoped (RLS), soft-deletable + auditable, optimistic-locked.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    InvoiceLineType,
    InvoiceStatus,
    LineReferenceType,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
    PenaltyType,
    QuoteStatus,
    SettlementStatus,
    SettlementType,
)


def _enum_values(enum_cls) -> list[str]:
    return [member.value for member in enum_cls]


class Quote(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "quote_number", name="uq_quotes_tenant_id_quote_number"),
        CheckConstraint(
            "status IN ('draft', 'issued', 'approved', 'rejected', 'expired', 'cancelled')",
            name="status",
        ),
        CheckConstraint("subtotal_amount >= 0", name="subtotal_non_negative"),
        CheckConstraint("tax_amount >= 0", name="tax_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quote_number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[QuoteStatus] = mapped_column(
        SAEnum(QuoteStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=QuoteStatus.DRAFT,
        server_default="draft",
        index=True,
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    terms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Invoice(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "invoice_number", name="uq_invoices_tenant_id_invoice_number"
        ),
        CheckConstraint(
            "status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'voided', 'cancelled')",
            name="status",
        ),
        CheckConstraint("subtotal_amount >= 0", name="subtotal_non_negative"),
        CheckConstraint("tax_amount >= 0", name="tax_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint("penalty_amount >= 0", name="penalty_non_negative"),
        CheckConstraint("claim_adjustment_amount >= 0", name="claim_adjustment_non_negative"),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True
    )
    claim_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=InvoiceStatus.DRAFT,
        server_default="draft",
        index=True,
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    penalty_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    claim_adjustment_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    is_credit_note: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class InvoiceLine(TimestampMixin, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint(
            "line_type IN ('transport_fee', 'equipment_fee', 'permit_fee', 'escort_fee', "
            "'storage_fee', 'penalty', 'claim_adjustment', 'cancellation_fee', 'discount', 'tax')",
            name="line_type",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("tax_rate >= 0", name="tax_rate_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_type: Mapped[InvoiceLineType] = mapped_column(
        SAEnum(InvoiceLineType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(String(512))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    reference_type: Mapped[Optional[LineReferenceType]] = mapped_column(
        SAEnum(LineReferenceType, native_enum=False, length=16, values_callable=_enum_values),
        nullable=True,
    )
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)


class Payment(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'confirmed', 'failed', 'reversed')", name="status"),
        CheckConstraint(
            "method IN ('bank_transfer', 'cash', 'card', 'sadad', 'internal_adjustment')",
            name="method",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_reference: Mapped[Optional[str]] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=PaymentStatus.CONFIRMED,
        server_default="confirmed",
        index=True,
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Settlement(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "settlement_number", name="uq_settlements_tenant_id_settlement_number"
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'settled', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "settlement_type IN ('claim_payout', 'claim_offset', 'customer_refund', "
            "'carrier_payout', 'penalty_deduction')",
            name="settlement_type",
        ),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    settlement_number: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SettlementStatus] = mapped_column(
        SAEnum(SettlementStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=SettlementStatus.DRAFT,
        server_default="draft",
        index=True,
    )
    settlement_type: Mapped[SettlementType] = mapped_column(
        SAEnum(SettlementType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Payout(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "payouts"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'paid', 'failed')", name="status"),
        CheckConstraint(
            "method IN ('bank_transfer', 'cash', 'card', 'sadad', 'internal_adjustment')",
            name="method",
        ),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("settlements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payout_reference: Mapped[Optional[str]] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
    )
    status: Mapped[PayoutStatus] = mapped_column(
        SAEnum(PayoutStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=PayoutStatus.PENDING,
        server_default="pending",
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Penalty(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "penalties"
    __table_args__ = (
        CheckConstraint(
            "penalty_type IN ('late_delivery', 'cancellation_fee', 'compliance_violation', "
            "'damage', 'other')",
            name="penalty_type",
        ),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    penalty_type: Mapped[PenaltyType] = mapped_column(
        SAEnum(PenaltyType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    reason: Mapped[Optional[str]] = mapped_column(Text)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}
