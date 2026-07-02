"""Customer API routes — thin HTTP handlers delegating to CustomerService.

All business logic lives in :class:`~app.services.customer_service.CustomerService`.
These handlers:
  * Extract and validate HTTP inputs (FastAPI / Pydantic).
  * Enforce RBAC via :func:`~app.core.security.require_roles`.
  * Translate domain exceptions to HTTP via the global exception handlers
    installed by :func:`~app.core.exceptions.install_exception_handlers`.
  * Return Pydantic response schemas.

Role permissions:
  * ADMIN + MANAGER → create, update, delete, restore, status changes
  * ADMIN + MANAGER + CLIENT → read, list, search
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
    CreditStatus,
    CustomerStatus,
    CustomerType,
    RiskLevel,
    UserRole,
)
from app.schemas.customer import (
    CustomerCreate,
    CustomerListParams,
    CustomerRead,
    CustomerStatusUpdate,
    CustomerUpdate,
)
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


# ---------------------------------------------------------------------------
# POST /customers — create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer.",
)
def create_customer(
    payload: CustomerCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> CustomerRead:
    """Register a new customer for the current tenant.

    ``code`` must be unique within the tenant. If ``commercial_registration``
    or ``vat_number`` are provided they must also be tenant-unique.
    Returns **409 Conflict** on a duplicate, **422** on validation failure.
    """
    svc = CustomerService(session)
    customer = svc.create_customer(**payload.model_dump())
    return CustomerRead.model_validate(customer)


# ---------------------------------------------------------------------------
# GET /customers/search — search before /{id} so the path wins
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=Page[CustomerRead],
    status_code=status.HTTP_200_OK,
    summary="Search customers with filters, sorting, and pagination.",
)
def search_customers(
    q: Optional[str] = Query(default=None, max_length=256, description="Search term."),
    status_filter: Optional[CustomerStatus] = Query(default=None, alias="status"),
    customer_type: Optional[CustomerType] = Query(default=None),
    risk_level: Optional[RiskLevel] = Query(default=None),
    credit_status: Optional[CreditStatus] = Query(default=None),
    country: Optional[str] = Query(default=None, max_length=128),
    city: Optional[str] = Query(default=None, max_length=128),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT)),
) -> Page[CustomerRead]:
    """Full-text + faceted search across the tenant's customer portfolio.

    The ``q`` parameter matches against company name, commercial name, customer
    code, primary email, and contact person (case-insensitive). All other query
    parameters act as filters and are AND-combined.
    """
    params = CustomerListParams(
        q=q,
        status=status_filter,
        customer_type=customer_type,
        risk_level=risk_level,
        credit_status=credit_status,
        country=country,
        city=city,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    svc = CustomerService(session)
    page_result = svc.list_customers(params)
    return Page[CustomerRead](
        items=[CustomerRead.model_validate(c) for c in page_result.items],
        total=page_result.total,
        page=page_result.page,
        size=page_result.size,
        pages=page_result.pages,
    )


# ---------------------------------------------------------------------------
# GET /customers — list
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=Page[CustomerRead],
    status_code=status.HTTP_200_OK,
    summary="List customers with optional filters, sorting, and pagination.",
)
def list_customers(
    status_filter: Optional[CustomerStatus] = Query(default=None, alias="status"),
    customer_type: Optional[CustomerType] = Query(default=None),
    risk_level: Optional[RiskLevel] = Query(default=None),
    credit_status: Optional[CreditStatus] = Query(default=None),
    country: Optional[str] = Query(default=None, max_length=128),
    city: Optional[str] = Query(default=None, max_length=128),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT)),
) -> Page[CustomerRead]:
    """Return a paginated list of customers visible to the current tenant."""
    params = CustomerListParams(
        status=status_filter,
        customer_type=customer_type,
        risk_level=risk_level,
        credit_status=credit_status,
        country=country,
        city=city,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    svc = CustomerService(session)
    page_result = svc.list_customers(params)
    return Page[CustomerRead](
        items=[CustomerRead.model_validate(c) for c in page_result.items],
        total=page_result.total,
        page=page_result.page,
        size=page_result.size,
        pages=page_result.pages,
    )


# ---------------------------------------------------------------------------
# GET /customers/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{customer_id}",
    response_model=CustomerRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a customer by ID.",
)
def get_customer(
    customer_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT)),
) -> CustomerRead:
    """Fetch a single customer; returns **404** when not found or soft-deleted."""
    svc = CustomerService(session)
    customer = svc.get_customer(customer_id, include_deleted=include_deleted)
    return CustomerRead.model_validate(customer)


# ---------------------------------------------------------------------------
# PATCH /customers/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/{customer_id}",
    response_model=CustomerRead,
    status_code=status.HTTP_200_OK,
    summary="Partially update a customer.",
)
def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> CustomerRead:
    """Apply a partial update to a customer.

    Only the provided fields are changed (PATCH semantics). Returns **409**
    on a uniqueness collision and **404** when the customer is not found.
    """
    svc = CustomerService(session)
    customer = svc.update_customer(customer_id, **payload.model_dump(exclude_unset=True))
    return CustomerRead.model_validate(customer)


# ---------------------------------------------------------------------------
# DELETE /customers/{id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a customer.",
)
def delete_customer(
    customer_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """Logically remove a customer (soft-delete). Data is retained for audit.

    Returns **404** when the customer is not found. Only ``ADMIN`` may delete.
    """
    svc = CustomerService(session)
    svc.delete_customer(customer_id)


# ---------------------------------------------------------------------------
# POST /customers/{id}/restore
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/restore",
    response_model=CustomerRead,
    status_code=status.HTTP_200_OK,
    summary="Restore a soft-deleted customer.",
)
def restore_customer(
    customer_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
) -> CustomerRead:
    """Undo a soft-delete, making the customer active again.

    Returns **404** when the customer does not exist, or **422** when it is
    not currently deleted.
    """
    svc = CustomerService(session)
    customer = svc.restore_customer(customer_id)
    return CustomerRead.model_validate(customer)


# ---------------------------------------------------------------------------
# POST /customers/{id}/activate
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/activate",
    response_model=CustomerRead,
    status_code=status.HTTP_200_OK,
    summary="Activate a suspended or inactive customer.",
)
def activate_customer(
    customer_id: uuid.UUID,
    payload: CustomerStatusUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> CustomerRead:
    """Transition the customer status to ``active``."""
    svc = CustomerService(session)
    customer = svc.activate_customer(customer_id, reason=payload.reason)
    return CustomerRead.model_validate(customer)


# ---------------------------------------------------------------------------
# POST /customers/{id}/suspend
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/suspend",
    response_model=CustomerRead,
    status_code=status.HTTP_200_OK,
    summary="Suspend an active customer.",
)
def suspend_customer(
    customer_id: uuid.UUID,
    payload: CustomerStatusUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> CustomerRead:
    """Transition the customer status to ``suspended``."""
    svc = CustomerService(session)
    customer = svc.suspend_customer(customer_id, reason=payload.reason)
    return CustomerRead.model_validate(customer)
