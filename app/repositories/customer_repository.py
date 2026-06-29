"""Repository for the Customer aggregate.

Follows the established pattern (see ``ShipmentRepository``):
  * Constructor takes ``Session``; no lifecycle management.
  * Never commits — the calling service owns the unit of work.
  * RLS scopes every query to the current tenant automatically via the
    ``after_begin`` GUC listener (``app.db.session``).
  * Intention-revealing method names; complex queries are built inline.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import (
    CreditStatus,
    CustomerStatus,
    CustomerType,
    RiskLevel,
)
from app.repositories.errors import NotFoundError


class CustomerRepository:
    """Persistence boundary for the Customer aggregate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations (no commit — caller commits)
    # ------------------------------------------------------------------

    def create(self, **data) -> Customer:
        """Instantiate and stage a new Customer; caller must commit."""
        customer = Customer(**data)
        self._session.add(customer)
        return customer

    def update(self, customer: Customer, **data) -> Customer:
        """Apply a dict of field updates to an existing Customer in-place.

        Ignores keys that are ``None`` so partial PATCH semantics work
        without overwriting existing values with null.
        """
        for field, value in data.items():
            if value is not None:
                setattr(customer, field, value)
        return customer

    # ------------------------------------------------------------------
    # Lookup by primary key
    # ------------------------------------------------------------------

    def get_by_id(self, customer_id: uuid.UUID) -> Optional[Customer]:
        """Return a customer by PK, or ``None`` if not found."""
        return self._session.get(Customer, customer_id)

    def get_by_id_or_raise(self, customer_id: uuid.UUID) -> Customer:
        """Return a customer by PK, raising :exc:`NotFoundError` if absent."""
        customer = self.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} not found.")
        return customer

    # ------------------------------------------------------------------
    # Uniqueness guards (tenant-scoped; used by service validation)
    # ------------------------------------------------------------------

    def get_by_code(self, code: str) -> Optional[Customer]:
        """Return the customer with the given code in the current tenant."""
        stmt = select(Customer).where(
            Customer.code == code.upper(),
            Customer.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def get_by_commercial_registration(
        self, commercial_registration: str
    ) -> Optional[Customer]:
        """Return a customer matching the commercial registration, or ``None``."""
        stmt = select(Customer).where(
            Customer.commercial_registration == commercial_registration,
            Customer.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def get_by_vat_number(self, vat_number: str) -> Optional[Customer]:
        """Return a customer matching the VAT number, or ``None``."""
        stmt = select(Customer).where(
            Customer.vat_number == vat_number,
            Customer.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    # ------------------------------------------------------------------
    # Listing with filtering, sorting, pagination
    # ------------------------------------------------------------------

    def list_customers(
        self,
        *,
        q: Optional[str] = None,
        status: Optional[CustomerStatus] = None,
        customer_type: Optional[CustomerType] = None,
        risk_level: Optional[RiskLevel] = None,
        credit_status: Optional[CreditStatus] = None,
        country: Optional[str] = None,
        city: Optional[str] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Customer], int]:
        """Return ``(items, total)`` honouring all filters, sort, and pagination.

        ``total`` is the count of ALL matching rows (ignoring limit/offset) so
        callers can build the :class:`~app.common.pagination.Page` envelope.
        """
        stmt = select(Customer)

        # Soft-delete filter.
        if not include_deleted:
            stmt = stmt.where(Customer.deleted_at.is_(None))

        # Enum filters.
        if status is not None:
            stmt = stmt.where(Customer.status == status)
        if customer_type is not None:
            stmt = stmt.where(Customer.customer_type == customer_type)
        if risk_level is not None:
            stmt = stmt.where(Customer.risk_level == risk_level)
        if credit_status is not None:
            stmt = stmt.where(Customer.credit_status == credit_status)
        if country is not None:
            stmt = stmt.where(Customer.country == country)
        if city is not None:
            stmt = stmt.where(Customer.city == city)

        # Free-text search (case-insensitive ilike across key fields).
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Customer.company_name.ilike(pattern),
                    Customer.commercial_name.ilike(pattern),
                    Customer.code.ilike(pattern),
                    Customer.primary_email.ilike(pattern),
                    Customer.contact_person.ilike(pattern),
                )
            )

        # Count before pagination.
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = self._session.scalar(count_stmt) or 0

        # Sorting (whitelist enforced at schema layer).
        col = getattr(Customer, sort_by, Customer.created_at)
        order_fn = asc if sort_dir == "asc" else desc
        stmt = stmt.order_by(order_fn(col))

        # Pagination.
        stmt = stmt.limit(limit).offset(offset)

        items = list(self._session.scalars(stmt).all())
        return items, total

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def soft_delete(
        self, customer: Customer, *, deleted_by: Optional[uuid.UUID]
    ) -> Customer:
        """Mark a customer as soft-deleted; caller must commit."""
        customer.soft_delete()  # sets deleted_at via SoftDeleteMixin
        customer.deleted_by = deleted_by
        return customer

    def restore(self, customer: Customer) -> Customer:
        """Clear soft-delete markers; caller must commit."""
        customer.restore()  # clears deleted_at via SoftDeleteMixin
        customer.deleted_by = None
        return customer
