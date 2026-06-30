"""Compliance & Permits API routes — thin handlers over ComplianceService.

Literal paths are declared before dynamic ``{id}`` paths. RBAC via require_roles;
domain exceptions are translated centrally. No business logic in routes.
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
    ComplianceCheckStatus,
    EscortStatus,
    PermitStatus,
    PermitType,
    UserRole,
)
from app.schemas.compliance import (
    AxleWeightProfileCreate,
    AxleWeightProfileRead,
    ComplianceCheckCreate,
    ComplianceCheckListParams,
    ComplianceCheckRead,
    ComplianceOverrideRequest,
    DispatchGateResult,
    EscortCreate,
    EscortListParams,
    EscortRead,
    EscortScheduleRequest,
    OperatorCertificationCreate,
    OperatorCertificationRead,
    PermitCreate,
    PermitListParams,
    PermitRead,
    PermitStatusRequest,
    PermitUpdate,
    RouteRestrictionCreate,
    RouteRestrictionRead,
    RouteRestrictionUpdate,
)
from app.services.compliance_service import ComplianceService

router = APIRouter(prefix="/compliance", tags=["compliance"])

_WRITE = (UserRole.ADMIN, UserRole.MANAGER)
_READ = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)
_OVERRIDE = (UserRole.ADMIN, UserRole.MANAGER)


# ===================== Permits =====================


@router.post("/permits", response_model=PermitRead, status_code=status.HTTP_201_CREATED,
             summary="Create a permit (draft).")
def create_permit(payload: PermitCreate, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).create_permit(**payload.model_dump()))


@router.get("/permits/search", response_model=Page[PermitRead], summary="Search permits.")
def search_permits(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[PermitStatus] = Query(default=None, alias="status"),
    permit_type: Optional[PermitType] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    equipment_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[PermitRead]:
    params = PermitListParams(q=q, status=status_filter, permit_type=permit_type,
                              shipment_id=shipment_id, equipment_id=equipment_id,
                              include_deleted=include_deleted, sort_by=sort_by, sort_dir=sort_dir,
                              page=page, size=size)
    return _permit_page(ComplianceService(session).list_permits(params))


@router.get("/permits", response_model=Page[PermitRead], summary="List permits.")
def list_permits(
    status_filter: Optional[PermitStatus] = Query(default=None, alias="status"),
    permit_type: Optional[PermitType] = Query(default=None),
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    equipment_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[PermitRead]:
    params = PermitListParams(status=status_filter, permit_type=permit_type,
                              shipment_id=shipment_id, equipment_id=equipment_id,
                              include_deleted=include_deleted, sort_by=sort_by, sort_dir=sort_dir,
                              page=page, size=size)
    return _permit_page(ComplianceService(session).list_permits(params))


def _permit_page(p) -> Page[PermitRead]:
    return Page[PermitRead](items=[PermitRead.model_validate(x) for x in p.items],
                            total=p.total, page=p.page, size=p.size, pages=p.pages)


@router.get("/permits/{permit_id}", response_model=PermitRead, summary="Get a permit.")
def get_permit(permit_id: uuid.UUID, include_deleted: bool = Query(default=False),
               session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).get_permit(permit_id, include_deleted=include_deleted))


@router.patch("/permits/{permit_id}", response_model=PermitRead, summary="Update a permit.")
def update_permit(permit_id: uuid.UUID, payload: PermitUpdate, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).update_permit(permit_id, **payload.model_dump(exclude_unset=True)))


@router.delete("/permits/{permit_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft-delete a permit.")
def delete_permit(permit_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(UserRole.ADMIN))):
    ComplianceService(session).delete_permit(permit_id)


@router.post("/permits/{permit_id}/submit", response_model=PermitRead, summary="Submit a permit.")
def submit_permit(permit_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).submit_permit(permit_id))


@router.post("/permits/{permit_id}/review", response_model=PermitRead, summary="Mark a permit under review.")
def review_permit(permit_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).mark_under_review(permit_id))


@router.post("/permits/{permit_id}/approve", response_model=PermitRead, summary="Approve a permit.")
def approve_permit(permit_id: uuid.UUID, payload: PermitStatusRequest, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(
        ComplianceService(session).approve_permit(permit_id, valid_from=payload.valid_from, valid_until=payload.valid_until))


@router.post("/permits/{permit_id}/reject", response_model=PermitRead, summary="Reject a permit.")
def reject_permit(permit_id: uuid.UUID, payload: PermitStatusRequest, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).reject_permit(permit_id, reason=payload.reason))


@router.post("/permits/{permit_id}/activate", response_model=PermitRead, summary="Activate a permit.")
def activate_permit(permit_id: uuid.UUID, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).activate_permit(permit_id))


@router.post("/permits/{permit_id}/expire", response_model=PermitRead, summary="Expire a permit.")
def expire_permit(permit_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).expire_permit(permit_id))


@router.post("/permits/{permit_id}/cancel", response_model=PermitRead, summary="Cancel a permit.")
def cancel_permit(permit_id: uuid.UUID, payload: PermitStatusRequest, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).cancel_permit(permit_id, reason=payload.reason))


@router.post("/permits/{permit_id}/restore", response_model=PermitRead, summary="Restore a permit.")
def restore_permit(permit_id: uuid.UUID, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(UserRole.ADMIN))) -> PermitRead:
    return PermitRead.model_validate(ComplianceService(session).restore_permit(permit_id))


# ===================== Compliance checks =====================


@router.post("/checks/evaluate", response_model=list[ComplianceCheckRead], status_code=status.HTTP_201_CREATED,
             summary="Evaluate compliance for a shipment.")
def evaluate_checks(payload: ComplianceCheckCreate, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_WRITE))) -> list[ComplianceCheckRead]:
    checks = ComplianceService(session).evaluate_compliance(shipment_id=payload.shipment_id)
    return [ComplianceCheckRead.model_validate(c) for c in checks]


@router.get("/checks", response_model=Page[ComplianceCheckRead], summary="List compliance checks.")
def list_checks(
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    status_filter: Optional[ComplianceCheckStatus] = Query(default=None, alias="status"),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[ComplianceCheckRead]:
    params = ComplianceCheckListParams(shipment_id=shipment_id, status=status_filter,
                                       include_deleted=include_deleted, sort_by=sort_by, sort_dir=sort_dir,
                                       page=page, size=size)
    p = ComplianceService(session).list_checks(params)
    return Page[ComplianceCheckRead](items=[ComplianceCheckRead.model_validate(x) for x in p.items],
                                     total=p.total, page=p.page, size=p.size, pages=p.pages)


@router.get("/checks/{check_id}", response_model=ComplianceCheckRead, summary="Get a compliance check.")
def get_check(check_id: uuid.UUID, session: Session = Depends(get_session),
              current_user=Depends(require_roles(*_READ))) -> ComplianceCheckRead:
    return ComplianceCheckRead.model_validate(ComplianceService(session).get_check(check_id))


@router.post("/checks/{check_id}/override", response_model=ComplianceCheckRead, summary="Override a compliance check.")
def override_check(check_id: uuid.UUID, payload: ComplianceOverrideRequest, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_OVERRIDE))) -> ComplianceCheckRead:
    return ComplianceCheckRead.model_validate(ComplianceService(session).apply_compliance_override(check_id, reason=payload.reason))


# ===================== Escorts =====================


@router.post("/escorts", response_model=EscortRead, status_code=status.HTTP_201_CREATED, summary="Create an escort.")
def create_escort(payload: EscortCreate, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> EscortRead:
    return EscortRead.model_validate(ComplianceService(session).create_escort(**payload.model_dump()))


@router.get("/escorts", response_model=Page[EscortRead], summary="List escorts.")
def list_escorts(
    shipment_id: Optional[uuid.UUID] = Query(default=None),
    status_filter: Optional[EscortStatus] = Query(default=None, alias="status"),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[EscortRead]:
    params = EscortListParams(shipment_id=shipment_id, status=status_filter, include_deleted=include_deleted,
                              sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    p = ComplianceService(session).list_escorts(params)
    return Page[EscortRead](items=[EscortRead.model_validate(x) for x in p.items],
                            total=p.total, page=p.page, size=p.size, pages=p.pages)


@router.post("/escorts/{escort_id}/schedule", response_model=EscortRead, summary="Schedule an escort.")
def schedule_escort(escort_id: uuid.UUID, payload: EscortScheduleRequest, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_WRITE))) -> EscortRead:
    return EscortRead.model_validate(
        ComplianceService(session).schedule_escort(escort_id, scheduled_start=payload.scheduled_start, scheduled_end=payload.scheduled_end))


@router.post("/escorts/{escort_id}/cancel", response_model=EscortRead, summary="Cancel an escort.")
def cancel_escort(escort_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_WRITE))) -> EscortRead:
    return EscortRead.model_validate(ComplianceService(session).cancel_escort(escort_id))


# ===================== Route restrictions =====================


@router.post("/route-restrictions", response_model=RouteRestrictionRead, status_code=status.HTTP_201_CREATED,
             summary="Create a route restriction.")
def create_restriction(payload: RouteRestrictionCreate, session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_WRITE))) -> RouteRestrictionRead:
    return RouteRestrictionRead.model_validate(ComplianceService(session).create_route_restriction(**payload.model_dump()))


@router.get("/route-restrictions", response_model=list[RouteRestrictionRead], summary="List route restrictions.")
def list_restrictions(region: Optional[str] = Query(default=None), session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_READ))) -> list[RouteRestrictionRead]:
    items, _ = ComplianceService(session).list_route_restrictions(region=region)
    return [RouteRestrictionRead.model_validate(x) for x in items]


@router.patch("/route-restrictions/{restriction_id}", response_model=RouteRestrictionRead,
              summary="Update a route restriction.")
def update_restriction(restriction_id: uuid.UUID, payload: RouteRestrictionUpdate, session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_WRITE))) -> RouteRestrictionRead:
    return RouteRestrictionRead.model_validate(
        ComplianceService(session).update_route_restriction(restriction_id, **payload.model_dump(exclude_unset=True)))


# ===================== Axle weight profiles =====================


@router.post("/axle-weight-profiles", response_model=AxleWeightProfileRead, status_code=status.HTTP_201_CREATED,
             summary="Create an axle-weight profile.")
def create_axle_profile(payload: AxleWeightProfileCreate, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_WRITE))) -> AxleWeightProfileRead:
    return AxleWeightProfileRead.model_validate(ComplianceService(session).create_axle_weight_profile(**payload.model_dump()))


# ===================== Operator certifications =====================


@router.post("/operator-certifications", response_model=OperatorCertificationRead, status_code=status.HTTP_201_CREATED,
             summary="Create an operator certification.")
def create_certification(payload: OperatorCertificationCreate, session: Session = Depends(get_session),
                         current_user=Depends(require_roles(*_WRITE))) -> OperatorCertificationRead:
    return OperatorCertificationRead.model_validate(ComplianceService(session).create_operator_certification(**payload.model_dump()))


@router.get("/operator-certifications", response_model=list[OperatorCertificationRead],
            summary="List operator certifications.")
def list_certifications(user_id: Optional[uuid.UUID] = Query(default=None), session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_READ))) -> list[OperatorCertificationRead]:
    items, _ = ComplianceService(session).list_certifications(user_id=user_id)
    return [OperatorCertificationRead.model_validate(x) for x in items]


@router.post("/operator-certifications/{certification_id}/expire", response_model=OperatorCertificationRead,
             summary="Expire an operator certification.")
def expire_certification(certification_id: uuid.UUID, session: Session = Depends(get_session),
                         current_user=Depends(require_roles(*_WRITE))) -> OperatorCertificationRead:
    return OperatorCertificationRead.model_validate(ComplianceService(session).expire_operator_certification(certification_id))
