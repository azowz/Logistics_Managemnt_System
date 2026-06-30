"""Compliance & Permits service + dispatch gate (context #16, Sprint 7).

`ComplianceService` owns the unit of work and outbox emission for permits,
escorts, route restrictions, axle-weight profiles, compliance checks, and
operator certifications. `ComplianceValidationService` is a thin, **read-only**
dispatch gate that `ShipmentService` depends on (no circular dependency, no
events, no commit) to decide whether a movement may proceed.

State changes follow the platform pattern:
    validate tenant → load → validate rules → mutate → flush → event →
    EventEnvelope.create() → EventStoreRepository.append() → commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.compliance_events import (
    AxleWeightProfileCreated,
    ComplianceCheckCreated,
    ComplianceCheckFailed,
    ComplianceCheckPassed,
    ComplianceOverrideApplied,
    EscortCancelled,
    EscortCreated,
    EscortScheduled,
    OperatorCertificationCreated,
    OperatorCertificationExpired,
    PermitActivated,
    PermitApproved,
    PermitCancelled,
    PermitCreated,
    PermitDeleted,
    PermitExpired,
    PermitRejected,
    PermitRestored,
    PermitSubmitted,
    PermitUnderReview,
    RouteRestrictionCreated,
    RouteRestrictionUpdated,
)
from app.models.compliance import (
    ComplianceCheck,
    Escort,
    OperatorCertification,
    Permit,
    RouteRestriction,
)
from app.models.enums import (
    ComplianceCheckStatus,
    ComplianceCheckType,
    EscortStatus,
    OperatorCertificationStatus,
    PermitStatus,
)
from app.repositories.compliance_repository import (
    AxleWeightProfileRepository,
    ComplianceCheckRepository,
    EscortRepository,
    OperatorCertificationRepository,
    PermitRepository,
    RouteRestrictionRepository,
)
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.compliance_policies import PermitStateMachine
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

# Oversize thresholds (metres / kg) — configurable per jurisdiction in a later
# sprint (docs/08 Part 1.3); conservative KSA-like defaults here.
OVERSIZE_WIDTH_M = Decimal("2.6")
OVERSIZE_HEIGHT_M = Decimal("4.5")
OVERSIZE_LENGTH_M = Decimal("16.0")
OVERWEIGHT_KG = Decimal("45000")


@dataclass(frozen=True, slots=True)
class DispatchGateResult:
    """Outcome of a compliance dispatch-gate evaluation."""

    allowed: bool
    blocking_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    required_permits: List[str] = field(default_factory=list)
    required_escorts: List[str] = field(default_factory=list)
    compliance_check_ids: List[str] = field(default_factory=list)


class ComplianceValidationService:
    """Read-only dispatch gate consumed by ShipmentService (no events/commit)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._permits = PermitRepository(session)
        self._escorts = EscortRepository(session)
        self._checks = ComplianceCheckRepository(session)
        self._equipment = EquipmentRepository(session)

    def validate_dispatch(self, *, shipment, stage: str = "assign") -> DispatchGateResult:
        """Decide whether ``shipment`` may proceed past ``stage``.

        Fails CLOSED for permit-required / hazardous equipment lacking an active
        valid permit or required escort; allows normal shipments (no equipment or
        no compliance conditions) through.
        """
        equipment_id = getattr(shipment, "equipment_id", None)
        if equipment_id is None:
            return DispatchGateResult(allowed=True)

        equipment = self._equipment.get_by_id(equipment_id)
        if equipment is None:
            # Referenced equipment vanished — fail closed.
            return DispatchGateResult(
                allowed=False,
                blocking_reasons=["Referenced equipment not found."],
            )

        blocking: List[str] = []
        warnings: List[str] = []
        required_permits: List[str] = []
        required_escorts: List[str] = []

        now = utcnow()
        needs_permit = bool(
            equipment.requires_permit
            or equipment.hazardous
            or self._is_oversize(equipment)
        )
        if needs_permit:
            required_permits.append("movement_permit")
            permit = self._permits.get_active_permit_for_shipment(shipment.id)
            if permit is None:
                blocking.append("An active movement permit is required but none exists.")
            elif not PermitStateMachine.is_dispatchable(permit.status):
                blocking.append(f"Permit is not active (status={permit.status.value}).")
            elif _aware(permit.valid_until) is not None and _aware(permit.valid_until) < now:
                blocking.append("The permit's validity window has expired.")
            elif _aware(permit.valid_from) is not None and _aware(permit.valid_from) > now:
                blocking.append("The permit is not yet valid.")

        if equipment.requires_escort:
            required_escorts.append("escort")
            escorts = self._escorts.get_active_escorts_for_shipment(shipment.id)
            if not escorts:
                blocking.append("An escort plan is required but none is scheduled.")

        if equipment.insurance_required:
            warnings.append("Insurance is required for this equipment (advisory).")

        # Honour previously-persisted failed blocking checks (oversize, route,
        # axle-weight, etc. produced by evaluate_compliance).
        failed = self._checks.list_failed_blocking_checks(shipment.id)
        check_ids = [str(c.id) for c in failed]
        for c in failed:
            blocking.append(f"Failed compliance check: {c.check_type.value}.")

        return DispatchGateResult(
            allowed=not blocking,
            blocking_reasons=blocking,
            warnings=warnings,
            required_permits=required_permits,
            required_escorts=required_escorts,
            compliance_check_ids=check_ids,
        )

    @staticmethod
    def _is_oversize(equipment) -> bool:
        def gt(value, threshold) -> bool:
            return value is not None and Decimal(str(value)) > threshold

        return (
            gt(equipment.width_m, OVERSIZE_WIDTH_M)
            or gt(equipment.height_m, OVERSIZE_HEIGHT_M)
            or gt(equipment.length_m, OVERSIZE_LENGTH_M)
            or gt(equipment.weight_kg, OVERWEIGHT_KG)
        )


class ComplianceService:
    """Owns permit/escort/restriction/check/certification lifecycles + events."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._permits = PermitRepository(session)
        self._escorts = EscortRepository(session)
        self._restrictions = RouteRestrictionRepository(session)
        self._axles = AxleWeightProfileRepository(session)
        self._checks = ComplianceCheckRepository(session)
        self._certs = OperatorCertificationRepository(session)
        self._shipments = ShipmentRepository(session)
        self._equipment = EquipmentRepository(session)
        self._vehicles = VehicleRepository(session)
        self._users = UserRepository(session)
        self._event_repo = EventStoreRepository(session)
        self._gate = ComplianceValidationService(session)

    # --- context helpers ---

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self) -> Optional[uuid.UUID]:
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id, aggregate_type, tenant_id) -> None:
        next_version = self._event_repo.next_aggregate_version(aggregate_id)
        envelope = EventEnvelope.create(
            event,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_version=next_version,
            aggregate_type=aggregate_type,
            user_id=self._actor_id(),
        )
        self._event_repo.append(envelope)

    def _require_tenant_owned(self, obj, tenant_id, label, identifier):
        if (
            obj is None
            or getattr(obj, "is_deleted", False)
            or getattr(obj, "tenant_id", None) != tenant_id
        ):
            raise ValidationError(f"{label} {identifier} does not exist in this tenant.")
        return obj

    @staticmethod
    def _generate_permit_number() -> str:
        return f"PMT-{uuid.uuid4().hex[:12].upper()}"

    def _validate_refs(self, tenant_id, *, shipment_id=None, equipment_id=None, vehicle_id=None):
        if shipment_id is not None:
            self._require_tenant_owned(self._shipments.get_by_id(shipment_id), tenant_id, "Shipment", shipment_id)
        if equipment_id is not None:
            self._require_tenant_owned(self._equipment.get_by_id(equipment_id), tenant_id, "Equipment", equipment_id)
        if vehicle_id is not None:
            self._require_tenant_owned(self._vehicles.get_by_id(vehicle_id), tenant_id, "Vehicle", vehicle_id)

    # ==================================================================
    # Permits
    # ==================================================================

    def create_permit(self, *, permit_number: Optional[str] = None, **data) -> Permit:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_refs(
            tenant_id,
            shipment_id=data.get("shipment_id"),
            equipment_id=data.get("equipment_id"),
            vehicle_id=data.get("vehicle_id"),
        )
        number = permit_number or self._generate_permit_number()
        if self._permits.get_by_number(number):
            raise ConflictError(f"Permit number '{number}' already exists in this tenant.")
        data.pop("status", None)
        permit = self._permits.create(
            tenant_id=tenant_id,
            permit_number=number,
            status=PermitStatus.DRAFT,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()
        self._emit(
            PermitCreated(
                permit_id=permit.id, tenant_id=tenant_id, permit_number=number,
                permit_type=permit.permit_type.value, status=permit.status.value,
                shipment_id=permit.shipment_id, equipment_id=permit.equipment_id,
            ),
            aggregate_id=permit.id, aggregate_type="Permit", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(permit)
        return permit

    def _permit_transition(
        self,
        permit_id: uuid.UUID,
        new_status: PermitStatus,
        *,
        mutate: Optional[Callable[[Permit], None]] = None,
        extra_events: Optional[List[Callable[[Permit, PermitStatus], object]]] = None,
    ) -> Permit:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        permit = self._permits.get_by_id_or_raise(permit_id)
        if permit.is_deleted:
            raise NotFoundError(f"Permit {permit_id} not found (deleted).")
        previous = permit.status
        if new_status == previous:
            return permit
        PermitStateMachine.validate_transition(previous, new_status)
        if mutate is not None:
            mutate(permit)
        permit.status = new_status
        permit.updated_by = actor_id
        self._session.flush()
        for factory in extra_events or []:
            self._emit(
                factory(permit, previous),
                aggregate_id=permit.id, aggregate_type="Permit", tenant_id=tenant_id,
            )
        self._session.commit()
        self._session.refresh(permit)
        return permit

    def submit_permit(self, permit_id):
        return self._permit_transition(
            permit_id, PermitStatus.SUBMITTED,
            extra_events=[lambda p, prev: PermitSubmitted(permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value)],
        )

    def mark_under_review(self, permit_id):
        return self._permit_transition(
            permit_id, PermitStatus.UNDER_REVIEW,
            extra_events=[lambda p, prev: PermitUnderReview(permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value)],
        )

    def approve_permit(self, permit_id, *, valid_from=None, valid_until=None):
        def _mutate(p: Permit) -> None:
            p.approved_at = utcnow()
            if valid_from is not None:
                p.valid_from = valid_from
            if valid_until is not None:
                p.valid_until = valid_until
        return self._permit_transition(
            permit_id, PermitStatus.APPROVED, mutate=_mutate,
            extra_events=[lambda p, prev: PermitApproved(
                permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value,
                valid_from=p.valid_from.isoformat() if p.valid_from else None,
                valid_until=p.valid_until.isoformat() if p.valid_until else None,
            )],
        )

    def reject_permit(self, permit_id, *, reason=None):
        def _mutate(p: Permit) -> None:
            p.rejected_at = utcnow()
            p.rejection_reason = reason
        return self._permit_transition(
            permit_id, PermitStatus.REJECTED, mutate=_mutate,
            extra_events=[lambda p, prev: PermitRejected(permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def activate_permit(self, permit_id):
        return self._permit_transition(
            permit_id, PermitStatus.ACTIVE,
            extra_events=[lambda p, prev: PermitActivated(permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value)],
        )

    def expire_permit(self, permit_id):
        def _mutate(p: Permit) -> None:
            p.expired_at = utcnow()
        return self._permit_transition(
            permit_id, PermitStatus.EXPIRED, mutate=_mutate,
            extra_events=[lambda p, prev: PermitExpired(permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value)],
        )

    def cancel_permit(self, permit_id, *, reason=None):
        def _mutate(p: Permit) -> None:
            p.cancelled_at = utcnow()
        return self._permit_transition(
            permit_id, PermitStatus.CANCELLED, mutate=_mutate,
            extra_events=[lambda p, prev: PermitCancelled(permit_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def get_permit(self, permit_id, *, include_deleted=False) -> Permit:
        permit = self._permits.get_by_id(permit_id)
        if permit is None or (permit.is_deleted and not include_deleted):
            raise NotFoundError(f"Permit {permit_id} not found.")
        return permit

    def list_permits(self, params) -> Page[Permit]:
        items, total = self._permits.list_permits(
            q=params.q, status=params.status, permit_type=params.permit_type,
            shipment_id=params.shipment_id, equipment_id=params.equipment_id,
            include_deleted=params.include_deleted, sort_by=params.sort_by,
            sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    def update_permit(self, permit_id, **data) -> Permit:
        self._tenant_id()
        actor_id = self._actor_id()
        permit = self._permits.get_by_id_or_raise(permit_id)
        if permit.is_deleted:
            raise NotFoundError(f"Permit {permit_id} not found (deleted).")
        if PermitStateMachine.is_terminal(permit.status):
            raise ValidationError(f"Permit {permit_id} is terminal and cannot be edited.")
        data["updated_by"] = actor_id
        self._permits.update(permit, **data)
        self._session.commit()
        self._session.refresh(permit)
        return permit

    def delete_permit(self, permit_id) -> None:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        permit = self._permits.get_by_id_or_raise(permit_id)
        if permit.is_deleted:
            raise NotFoundError(f"Permit {permit_id} is already deleted.")
        self._permits.soft_delete(permit, deleted_by=actor_id)
        self._session.flush()
        self._emit(
            PermitDeleted(permit_id=permit.id, tenant_id=tenant_id, deleted_by=actor_id),
            aggregate_id=permit.id, aggregate_type="Permit", tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_permit(self, permit_id) -> Permit:
        tenant_id = self._tenant_id()
        permit = self._permits.get_by_id(permit_id)
        if permit is None:
            raise NotFoundError(f"Permit {permit_id} not found.")
        if not permit.is_deleted:
            raise ValidationError(f"Permit {permit_id} is not deleted; nothing to restore.")
        self._permits.restore(permit)
        self._session.flush()
        self._emit(
            PermitRestored(permit_id=permit.id, tenant_id=tenant_id),
            aggregate_id=permit.id, aggregate_type="Permit", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(permit)
        return permit

    # ==================================================================
    # Escorts
    # ==================================================================

    def create_escort(self, **data) -> Escort:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_refs(tenant_id, shipment_id=data.get("shipment_id"))
        if data.get("permit_id") is not None:
            self._require_tenant_owned(self._permits.get_by_id(data["permit_id"]), tenant_id, "Permit", data["permit_id"])
        escort = self._escorts.create(
            tenant_id=tenant_id, status=EscortStatus.PLANNED,
            created_by=actor_id, updated_by=actor_id, **data,
        )
        self._session.flush()
        self._emit(
            EscortCreated(
                escort_id=escort.id, tenant_id=tenant_id, escort_type=escort.escort_type.value,
                shipment_id=escort.shipment_id, permit_id=escort.permit_id,
            ),
            aggregate_id=escort.id, aggregate_type="Escort", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(escort)
        return escort

    def schedule_escort(self, escort_id, *, scheduled_start=None, scheduled_end=None) -> Escort:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        escort = self._escorts.get_by_id_or_raise(escort_id)
        if escort.is_deleted:
            raise NotFoundError(f"Escort {escort_id} not found (deleted).")
        if escort.status == EscortStatus.CANCELLED:
            raise ConflictError("Cancelled escort cannot be scheduled.")
        previous = escort.status
        if scheduled_start is not None:
            escort.scheduled_start = scheduled_start
        if scheduled_end is not None:
            escort.scheduled_end = scheduled_end
        escort.status = EscortStatus.SCHEDULED
        escort.updated_by = actor_id
        self._session.flush()
        self._emit(
            EscortScheduled(
                escort_id=escort.id, tenant_id=tenant_id, previous_status=previous.value,
                scheduled_start=escort.scheduled_start.isoformat() if escort.scheduled_start else None,
                scheduled_end=escort.scheduled_end.isoformat() if escort.scheduled_end else None,
            ),
            aggregate_id=escort.id, aggregate_type="Escort", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(escort)
        return escort

    def cancel_escort(self, escort_id) -> Escort:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        escort = self._escorts.get_by_id_or_raise(escort_id)
        if escort.is_deleted:
            raise NotFoundError(f"Escort {escort_id} not found (deleted).")
        previous = escort.status
        escort.status = EscortStatus.CANCELLED
        escort.updated_by = actor_id
        self._session.flush()
        self._emit(
            EscortCancelled(escort_id=escort.id, tenant_id=tenant_id, previous_status=previous.value),
            aggregate_id=escort.id, aggregate_type="Escort", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(escort)
        return escort

    def list_escorts(self, params) -> Page[Escort]:
        items, total = self._escorts.list_escorts(
            shipment_id=params.shipment_id, status=params.status,
            include_deleted=params.include_deleted, sort_by=params.sort_by,
            sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    # ==================================================================
    # Route restrictions
    # ==================================================================

    def create_route_restriction(self, **data) -> RouteRestriction:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        restriction = self._restrictions.create(
            tenant_id=tenant_id, created_by=actor_id, updated_by=actor_id, **data
        )
        self._session.flush()
        self._emit(
            RouteRestrictionCreated(
                restriction_id=restriction.id, tenant_id=tenant_id,
                restriction_type=restriction.restriction_type.value, region=restriction.region,
            ),
            aggregate_id=restriction.id, aggregate_type="RouteRestriction", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(restriction)
        return restriction

    def update_route_restriction(self, restriction_id, **data) -> RouteRestriction:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        restriction = self._restrictions.get_by_id_or_raise(restriction_id)
        if restriction.is_deleted:
            raise NotFoundError(f"Route restriction {restriction_id} not found (deleted).")
        applied = {k: v for k, v in data.items() if v is not None}
        data["updated_by"] = actor_id
        self._restrictions.update(restriction, **data)
        self._session.flush()
        self._emit(
            RouteRestrictionUpdated(
                restriction_id=restriction.id, tenant_id=tenant_id, changed_fields=_jsonable(applied)
            ),
            aggregate_id=restriction.id, aggregate_type="RouteRestriction", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(restriction)
        return restriction

    def list_route_restrictions(self, *, region=None, limit=50, offset=0):
        return self._restrictions.list_restrictions(region=region, limit=limit, offset=offset)

    # ==================================================================
    # Axle weight profiles
    # ==================================================================

    def create_axle_weight_profile(self, **data):
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_refs(tenant_id, equipment_id=data.get("equipment_id"), vehicle_id=data.get("vehicle_id"))
        profile = self._axles.create(
            tenant_id=tenant_id, created_by=actor_id, updated_by=actor_id, **data
        )
        self._session.flush()
        self._emit(
            AxleWeightProfileCreated(
                profile_id=profile.id, tenant_id=tenant_id, equipment_id=profile.equipment_id,
                vehicle_id=profile.vehicle_id, is_compliant=profile.is_compliant,
            ),
            aggregate_id=profile.id, aggregate_type="AxleWeightProfile", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(profile)
        return profile

    # ==================================================================
    # Compliance checks + dispatch
    # ==================================================================

    def _persist_check(self, *, tenant_id, shipment_id, equipment_id, check_type, status, blocking, result=None, failure_reasons=None):
        actor_id = self._actor_id()
        check = self._checks.create(
            tenant_id=tenant_id, shipment_id=shipment_id, equipment_id=equipment_id,
            check_type=check_type, status=status, blocking=blocking, result=result,
            failure_reasons=failure_reasons, evaluated_at=utcnow(), evaluated_by=actor_id,
            created_by=actor_id, updated_by=actor_id,
        )
        self._session.flush()
        self._emit(
            ComplianceCheckCreated(
                check_id=check.id, tenant_id=tenant_id, shipment_id=shipment_id,
                check_type=check_type.value, status=status.value,
            ),
            aggregate_id=check.id, aggregate_type="ComplianceCheck", tenant_id=tenant_id,
        )
        if status == ComplianceCheckStatus.PASSED:
            self._emit(
                ComplianceCheckPassed(check_id=check.id, tenant_id=tenant_id, shipment_id=shipment_id, check_type=check_type.value),
                aggregate_id=check.id, aggregate_type="ComplianceCheck", tenant_id=tenant_id,
            )
        elif status == ComplianceCheckStatus.FAILED:
            self._emit(
                ComplianceCheckFailed(
                    check_id=check.id, tenant_id=tenant_id, shipment_id=shipment_id,
                    check_type=check_type.value, failure_reasons=failure_reasons or [],
                ),
                aggregate_id=check.id, aggregate_type="ComplianceCheck", tenant_id=tenant_id,
            )
        return check

    def evaluate_compliance(self, *, shipment_id: uuid.UUID) -> List[ComplianceCheck]:
        """Evaluate the equipment transport profile and persist compliance checks."""
        tenant_id = self._tenant_id()
        shipment = self._require_tenant_owned(
            self._shipments.get_by_id(shipment_id), tenant_id, "Shipment", shipment_id
        )
        checks: List[ComplianceCheck] = []
        equipment_id = shipment.equipment_id
        equipment = self._equipment.get_by_id(equipment_id) if equipment_id else None
        if equipment is None:
            self._session.commit()
            return checks

        active_permit = self._permits.get_active_permit_for_shipment(shipment_id)
        active_escorts = self._escorts.get_active_escorts_for_shipment(shipment_id)
        oversize = ComplianceValidationService._is_oversize(equipment)

        if equipment.requires_permit or equipment.hazardous or oversize:
            ok = active_permit is not None
            checks.append(self._persist_check(
                tenant_id=tenant_id, shipment_id=shipment_id, equipment_id=equipment_id,
                check_type=ComplianceCheckType.PERMIT_REQUIRED,
                status=ComplianceCheckStatus.PASSED if ok else ComplianceCheckStatus.FAILED,
                blocking=True, result="permit present" if ok else "no active permit",
                failure_reasons=None if ok else ["No active movement permit for shipment."],
            ))
        if oversize:
            checks.append(self._persist_check(
                tenant_id=tenant_id, shipment_id=shipment_id, equipment_id=equipment_id,
                check_type=ComplianceCheckType.OVERSIZE,
                status=ComplianceCheckStatus.PASSED if active_permit else ComplianceCheckStatus.FAILED,
                blocking=True, result="oversize within permit" if active_permit else "oversize without permit",
                failure_reasons=None if active_permit else ["Oversize load requires a permit."],
            ))
        if equipment.requires_escort:
            ok = bool(active_escorts)
            checks.append(self._persist_check(
                tenant_id=tenant_id, shipment_id=shipment_id, equipment_id=equipment_id,
                check_type=ComplianceCheckType.ESCORT_REQUIRED,
                status=ComplianceCheckStatus.PASSED if ok else ComplianceCheckStatus.FAILED,
                blocking=True, result="escort scheduled" if ok else "no escort",
                failure_reasons=None if ok else ["Escort required but none scheduled."],
            ))
        if equipment.hazardous:
            checks.append(self._persist_check(
                tenant_id=tenant_id, shipment_id=shipment_id, equipment_id=equipment_id,
                check_type=ComplianceCheckType.HAZARDOUS_MATERIAL,
                status=ComplianceCheckStatus.WARNING, blocking=False,
                result="hazardous handling advisory",
            ))
        if equipment.insurance_required:
            checks.append(self._persist_check(
                tenant_id=tenant_id, shipment_id=shipment_id, equipment_id=equipment_id,
                check_type=ComplianceCheckType.INSURANCE_REQUIRED,
                status=ComplianceCheckStatus.WARNING, blocking=False,
                result="insurance advisory",
            ))
        self._session.commit()
        return checks

    def apply_compliance_override(self, check_id, *, reason=None) -> ComplianceCheck:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        check = self._checks.get_by_id_or_raise(check_id)
        if check.is_deleted:
            raise NotFoundError(f"Compliance check {check_id} not found (deleted).")
        check.status = ComplianceCheckStatus.OVERRIDDEN
        check.blocking = False
        check.notes = reason
        check.updated_by = actor_id
        self._session.flush()
        self._emit(
            ComplianceOverrideApplied(check_id=check.id, tenant_id=tenant_id, overridden_by=actor_id, reason=reason),
            aggregate_id=check.id, aggregate_type="ComplianceCheck", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(check)
        return check

    def get_check(self, check_id, *, include_deleted=False) -> ComplianceCheck:
        check = self._checks.get_by_id(check_id)
        if check is None or (check.is_deleted and not include_deleted):
            raise NotFoundError(f"Compliance check {check_id} not found.")
        return check

    def list_checks(self, params) -> Page[ComplianceCheck]:
        items, total = self._checks.list_checks(
            shipment_id=params.shipment_id, status=params.status,
            include_deleted=params.include_deleted, sort_by=params.sort_by,
            sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    def validate_dispatch_clearance(self, shipment_id, *, stage="assign") -> DispatchGateResult:
        """Load the shipment and run the read-only dispatch gate."""
        tenant_id = self._tenant_id()
        shipment = self._require_tenant_owned(
            self._shipments.get_by_id(shipment_id), tenant_id, "Shipment", shipment_id
        )
        return self._gate.validate_dispatch(shipment=shipment, stage=stage)

    # ==================================================================
    # Operator certifications
    # ==================================================================

    def create_operator_certification(self, **data) -> OperatorCertification:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._require_tenant_owned(self._users.get_by_id(data["user_id"]), tenant_id, "User", data["user_id"])
        cert = self._certs.create(
            tenant_id=tenant_id, status=OperatorCertificationStatus.ACTIVE,
            created_by=actor_id, updated_by=actor_id, **data,
        )
        self._session.flush()
        self._emit(
            OperatorCertificationCreated(
                certification_id=cert.id, tenant_id=tenant_id, user_id=cert.user_id,
                certification_type=cert.certification_type, status=cert.status.value,
            ),
            aggregate_id=cert.id, aggregate_type="OperatorCertification", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(cert)
        return cert

    def expire_operator_certification(self, certification_id) -> OperatorCertification:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        cert = self._certs.get_by_id_or_raise(certification_id)
        if cert.is_deleted:
            raise NotFoundError(f"Certification {certification_id} not found (deleted).")
        previous = cert.status
        if previous == OperatorCertificationStatus.EXPIRED:
            return cert
        cert.status = OperatorCertificationStatus.EXPIRED
        cert.updated_by = actor_id
        self._session.flush()
        self._emit(
            OperatorCertificationExpired(certification_id=cert.id, tenant_id=tenant_id, previous_status=previous.value),
            aggregate_id=cert.id, aggregate_type="OperatorCertification", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(cert)
        return cert

    def list_certifications(self, *, user_id=None, status=None, limit=50, offset=0):
        return self._certs.list_certifications(user_id=user_id, status=status, limit=limit, offset=offset)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat a naive datetime (e.g. read back from SQLite) as UTC for comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _jsonable(data: Dict[str, object]) -> Dict[str, object]:
    from app.events.domain_event import to_jsonable

    return {k: to_jsonable(v) for k, v in data.items()}
