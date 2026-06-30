"""Repositories for the Compliance & Permits domain (Sprint 7).

Follow the established pattern: constructor takes ``Session``; never commit/
rollback; no FastAPI; no events; tenant-scoped reads via RLS; soft-delete aware.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.compliance import (
    AxleWeightProfile,
    ComplianceCheck,
    Escort,
    OperatorCertification,
    Permit,
    RouteRestriction,
)
from app.models.enums import (
    ComplianceCheckStatus,
    EscortStatus,
    OperatorCertificationStatus,
    PermitStatus,
    PermitType,
)
from app.repositories.errors import NotFoundError


def _coerce_uuid(value: Union[str, uuid.UUID]) -> Optional[uuid.UUID]:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class _BaseRepo:
    """Shared no-commit create/get/soft-delete plumbing."""

    model = None  # set by subclass

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **data):
        obj = self.model(**data)
        self._session.add(obj)
        return obj

    def update(self, obj, **data):
        for field, value in data.items():
            if value is not None:
                setattr(obj, field, value)
        return obj

    def get_by_id(self, obj_id: Union[str, uuid.UUID]):
        oid = _coerce_uuid(obj_id)
        if oid is None:
            return None
        return self._session.get(self.model, oid)

    def get_by_id_or_raise(self, obj_id: Union[str, uuid.UUID]):
        obj = self.get_by_id(obj_id)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} {obj_id} not found.")
        return obj

    def soft_delete(self, obj, *, deleted_by: Optional[uuid.UUID]):
        obj.soft_delete()
        obj.deleted_by = deleted_by
        return obj

    def restore(self, obj):
        obj.restore()
        obj.deleted_by = None
        return obj


class PermitRepository(_BaseRepo):
    model = Permit

    def get_by_number(self, permit_number: str) -> Optional[Permit]:
        stmt = select(Permit).where(
            Permit.permit_number == permit_number, Permit.deleted_at.is_(None)
        )
        return self._session.scalars(stmt).first()

    def get_active_permit_for_shipment(self, shipment_id: uuid.UUID) -> Optional[Permit]:
        stmt = select(Permit).where(
            Permit.shipment_id == shipment_id,
            Permit.status == PermitStatus.ACTIVE,
            Permit.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def get_active_permits_for_equipment(self, equipment_id: uuid.UUID) -> List[Permit]:
        stmt = select(Permit).where(
            Permit.equipment_id == equipment_id,
            Permit.status == PermitStatus.ACTIVE,
            Permit.deleted_at.is_(None),
        )
        return list(self._session.scalars(stmt).all())

    def list_permits(
        self,
        *,
        q: Optional[str] = None,
        status: Optional[PermitStatus] = None,
        permit_type: Optional[PermitType] = None,
        shipment_id: Optional[uuid.UUID] = None,
        equipment_id: Optional[uuid.UUID] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Permit], int]:
        stmt = select(Permit)
        if not include_deleted:
            stmt = stmt.where(Permit.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Permit.status == status)
        if permit_type is not None:
            stmt = stmt.where(Permit.permit_type == permit_type)
        if shipment_id is not None:
            stmt = stmt.where(Permit.shipment_id == shipment_id)
        if equipment_id is not None:
            stmt = stmt.where(Permit.equipment_id == equipment_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Permit.permit_number.ilike(pattern),
                    Permit.issuing_authority.ilike(pattern),
                    Permit.region.ilike(pattern),
                )
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Permit, sort_by, Permit.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class EscortRepository(_BaseRepo):
    model = Escort

    def get_active_escorts_for_shipment(self, shipment_id: uuid.UUID) -> List[Escort]:
        stmt = select(Escort).where(
            Escort.shipment_id == shipment_id,
            Escort.status.in_((EscortStatus.PLANNED, EscortStatus.SCHEDULED)),
            Escort.deleted_at.is_(None),
        )
        return list(self._session.scalars(stmt).all())

    def list_escorts(
        self,
        *,
        shipment_id: Optional[uuid.UUID] = None,
        status: Optional[EscortStatus] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Escort], int]:
        stmt = select(Escort)
        if not include_deleted:
            stmt = stmt.where(Escort.deleted_at.is_(None))
        if shipment_id is not None:
            stmt = stmt.where(Escort.shipment_id == shipment_id)
        if status is not None:
            stmt = stmt.where(Escort.status == status)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Escort, sort_by, Escort.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class RouteRestrictionRepository(_BaseRepo):
    model = RouteRestriction

    def get_route_restrictions(
        self, *, region: Optional[str] = None, active_only: bool = True
    ) -> List[RouteRestriction]:
        stmt = select(RouteRestriction).where(RouteRestriction.deleted_at.is_(None))
        if region is not None:
            stmt = stmt.where(RouteRestriction.region == region)
        if active_only:
            stmt = stmt.where(RouteRestriction.active.is_(True))
        return list(self._session.scalars(stmt).all())

    def list_restrictions(
        self,
        *,
        region: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[RouteRestriction], int]:
        stmt = select(RouteRestriction)
        if not include_deleted:
            stmt = stmt.where(RouteRestriction.deleted_at.is_(None))
        if region is not None:
            stmt = stmt.where(RouteRestriction.region == region)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(desc(RouteRestriction.created_at)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class AxleWeightProfileRepository(_BaseRepo):
    model = AxleWeightProfile

    def list_profiles(
        self,
        *,
        equipment_id: Optional[uuid.UUID] = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AxleWeightProfile], int]:
        stmt = select(AxleWeightProfile)
        if not include_deleted:
            stmt = stmt.where(AxleWeightProfile.deleted_at.is_(None))
        if equipment_id is not None:
            stmt = stmt.where(AxleWeightProfile.equipment_id == equipment_id)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(desc(AxleWeightProfile.created_at)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class ComplianceCheckRepository(_BaseRepo):
    model = ComplianceCheck

    def list_checks(
        self,
        *,
        shipment_id: Optional[uuid.UUID] = None,
        status: Optional[ComplianceCheckStatus] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[ComplianceCheck], int]:
        stmt = select(ComplianceCheck)
        if not include_deleted:
            stmt = stmt.where(ComplianceCheck.deleted_at.is_(None))
        if shipment_id is not None:
            stmt = stmt.where(ComplianceCheck.shipment_id == shipment_id)
        if status is not None:
            stmt = stmt.where(ComplianceCheck.status == status)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(ComplianceCheck, sort_by, ComplianceCheck.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total

    def list_failed_blocking_checks(self, shipment_id: uuid.UUID) -> List[ComplianceCheck]:
        stmt = select(ComplianceCheck).where(
            ComplianceCheck.shipment_id == shipment_id,
            ComplianceCheck.status == ComplianceCheckStatus.FAILED,
            ComplianceCheck.blocking.is_(True),
            ComplianceCheck.deleted_at.is_(None),
        )
        return list(self._session.scalars(stmt).all())


class OperatorCertificationRepository(_BaseRepo):
    model = OperatorCertification

    def get_valid_operator_certification(
        self, user_id: uuid.UUID, *, certification_type: Optional[str] = None
    ) -> Optional[OperatorCertification]:
        stmt = select(OperatorCertification).where(
            OperatorCertification.user_id == user_id,
            OperatorCertification.status == OperatorCertificationStatus.ACTIVE,
            OperatorCertification.deleted_at.is_(None),
        )
        if certification_type is not None:
            stmt = stmt.where(OperatorCertification.certification_type == certification_type)
        return self._session.scalars(stmt).first()

    def list_certifications(
        self,
        *,
        user_id: Optional[uuid.UUID] = None,
        status: Optional[OperatorCertificationStatus] = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[OperatorCertification], int]:
        stmt = select(OperatorCertification)
        if not include_deleted:
            stmt = stmt.where(OperatorCertification.deleted_at.is_(None))
        if user_id is not None:
            stmt = stmt.where(OperatorCertification.user_id == user_id)
        if status is not None:
            stmt = stmt.where(OperatorCertification.status == status)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(desc(OperatorCertification.created_at)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total
