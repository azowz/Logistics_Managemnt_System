"""Insurance API routes — policies & coverage rules (thin handlers, RBAC)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.pagination import Page
from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import InsurancePolicyStatus, InsurancePolicyType, UserRole
from app.schemas.insurance import (
    CoverageRuleCreate,
    CoverageRuleRead,
    CoverageRuleUpdate,
    InsurancePolicyCreate,
    InsurancePolicyListParams,
    InsurancePolicyRead,
    InsurancePolicyUpdate,
)
from app.services.insurance_service import InsuranceService

router = APIRouter(prefix="/insurance", tags=["insurance"])

_WRITE = (UserRole.ADMIN, UserRole.MANAGER)
_READ = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)


def _page(p) -> Page[InsurancePolicyRead]:
    return Page[InsurancePolicyRead](
        items=[InsurancePolicyRead.model_validate(x) for x in p.items],
        total=p.total,
        page=p.page,
        size=p.size,
        pages=p.pages,
    )


# --- policies (literal paths before /{id}) ---


@router.post(
    "/policies",
    response_model=InsurancePolicyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an insurance policy.",
)
def create_policy(
    payload: InsurancePolicyCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(
        InsuranceService(session).create_policy(**payload.model_dump())
    )


@router.get(
    "/policies/search", response_model=Page[InsurancePolicyRead], summary="Search policies."
)
def search_policies(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[InsurancePolicyStatus] = Query(default=None, alias="status"),
    policy_type: Optional[InsurancePolicyType] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ)),
) -> Page[InsurancePolicyRead]:
    params = InsurancePolicyListParams(
        q=q,
        status=status_filter,
        policy_type=policy_type,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return _page(InsuranceService(session).list_policies(params))


@router.get("/policies", response_model=Page[InsurancePolicyRead], summary="List policies.")
def list_policies(
    status_filter: Optional[InsurancePolicyStatus] = Query(default=None, alias="status"),
    policy_type: Optional[InsurancePolicyType] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ)),
) -> Page[InsurancePolicyRead]:
    params = InsurancePolicyListParams(
        status=status_filter,
        policy_type=policy_type,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return _page(InsuranceService(session).list_policies(params))


# --- coverage rules (literal, before /policies/{id}) ---


@router.post(
    "/coverage-rules",
    response_model=CoverageRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a coverage rule.",
)
def create_coverage_rule(
    payload: CoverageRuleCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> CoverageRuleRead:
    return CoverageRuleRead.model_validate(
        InsuranceService(session).create_coverage_rule(**payload.model_dump())
    )


@router.get(
    "/coverage-rules", response_model=list[CoverageRuleRead], summary="List coverage rules."
)
def list_coverage_rules(
    policy_id: Optional[uuid.UUID] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ)),
) -> list[CoverageRuleRead]:
    items, _ = InsuranceService(session).list_coverage_rules(policy_id=policy_id)
    return [CoverageRuleRead.model_validate(x) for x in items]


@router.patch(
    "/coverage-rules/{rule_id}", response_model=CoverageRuleRead, summary="Update a coverage rule."
)
def update_coverage_rule(
    rule_id: uuid.UUID,
    payload: CoverageRuleUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> CoverageRuleRead:
    return CoverageRuleRead.model_validate(
        InsuranceService(session).update_coverage_rule(
            rule_id, **payload.model_dump(exclude_unset=True)
        )
    )


# --- policy by id + lifecycle ---


@router.get("/policies/{policy_id}", response_model=InsurancePolicyRead, summary="Get a policy.")
def get_policy(
    policy_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(
        InsuranceService(session).get_policy(policy_id, include_deleted=include_deleted)
    )


@router.patch(
    "/policies/{policy_id}", response_model=InsurancePolicyRead, summary="Update a policy."
)
def update_policy(
    policy_id: uuid.UUID,
    payload: InsurancePolicyUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(
        InsuranceService(session).update_policy(policy_id, **payload.model_dump(exclude_unset=True))
    )


@router.post(
    "/policies/{policy_id}/activate",
    response_model=InsurancePolicyRead,
    summary="Activate a policy.",
)
def activate_policy(
    policy_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(InsuranceService(session).activate_policy(policy_id))


@router.post(
    "/policies/{policy_id}/suspend", response_model=InsurancePolicyRead, summary="Suspend a policy."
)
def suspend_policy(
    policy_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(InsuranceService(session).suspend_policy(policy_id))


@router.post(
    "/policies/{policy_id}/expire", response_model=InsurancePolicyRead, summary="Expire a policy."
)
def expire_policy(
    policy_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(InsuranceService(session).expire_policy(policy_id))


@router.post(
    "/policies/{policy_id}/cancel", response_model=InsurancePolicyRead, summary="Cancel a policy."
)
def cancel_policy(
    policy_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE)),
) -> InsurancePolicyRead:
    return InsurancePolicyRead.model_validate(InsuranceService(session).cancel_policy(policy_id))
