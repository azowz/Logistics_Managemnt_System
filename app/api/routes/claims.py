"""Claims API routes — claim workflow, damage reports, liability (thin, RBAC)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.pagination import Page
from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import ClaimStatus, ClaimType, UserRole
from app.schemas.insurance import (
    ClaimApprovalRequest,
    ClaimCreate,
    ClaimListParams,
    ClaimRead,
    ClaimRejectionRequest,
    ClaimSettlementRequest,
    ClaimStatusRequest,
    ClaimUpdate,
    DamageReportCreate,
    DamageReportRead,
    LiabilityRecordCreate,
    LiabilityRecordRead,
)
from app.services.claims_service import ClaimsService

router = APIRouter(prefix="/claims", tags=["claims"])

_WRITE = (UserRole.ADMIN, UserRole.MANAGER)
_READ = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)
_OVERRIDE = (UserRole.ADMIN,)  # approving above claimed amount / liability override


def _page(p) -> Page[ClaimRead]:
    return Page[ClaimRead](items=[ClaimRead.model_validate(x) for x in p.items],
                           total=p.total, page=p.page, size=p.size, pages=p.pages)


# --- create ---


@router.post("", response_model=ClaimRead, status_code=status.HTTP_201_CREATED, summary="Create a claim.")
def create_claim(payload: ClaimCreate, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).create_claim(**payload.model_dump()))


@router.get("/search", response_model=Page[ClaimRead], summary="Search claims.")
def search_claims(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[ClaimStatus] = Query(default=None, alias="status"),
    claim_type: Optional[ClaimType] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    equipment_id: Optional[uuid.UUID] = Query(default=None),
    policy_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[ClaimRead]:
    params = ClaimListParams(q=q, status=status_filter, claim_type=claim_type, shipment_id=shipment_id,
                             equipment_id=equipment_id, policy_id=policy_id, include_deleted=include_deleted,
                             sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    return _page(ClaimsService(session).list_claims(params))


@router.get("", response_model=Page[ClaimRead], summary="List claims.")
def list_claims(
    status_filter: Optional[ClaimStatus] = Query(default=None, alias="status"),
    claim_type: Optional[ClaimType] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    equipment_id: Optional[uuid.UUID] = Query(default=None),
    policy_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[ClaimRead]:
    params = ClaimListParams(status=status_filter, claim_type=claim_type, shipment_id=shipment_id,
                             equipment_id=equipment_id, policy_id=policy_id, include_deleted=include_deleted,
                             sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    return _page(ClaimsService(session).list_claims(params))


@router.get("/{claim_id}", response_model=ClaimRead, summary="Get a claim.")
def get_claim(claim_id: uuid.UUID, include_deleted: bool = Query(default=False),
              session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).get_claim(claim_id, include_deleted=include_deleted))


@router.patch("/{claim_id}", response_model=ClaimRead, summary="Update a claim.")
def update_claim(claim_id: uuid.UUID, payload: ClaimUpdate, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).update_claim(claim_id, **payload.model_dump(exclude_unset=True)))


@router.delete("/{claim_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft-delete a claim.")
def delete_claim(claim_id: uuid.UUID, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(UserRole.ADMIN))):
    ClaimsService(session).delete_claim(claim_id)


@router.post("/{claim_id}/restore", response_model=ClaimRead, summary="Restore a claim.")
def restore_claim(claim_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(UserRole.ADMIN))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).restore_claim(claim_id))


# --- lifecycle ---


@router.post("/{claim_id}/review", response_model=ClaimRead, summary="Submit a claim for review.")
def review_claim(claim_id: uuid.UUID, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).submit_claim_for_review(claim_id))


@router.post("/{claim_id}/approve", response_model=ClaimRead, summary="Approve a claim.")
def approve_claim(claim_id: uuid.UUID, payload: ClaimApprovalRequest, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    # Exceeding the claimed amount requires an ADMIN override.
    allow = payload.allow_override and current_user.role == UserRole.ADMIN
    return ClaimRead.model_validate(
        ClaimsService(session).approve_claim(claim_id, approved_amount=payload.approved_amount, allow_override=allow))


@router.post("/{claim_id}/reject", response_model=ClaimRead, summary="Reject a claim.")
def reject_claim(claim_id: uuid.UUID, payload: ClaimRejectionRequest, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).reject_claim(claim_id, reason=payload.reason))


@router.post("/{claim_id}/settle", response_model=ClaimRead, summary="Settle a claim.")
def settle_claim(claim_id: uuid.UUID, payload: ClaimSettlementRequest, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).settle_claim(claim_id, settlement_notes=payload.settlement_notes))


@router.post("/{claim_id}/close", response_model=ClaimRead, summary="Close a claim.")
def close_claim(claim_id: uuid.UUID, session: Session = Depends(get_session),
                current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).close_claim(claim_id))


@router.post("/{claim_id}/reopen", response_model=ClaimRead, summary="Reopen a closed claim.")
def reopen_claim(claim_id: uuid.UUID, payload: ClaimStatusRequest, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_WRITE))) -> ClaimRead:
    return ClaimRead.model_validate(ClaimsService(session).reopen_claim(claim_id, reason=payload.reason))


# --- damage reports ---


@router.post("/{claim_id}/damage-reports", response_model=DamageReportRead, status_code=status.HTTP_201_CREATED,
             summary="Add a damage report to a claim.")
def create_damage_report(claim_id: uuid.UUID, payload: DamageReportCreate, session: Session = Depends(get_session),
                         current_user=Depends(require_roles(*_WRITE))) -> DamageReportRead:
    return DamageReportRead.model_validate(ClaimsService(session).create_damage_report(claim_id, **payload.model_dump()))


@router.get("/{claim_id}/damage-reports", response_model=list[DamageReportRead], summary="List damage reports.")
def list_damage_reports(claim_id: uuid.UUID, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_READ))) -> list[DamageReportRead]:
    return [DamageReportRead.model_validate(x) for x in ClaimsService(session).list_damage_reports(claim_id)]


# --- liability records ---


@router.post("/{claim_id}/liability-records", response_model=LiabilityRecordRead, status_code=status.HTTP_201_CREATED,
             summary="Add a liability record to a claim.")
def create_liability_record(claim_id: uuid.UUID, payload: LiabilityRecordCreate, session: Session = Depends(get_session),
                            current_user=Depends(require_roles(*_WRITE))) -> LiabilityRecordRead:
    data = payload.model_dump()
    allow_override = data.pop("allow_override", False) and current_user.role == UserRole.ADMIN
    return LiabilityRecordRead.model_validate(
        ClaimsService(session).create_liability_record(claim_id, allow_override=allow_override, **data))


@router.get("/{claim_id}/liability-records", response_model=list[LiabilityRecordRead], summary="List liability records.")
def list_liability_records(claim_id: uuid.UUID, session: Session = Depends(get_session),
                           current_user=Depends(require_roles(*_READ))) -> list[LiabilityRecordRead]:
    return [LiabilityRecordRead.model_validate(x) for x in ClaimsService(session).list_liability_records(claim_id)]
