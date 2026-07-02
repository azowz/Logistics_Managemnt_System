"""Repository for the Order aggregate.

Follows the Sprint 3 ``CustomerRepository`` pattern:
  * Constructor takes ``Session``; no lifecycle management.
  * Never commits — the calling service owns the unit of work.
  * RLS scopes every query to the current tenant via the ``after_begin`` GUC
    listener (``app.db.session``).
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import (
    OrderPriority,
    OrderSource,
    OrderStatus,
    OrderType,
)
from app.models.order import Order
from app.repositories.errors import NotFoundError


class OrderRepository:
    """Persistence boundary for the Order aggregate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations (no commit — caller commits)
    # ------------------------------------------------------------------

    def create(self, **data) -> Order:
        """Instantiate and stage a new Order; caller must commit."""
        order = Order(**data)
        self._session.add(order)
        return order

    def update(self, order: Order, **data) -> Order:
        """Apply non-None field updates to an existing Order in-place."""
        for field, value in data.items():
            if value is not None:
                setattr(order, field, value)
        return order

    # ------------------------------------------------------------------
    # Lookup by primary key
    # ------------------------------------------------------------------

    def get_by_id(self, order_id: uuid.UUID) -> Optional[Order]:
        """Return an order by PK, or ``None`` if not found."""
        return self._session.get(Order, order_id)

    def get_by_id_or_raise(self, order_id: uuid.UUID) -> Order:
        """Return an order by PK, raising :exc:`NotFoundError` if absent."""
        order = self.get_by_id(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found.")
        return order

    # ------------------------------------------------------------------
    # Uniqueness guard (tenant-scoped)
    # ------------------------------------------------------------------

    def get_by_order_number(self, order_number: str) -> Optional[Order]:
        """Return the order with the given number in the current tenant."""
        stmt = select(Order).where(
            Order.order_number == order_number.upper(),
            Order.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    # ------------------------------------------------------------------
    # Listing with filtering, sorting, pagination
    # ------------------------------------------------------------------

    def list_orders(
        self,
        *,
        q: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        order_type: Optional[OrderType] = None,
        order_source: Optional[OrderSource] = None,
        priority: Optional[OrderPriority] = None,
        customer_id: Optional[uuid.UUID] = None,
        assigned_dispatcher_id: Optional[uuid.UUID] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Order], int]:
        """Return ``(items, total)`` honouring all filters, sort, and pagination.

        ``total`` counts ALL matching rows (ignoring limit/offset) so callers can
        build the :class:`~app.common.pagination.Page` envelope.
        """
        stmt = select(Order)

        if not include_deleted:
            stmt = stmt.where(Order.deleted_at.is_(None))

        if status is not None:
            stmt = stmt.where(Order.status == status)
        if order_type is not None:
            stmt = stmt.where(Order.order_type == order_type)
        if order_source is not None:
            stmt = stmt.where(Order.order_source == order_source)
        if priority is not None:
            stmt = stmt.where(Order.priority == priority)
        if customer_id is not None:
            stmt = stmt.where(Order.customer_id == customer_id)
        if assigned_dispatcher_id is not None:
            stmt = stmt.where(Order.assigned_dispatcher_id == assigned_dispatcher_id)

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Order.order_number.ilike(pattern),
                    Order.cargo_description.ilike(pattern),
                    Order.special_instructions.ilike(pattern),
                    Order.pickup_location.ilike(pattern),
                    Order.delivery_location.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = self._session.scalar(count_stmt) or 0

        col = getattr(Order, sort_by, Order.created_at)
        order_fn = asc if sort_dir == "asc" else desc
        stmt = stmt.order_by(order_fn(col))

        stmt = stmt.limit(limit).offset(offset)
        items = list(self._session.scalars(stmt).all())
        return items, total

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def soft_delete(self, order: Order, *, deleted_by: Optional[uuid.UUID]) -> Order:
        """Mark an order as soft-deleted; caller must commit."""
        order.soft_delete()  # sets deleted_at via SoftDeleteMixin
        order.deleted_by = deleted_by
        return order

    def restore(self, order: Order) -> Order:
        """Clear soft-delete markers; caller must commit."""
        order.restore()  # clears deleted_at via SoftDeleteMixin
        order.deleted_by = None
        return order
