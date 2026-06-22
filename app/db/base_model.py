"""Abstract declarative base model for FUTURE persistence models.

This module introduces :class:`BaseModel`, an abstract SQLAlchemy model that
supplies a time-ordered UUIDv7 primary key. It is intended for models created
*after* the foundation is in place. EXISTING models in ``app.models`` define
their own ``id`` (uuid4) and must NOT be retrofitted onto this base — doing so
would alter their primary-key defaults and break migrations.

Mixins such as :class:`app.db.mixins.TimestampMixin`,
:class:`app.db.mixins.SoftDeleteMixin`, :class:`app.db.mixins.AuditMixin`, and
:class:`app.db.mixins.TenantMixin` are intentionally NOT baked into this base
so that each future model can opt into exactly the cross-cutting columns it
needs.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.uuidv7 import uuid7


class BaseModel(Base):
    """Abstract base providing a time-ordered UUIDv7 primary key.

    ``__abstract__ = True`` ensures SQLAlchemy creates no table for this class;
    it only contributes the shared ``id`` column to concrete subclasses.
    """

    __abstract__ = True

    # ``as_uuid=True`` returns native :class:`uuid.UUID` instances. The default
    # is generated client-side via :func:`app.db.uuidv7.uuid7` so identifiers
    # are known before flush and remain time-ordered for index locality.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid7,
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only.
        """Return a concise, unambiguous representation for logs/REPL."""
        return f"<{type(self).__name__} id={self.id!s}>"


__all__ = ["BaseModel"]
