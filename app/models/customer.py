"""Customer aggregate — the primary commercial entity in the logistics platform.

A Customer represents an organization or individual that places orders and
receives shipments. Each customer is isolated within a tenant (ADR-001 / RLS)
and versioned for optimistic concurrency (ADR-004).

Business invariants enforced here:
  * ``code`` is unique per tenant (``uq_customers_tenant_id_code``).
  * ``commercial_registration`` is unique per tenant when provided.
  * ``vat_number`` is unique per tenant when provided.
  * ``status`` is one of: active | suspended | inactive.
  * ``risk_level`` is one of: low | medium | high.
  * ``credit_status`` is one of: good | watch | blocked.
  * ``customer_type`` is one of: individual | corporate | government | sme.
  * Soft-delete only; ``deleted_at`` / ``deleted_by`` are set on logical removal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
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
from app.models.enums import CreditStatus, CustomerStatus, CustomerType, RiskLevel


def _enum_values(enum_cls) -> list[str]:
    """Persist enum *values* (e.g. 'active'), not member names ('ACTIVE').

    SQLAlchemy's ``Enum`` stores member names by default; our CHECK constraints,
    migrations, and API contract all use the lowercase values, so every
    ``SAEnum`` column must opt into ``values_callable``.
    """
    return [member.value for member in enum_cls]


class Customer(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """A commercial customer (organization or individual) within a tenant."""

    __tablename__ = "customers"
    __table_args__ = (
        # Tenant-scoped uniqueness invariants (ADR-001).
        UniqueConstraint("tenant_id", "code", name="uq_customers_tenant_id_code"),
        UniqueConstraint(
            "tenant_id",
            "commercial_registration",
            name="uq_customers_tenant_id_commercial_registration",
        ),
        UniqueConstraint(
            "tenant_id", "vat_number", name="uq_customers_tenant_id_vat_number"
        ),
        # VARCHAR + CHECK guards (ck naming convention expands "status" →
        # "ck_customers_status").
        CheckConstraint(
            "status IN ('active', 'suspended', 'inactive')", name="status"
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')", name="risk_level"
        ),
        CheckConstraint(
            "credit_status IN ('good', 'watch', 'blocked')", name="credit_status"
        ),
        CheckConstraint(
            "customer_type IN ('individual', 'corporate', 'government', 'sme')",
            name="customer_type",
        ),
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Internal identifier — unique within a tenant.
    code: Mapped[str] = mapped_column(String(64), nullable=False)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    customer_type: Mapped[CustomerType] = mapped_column(
        SAEnum(CustomerType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=CustomerType.CORPORATE,
    )
    industry: Mapped[Optional[str]] = mapped_column(String(128))

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    commercial_name: Mapped[Optional[str]] = mapped_column(String(255))

    # ------------------------------------------------------------------
    # Legal / Tax
    # ------------------------------------------------------------------

    tax_number: Mapped[Optional[str]] = mapped_column(String(64))
    commercial_registration: Mapped[Optional[str]] = mapped_column(String(64))
    vat_number: Mapped[Optional[str]] = mapped_column(String(64))

    # ------------------------------------------------------------------
    # Contact
    # ------------------------------------------------------------------

    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    primary_phone: Mapped[Optional[str]] = mapped_column(String(32))
    secondary_phone: Mapped[Optional[str]] = mapped_column(String(32))
    primary_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    secondary_email: Mapped[Optional[str]] = mapped_column(String(255))

    # ------------------------------------------------------------------
    # Address
    # ------------------------------------------------------------------

    country: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    city: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    district: Mapped[Optional[str]] = mapped_column(String(128))
    address: Mapped[Optional[str]] = mapped_column(Text)
    # 6 decimal places ≈ 0.1 m precision — same scale as warehouses.
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    preferred_language: Mapped[Optional[str]] = mapped_column(
        String(8)  # BCP-47 language tag, e.g. "ar", "en"
    )

    # ------------------------------------------------------------------
    # Operational state
    # ------------------------------------------------------------------

    status: Mapped[CustomerStatus] = mapped_column(
        SAEnum(CustomerStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=CustomerStatus.ACTIVE,
        index=True,
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=RiskLevel.LOW,
    )
    credit_status: Mapped[CreditStatus] = mapped_column(
        SAEnum(CreditStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=CreditStatus.GOOD,
    )

    # ------------------------------------------------------------------
    # Free-form
    # ------------------------------------------------------------------

    notes: Mapped[Optional[str]] = mapped_column(Text)
    # JSONB array of strings; e.g. ["vip", "hazmat-certified"]
    tags: Mapped[Optional[List[str]]] = mapped_column(JSONB)

    # ------------------------------------------------------------------
    # Soft-delete extension (actor attribution beyond SoftDeleteMixin)
    # ------------------------------------------------------------------

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )

    # ------------------------------------------------------------------
    # Optimistic concurrency (ADR-004)
    # ------------------------------------------------------------------

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    __mapper_args__ = {"version_id_col": version}
