"""Order API routes — thin HTTP handlers delegating to OrderService.

All business logic lives in :class:`~app.services.order_service.OrderService`.
These handlers extract/validate HTTP inputs, enforce RBAC via
:func:`~app.core.security.require_roles`, and let the global exception handlers
(installed by :func:`~app.core.exceptions.install_exception_handlers`) translate
domain exceptions to HTTP responses.

Role permissions:
  * ADMIN, MANAGER                       → create / update / lifecycle ops
  * ADMIN, MANAGER, DRIVER               → start-transit / deliver / fail
  * ADMIN, MANAGER, CLIENT, DRIVER       → read / list / search
  * ADMIN                                → delete / restore
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
    OrderPriority,
    OrderSource,
    OrderStatus,
    OrderType,
    UserRole,
)
from app.schemas.order import (
    OrderAssignRequest,
    OrderCreate,
    OrderListParams,
    OrderRead,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])

# Role bundles reused across handlers.
_WRITE_ROLES = (UserRole.ADMIN, UserRole.MANAGER)
_FIELD_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.DRIVER)
_READ_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)


def _to_page(page_result) -> Page[OrderRead]:
    """Map a service Page[Order] to a Page[OrderRead] response envelope."""
    return Page[OrderRead](
        items=[OrderRead.model_validate(o) for o in page_result.items],
        total=page_result.total,
        page=page_result.page,
        size=page_result.size,
        pages=page_result.pages,
    )


# ---------------------------------------------------------------------------
# POST /orders — create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order (starts in draft).",
)
def create_order(
    payload: OrderCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """Create a new order for the current tenant.

    The owning ``customer_id`` must exist. ``order_number`` must be tenant-unique
    (auto-generated when omitted). Returns **409** on a duplicate number and
    **422** when the customer does not exist or validation fails.
    """
    svc = OrderService(session)
    order = svc.create_order(**payload.model_dump())
    return OrderRead.model_validate(order)


# ---------------------------------------------------------------------------
# GET /orders/search — declared before /{id} so the literal path wins
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=Page[OrderRead],
    status_code=status.HTTP_200_OK,
    summary="Search orders with filters, sorting, and pagination.",
)
def search_orders(
    q: Optional[str] = Query(default=None, max_length=256, description="Search term."),
    status_filter: Optional[OrderStatus] = Query(default=None, alias="status"),
    order_type: Optional[OrderType] = Query(default=None),
    order_source: Optional[OrderSource] = Query(default=None),
    priority: Optional[OrderPriority] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    assigned_dispatcher_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> Page[OrderRead]:
    """Full-text + faceted search across the tenant's orders.

    ``q`` matches order number, cargo description, special instructions, and
    pickup/delivery locations (case-insensitive). All other parameters are
    AND-combined filters.
    """
    params = OrderListParams(
        q=q,
        status=status_filter,
        order_type=order_type,
        order_source=order_source,
        priority=priority,
        customer_id=customer_id,
        assigned_dispatcher_id=assigned_dispatcher_id,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    svc = OrderService(session)
    return _to_page(svc.list_orders(params))


# ---------------------------------------------------------------------------
# GET /orders — list
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=Page[OrderRead],
    status_code=status.HTTP_200_OK,
    summary="List orders with optional filters, sorting, and pagination.",
)
def list_orders(
    status_filter: Optional[OrderStatus] = Query(default=None, alias="status"),
    order_type: Optional[OrderType] = Query(default=None),
    order_source: Optional[OrderSource] = Query(default=None),
    priority: Optional[OrderPriority] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    assigned_dispatcher_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> Page[OrderRead]:
    """Return a paginated list of orders visible to the current tenant."""
    params = OrderListParams(
        status=status_filter,
        order_type=order_type,
        order_source=order_source,
        priority=priority,
        customer_id=customer_id,
        assigned_dispatcher_id=assigned_dispatcher_id,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    svc = OrderService(session)
    return _to_page(svc.list_orders(params))


# ---------------------------------------------------------------------------
# GET /orders/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{order_id}",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an order by ID.",
)
def get_order(
    order_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> OrderRead:
    """Fetch a single order; returns **404** when not found or soft-deleted."""
    svc = OrderService(session)
    order = svc.get_order(order_id, include_deleted=include_deleted)
    return OrderRead.model_validate(order)


# ---------------------------------------------------------------------------
# PATCH /orders/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/{order_id}",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Partially update an order.",
)
def update_order(
    order_id: uuid.UUID,
    payload: OrderUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """Apply a partial update. Terminal orders cannot be edited (**422**)."""
    svc = OrderService(session)
    order = svc.update_order(order_id, **payload.model_dump(exclude_unset=True))
    return OrderRead.model_validate(order)


# ---------------------------------------------------------------------------
# DELETE /orders/{id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an order.",
)
def delete_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """Logically remove an order (soft-delete). Returns **404** when not found."""
    svc = OrderService(session)
    svc.delete_order(order_id)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


@router.post(
    "/{order_id}/submit",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Submit a draft order for approval.",
)
def submit_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """draft → submitted."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.submit_order(order_id))


@router.post(
    "/{order_id}/approve",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Approve a submitted order.",
)
def approve_order(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """submitted → approved."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.approve_order(order_id, reason=payload.reason))


@router.post(
    "/{order_id}/schedule",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Schedule an approved order.",
)
def schedule_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """approved → scheduled."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.schedule_order(order_id))


@router.post(
    "/{order_id}/assign",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Assign a scheduled order to a dispatcher.",
)
def assign_order(
    order_id: uuid.UUID,
    payload: OrderAssignRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """scheduled → assigned."""
    svc = OrderService(session)
    order = svc.assign_order(
        order_id,
        assigned_dispatcher_id=payload.assigned_dispatcher_id,
        reason=payload.reason,
    )
    return OrderRead.model_validate(order)


@router.post(
    "/{order_id}/start-transit",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Mark cargo picked up; begin transit.",
)
def start_transit_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> OrderRead:
    """assigned → in_transit (emits OrderPickedUp + OrderInTransit)."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.start_transit_order(order_id))


@router.post(
    "/{order_id}/deliver",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Mark an in-transit order delivered.",
)
def deliver_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> OrderRead:
    """in_transit → delivered."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.deliver_order(order_id))


@router.post(
    "/{order_id}/cancel",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Cancel an order (compensation flagged when in progress).",
)
def cancel_order(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> OrderRead:
    """any non-terminal → cancelled."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.cancel_order(order_id, reason=payload.reason))


@router.post(
    "/{order_id}/fail",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Mark an order as failed.",
)
def fail_order(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> OrderRead:
    """non-terminal → failed."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.fail_order(order_id, reason=payload.reason))


@router.post(
    "/{order_id}/restore",
    response_model=OrderRead,
    status_code=status.HTTP_200_OK,
    summary="Restore a soft-deleted order.",
)
def restore_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
) -> OrderRead:
    """Undo a soft-delete. **404** when missing, **422** when not deleted."""
    svc = OrderService(session)
    return OrderRead.model_validate(svc.restore_order(order_id))
