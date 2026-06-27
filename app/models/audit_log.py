"""Immutable audit log (``docs/03`` §6, audit layers 2 & 3).

A single append-only table capturing *who changed what, when, and the before/after*.
It serves two complementary roles:

* **Layer 2 — row history:** generic INSERT/UPDATE/DELETE captures (``action`` ∈
  ``I``/``U``/``D``) intended to be written by an ``AFTER`` row trigger once the
  trigger function + non-superuser role land (deferred; see ``docs/10`` R-1).
* **Layer 3 — domain audit:** every domain event is also reflected here
  (``action = 'E'``) by the event-append path (M2), linking ``event_id`` and the
  acting ``actor_user_id`` (from ``app.current_user_id``) to the aggregate row.

Append-only and tenant-scoped (RLS). Kept in the default schema for M2 (the
dedicated ``audit`` schema in ``docs/03`` §6 is an organizational refinement
deferred with the trigger/role work).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.uuidv7 import uuid7


class AuditLog(Base):
    """Append-only audit record: actor, action, target row, before/after state."""

    __tablename__ = "audit_log"
    __table_args__ = (
        # Short logical name -> expanded to ``ck_audit_log_action`` by convention.
        CheckConstraint("action IN ('I','U','D','E')", name="action"),
        Index("ix_audit_log_tenant_table_row_at", "tenant_id", "table_name", "row_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # I | U | D | E
    old_row: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_row: Mapped[Optional[dict]] = mapped_column(JSONB)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    # Links a layer-3 (action='E') audit row to its originating domain event.
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    txid: Mapped[Optional[int]] = mapped_column(BigInteger)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only.
        return f"<AuditLog {self.action} {self.table_name}:{self.row_id!s} at={self.at!s}>"


__all__ = ["AuditLog"]
