"""Repositories for the Insurance & Claims domain (Sprint 8).

Constructor takes ``Session``; never commit/rollback; no FastAPI; no events;
tenant-scoped reads via RLS; soft-delete aware.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import (
    InsurancePolicyStatus,
)
from app.models.insurance import (
    Claim,
    CoverageRule,
    DamageReport,
    InsurancePolicy,
    LiabilityRecord,
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
    model = None

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

    def get_by_id(self, obj_id):
        oid = _coerce_uuid(obj_id)
        if oid is None:
            return None
        return self._session.get(self.model, oid)

    def get_by_id_or_raise(self, obj_id):
        obj = self.get_by_id(obj_id)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} {obj_id} not found.")
        return obj

    def soft_delete(self, obj, *, deleted_by=None):
        obj.soft_delete()
        obj.deleted_by = deleted_by
        return obj

    def restore(self, obj):
        obj.restore()
        obj.deleted_by = None
        return obj


class InsurancePolicyRepository(_BaseRepo):
    model = InsurancePolicy

    def get_by_number(self, policy_number: str) -> Optional[InsurancePolicy]:
        stmt = select(InsurancePolicy).where(
            InsurancePolicy.policy_number == policy_number,
            InsurancePolicy.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def list_policies(
        self,
        *,
        q=None,
        status=None,
        policy_type=None,
        include_deleted=False,
        sort_by="created_at",
        sort_dir="desc",
        limit=50,
        offset=0,
    ) -> Tuple[List[InsurancePolicy], int]:
        stmt = select(InsurancePolicy)
        if not include_deleted:
            stmt = stmt.where(InsurancePolicy.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(InsurancePolicy.status == status)
        if policy_type is not None:
            stmt = stmt.where(InsurancePolicy.policy_type == policy_type)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    InsurancePolicy.policy_number.ilike(pattern),
                    InsurancePolicy.provider_name.ilike(pattern),
                )
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(InsurancePolicy, sort_by, InsurancePolicy.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class CoverageRuleRepository(_BaseRepo):
    model = CoverageRule

    def get_rules_for_policy(
        self, policy_id: uuid.UUID, *, active_only: bool = False
    ) -> List[CoverageRule]:
        stmt = select(CoverageRule).where(
            CoverageRule.policy_id == policy_id, CoverageRule.deleted_at.is_(None)
        )
        if active_only:
            stmt = stmt.where(CoverageRule.active.is_(True))
        return list(self._session.scalars(stmt).all())

    def list_rules(self, *, policy_id=None, include_deleted=False, limit=50, offset=0):
        stmt = select(CoverageRule)
        if not include_deleted:
            stmt = stmt.where(CoverageRule.deleted_at.is_(None))
        if policy_id is not None:
            stmt = stmt.where(CoverageRule.policy_id == policy_id)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(desc(CoverageRule.created_at)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class ClaimRepository(_BaseRepo):
    model = Claim

    def get_by_number(self, claim_number: str) -> Optional[Claim]:
        stmt = select(Claim).where(Claim.claim_number == claim_number, Claim.deleted_at.is_(None))
        return self._session.scalars(stmt).first()

    def get_active_policy_for_claim(self, claim: Claim) -> Optional[InsurancePolicy]:
        """Return the claim's linked policy if it is currently ACTIVE."""
        if claim.policy_id is None:
            return None
        stmt = select(InsurancePolicy).where(
            InsurancePolicy.id == claim.policy_id,
            InsurancePolicy.status == InsurancePolicyStatus.ACTIVE,
            InsurancePolicy.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def list_claims_for_shipment(self, shipment_id: uuid.UUID) -> List[Claim]:
        stmt = select(Claim).where(Claim.shipment_id == shipment_id, Claim.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_claims_for_equipment(self, equipment_id: uuid.UUID) -> List[Claim]:
        stmt = select(Claim).where(Claim.equipment_id == equipment_id, Claim.deleted_at.is_(None))
        return list(self._session.scalars(stmt).all())

    def list_claims(
        self,
        *,
        q=None,
        status=None,
        claim_type=None,
        shipment_id=None,
        equipment_id=None,
        policy_id=None,
        include_deleted=False,
        sort_by="created_at",
        sort_dir="desc",
        limit=50,
        offset=0,
    ) -> Tuple[List[Claim], int]:
        stmt = select(Claim)
        if not include_deleted:
            stmt = stmt.where(Claim.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Claim.status == status)
        if claim_type is not None:
            stmt = stmt.where(Claim.claim_type == claim_type)
        if shipment_id is not None:
            stmt = stmt.where(Claim.shipment_id == shipment_id)
        if equipment_id is not None:
            stmt = stmt.where(Claim.equipment_id == equipment_id)
        if policy_id is not None:
            stmt = stmt.where(Claim.policy_id == policy_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(Claim.claim_number.ilike(pattern), Claim.description.ilike(pattern))
            )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Claim, sort_by, Claim.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class DamageReportRepository(_BaseRepo):
    model = DamageReport

    def list_damage_reports_for_claim(self, claim_id: uuid.UUID) -> List[DamageReport]:
        stmt = (
            select(DamageReport)
            .where(DamageReport.claim_id == claim_id, DamageReport.deleted_at.is_(None))
            .order_by(DamageReport.created_at)
        )
        return list(self._session.scalars(stmt).all())


class LiabilityRecordRepository(_BaseRepo):
    model = LiabilityRecord

    def list_liability_records_for_claim(self, claim_id: uuid.UUID) -> List[LiabilityRecord]:
        stmt = (
            select(LiabilityRecord)
            .where(LiabilityRecord.claim_id == claim_id, LiabilityRecord.deleted_at.is_(None))
            .order_by(LiabilityRecord.created_at)
        )
        return list(self._session.scalars(stmt).all())

    def total_liability_percentage(self, claim_id: uuid.UUID) -> float:
        stmt = select(func.coalesce(func.sum(LiabilityRecord.liability_percentage), 0)).where(
            LiabilityRecord.claim_id == claim_id, LiabilityRecord.deleted_at.is_(None)
        )
        return float(self._session.scalar(stmt) or 0)
