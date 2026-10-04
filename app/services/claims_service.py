"""Claims service — claim workflow, damage reports, liability (context #17, Sprint 8).

Owns the unit of work and outbox emission for the `Claim` aggregate and its
`DamageReport` / `LiabilityRecord` children. Claims reference Shipment / Order /
Customer / Equipment / Compliance by id (validated tenant-owned) but those
contexts do not own the claim lifecycle.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.insurance_events import (
    ClaimApproved,
    ClaimClosed,
    ClaimCreated,
    ClaimDeleted,
    ClaimLinkedToEquipment,
    ClaimLinkedToShipment,
    ClaimRejected,
    ClaimReopened,
    ClaimRestored,
    ClaimSettled,
    ClaimSubmittedForReview,
    DamageReportCreated,
    LiabilityRecordCreated,
)
from app.models.enums import ClaimStatus, ClaimType
from app.models.insurance import Claim, DamageReport, LiabilityRecord
from app.repositories.compliance_repository import ComplianceCheckRepository, PermitRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.insurance_repository import (
    ClaimRepository,
    DamageReportRepository,
    InsurancePolicyRepository,
    LiabilityRecordRepository,
)
from app.repositories.order_repository import OrderRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.insurance_policies import ClaimStateMachine, PolicyStateMachine

# claim_type → the policy flag that must be set for coverage.
_COVERAGE_FLAG = {
    ClaimType.SHIPMENT_LOSS: "covers_shipment",
    ClaimType.SHIPMENT_DAMAGE: "covers_shipment",
    ClaimType.DELAY_CLAIM: "covers_shipment",
    ClaimType.EQUIPMENT_DAMAGE: "covers_equipment",
    ClaimType.THIRD_PARTY_LIABILITY: "covers_third_party",
    ClaimType.COMPLIANCE_VIOLATION: None,  # any active policy
}


class ClaimsService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._claims = ClaimRepository(session)
        self._policies = InsurancePolicyRepository(session)
        self._damage = DamageReportRepository(session)
        self._liability = LiabilityRecordRepository(session)
        self._shipments = ShipmentRepository(session)
        self._orders = OrderRepository(session)
        self._customers = CustomerRepository(session)
        self._equipment = EquipmentRepository(session)
        self._checks = ComplianceCheckRepository(session)
        self._permits = PermitRepository(session)
        self._event_repo = EventStoreRepository(session)

    # --- context helpers ---

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self):
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id, aggregate_type, tenant_id):
        nv = self._event_repo.next_aggregate_version(aggregate_id)
        env = EventEnvelope.create(
            event,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_version=nv,
            aggregate_type=aggregate_type,
            user_id=self._actor_id(),
        )
        self._event_repo.append(env)

    def _owned(self, obj, tenant_id, label, ident):
        if (
            obj is None
            or getattr(obj, "is_deleted", False)
            or getattr(obj, "tenant_id", None) != tenant_id
        ):
            raise ValidationError(f"{label} {ident} does not exist in this tenant.")
        return obj

    @staticmethod
    def _generate_claim_number() -> str:
        return f"CLM-{uuid.uuid4().hex[:12].upper()}"

    @staticmethod
    def _ev(value):
        """Return an enum's value, tolerating a raw string (defensive)."""
        return value.value if hasattr(value, "value") else value

    @staticmethod
    def _cycle_days(created, settled):
        """Whole days from claim creation to settlement (None if unknown/non-datetime)."""
        from datetime import datetime, timezone

        if not isinstance(created, datetime) or not isinstance(settled, datetime):
            return None
        created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        settled = settled if settled.tzinfo else settled.replace(tzinfo=timezone.utc)
        return max(0, (settled - created).days)

    # --- validation ops ---

    def validate_claim_references(self, tenant_id, data) -> None:
        if data.get("policy_id") is not None:
            self._owned(
                self._policies.get_by_id(data["policy_id"]), tenant_id, "Policy", data["policy_id"]
            )
        if data.get("shipment_id") is not None:
            self._owned(
                self._shipments.get_by_id(data["shipment_id"]),
                tenant_id,
                "Shipment",
                data["shipment_id"],
            )
        if data.get("order_id") is not None:
            self._owned(
                self._orders.get_by_id(data["order_id"]), tenant_id, "Order", data["order_id"]
            )
        if data.get("customer_id") is not None:
            self._owned(
                self._customers.get_by_id(data["customer_id"]),
                tenant_id,
                "Customer",
                data["customer_id"],
            )
        if data.get("equipment_id") is not None:
            self._owned(
                self._equipment.get_by_id(data["equipment_id"]),
                tenant_id,
                "Equipment",
                data["equipment_id"],
            )
        if data.get("compliance_check_id") is not None:
            self._owned(
                self._checks.get_by_id(data["compliance_check_id"]),
                tenant_id,
                "Compliance check",
                data["compliance_check_id"],
            )
        if data.get("permit_id") is not None:
            self._owned(
                self._permits.get_by_id(data["permit_id"]), tenant_id, "Permit", data["permit_id"]
            )

    def validate_policy_coverage(self, claim: Claim) -> None:
        """Raise ValidationError unless the linked policy can back this claim."""
        if claim.policy_id is None:
            raise ValidationError("Claim has no linked insurance policy; cannot approve.")
        policy = self._policies.get_by_id(claim.policy_id)
        if policy is None or policy.is_deleted or policy.tenant_id != claim.tenant_id:
            raise ValidationError("Linked policy does not exist in this tenant.")
        if not PolicyStateMachine.can_cover(policy.status):
            raise ValidationError(
                f"Policy is '{policy.status.value}', not active; cannot approve claim."
            )
        flag = _COVERAGE_FLAG.get(claim.claim_type)
        if flag is not None and not getattr(policy, flag, False):
            raise ValidationError(f"Policy does not cover '{claim.claim_type.value}'.")

    def validate_liability_distribution(
        self, claim_id, new_percentage, *, allow_override=False
    ) -> None:
        if new_percentage is None:
            return
        existing = self._liability.total_liability_percentage(claim_id)
        if not allow_override and existing + float(new_percentage) > 100.0:
            raise ValidationError(
                f"Total liability would exceed 100% (existing {existing}% + {new_percentage}%)."
            )

    # --- create ---

    def create_claim(self, *, claim_number: Optional[str] = None, **data) -> Claim:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self.validate_claim_references(tenant_id, data)
        if (
            data.get("claim_type") == ClaimType.EQUIPMENT_DAMAGE
            and data.get("equipment_id") is None
        ):
            raise ValidationError("equipment_damage claims require an equipment_id.")
        number = claim_number or self._generate_claim_number()
        if self._claims.get_by_number(number):
            raise ConflictError(f"Claim number '{number}' already exists in this tenant.")
        data.pop("status", None)
        claim = self._claims.create(
            tenant_id=tenant_id,
            claim_number=number,
            status=ClaimStatus.CREATED,
            reported_at=utcnow(),
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()
        self._emit(
            ClaimCreated(
                claim_id=claim.id,
                tenant_id=tenant_id,
                claim_number=number,
                claim_type=self._ev(claim.claim_type),
                status=self._ev(claim.status),
                shipment_id=claim.shipment_id,
                equipment_id=claim.equipment_id,
                claimed_amount=(
                    str(claim.claimed_amount) if claim.claimed_amount is not None else None
                ),
                currency_code=claim.currency_code,
                customer_id=claim.customer_id,
            ),
            aggregate_id=claim.id,
            aggregate_type="Claim",
            tenant_id=tenant_id,
        )
        if claim.shipment_id is not None:
            self._emit(
                ClaimLinkedToShipment(
                    claim_id=claim.id, tenant_id=tenant_id, shipment_id=claim.shipment_id
                ),
                aggregate_id=claim.id,
                aggregate_type="Claim",
                tenant_id=tenant_id,
            )
        if claim.equipment_id is not None:
            self._emit(
                ClaimLinkedToEquipment(
                    claim_id=claim.id, tenant_id=tenant_id, equipment_id=claim.equipment_id
                ),
                aggregate_id=claim.id,
                aggregate_type="Claim",
                tenant_id=tenant_id,
            )
        self._session.commit()
        self._session.refresh(claim)
        return claim

    # --- transitions ---

    def _transition(self, claim_id, new_status, *, mutate=None, extra_events=None) -> Claim:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        claim = self._claims.get_by_id_or_raise(claim_id)
        if claim.is_deleted:
            raise NotFoundError(f"Claim {claim_id} not found (deleted).")
        previous = claim.status
        if new_status == previous:
            return claim
        ClaimStateMachine.validate_transition(previous, new_status)
        if mutate is not None:
            mutate(claim)
        claim.status = new_status
        claim.updated_by = actor_id
        self._session.flush()
        for factory in extra_events or []:
            self._emit(
                factory(claim, previous),
                aggregate_id=claim.id,
                aggregate_type="Claim",
                tenant_id=tenant_id,
            )
        self._session.commit()
        self._session.refresh(claim)
        return claim

    def submit_claim_for_review(self, claim_id):
        def _m(c):
            c.reviewed_at = utcnow()

        return self._transition(
            claim_id,
            ClaimStatus.UNDER_REVIEW,
            mutate=_m,
            extra_events=[
                lambda c, prev: ClaimSubmittedForReview(
                    claim_id=c.id, tenant_id=c.tenant_id, previous_status=prev.value
                )
            ],
        )

    def approve_claim(self, claim_id, *, approved_amount, allow_override=False):
        if approved_amount is None:
            raise ValidationError("approved_amount is required to approve a claim.")
        claim = self._claims.get_by_id_or_raise(claim_id)
        if claim.is_deleted:
            raise NotFoundError(f"Claim {claim_id} not found (deleted).")
        self.validate_policy_coverage(claim)
        if (
            claim.claimed_amount is not None
            and Decimal(str(approved_amount)) > claim.claimed_amount
            and not allow_override
        ):
            raise ValidationError(
                "approved_amount cannot exceed claimed_amount without an authorized override."
            )

        def _m(c: Claim):
            c.approved_amount = approved_amount
            c.approved_at = utcnow()

        return self._transition(
            claim_id,
            ClaimStatus.APPROVED,
            mutate=_m,
            extra_events=[
                lambda c, prev: ClaimApproved(
                    claim_id=c.id,
                    tenant_id=c.tenant_id,
                    previous_status=prev.value,
                    approved_amount=(
                        str(c.approved_amount) if c.approved_amount is not None else None
                    ),
                    currency_code=c.currency_code,
                )
            ],
        )

    def reject_claim(self, claim_id, *, reason):
        if not reason:
            raise ValidationError("A rejection reason is required to reject a claim.")

        def _m(c: Claim):
            c.rejected_at = utcnow()
            c.rejection_reason = reason

        return self._transition(
            claim_id,
            ClaimStatus.REJECTED,
            mutate=_m,
            extra_events=[
                lambda c, prev: ClaimRejected(
                    claim_id=c.id, tenant_id=c.tenant_id, previous_status=prev.value, reason=reason
                )
            ],
        )

    def settle_claim(self, claim_id, *, settlement_notes):
        if not settlement_notes:
            raise ValidationError("settlement_notes are required to settle a claim.")
        claim = self._claims.get_by_id_or_raise(claim_id)
        if not claim.is_deleted and claim.approved_amount is None:
            raise ValidationError("A settled claim requires an approved_amount.")

        def _m(c: Claim):
            c.settled_at = utcnow()
            c.settlement_notes = settlement_notes

        return self._transition(
            claim_id,
            ClaimStatus.SETTLED,
            mutate=_m,
            extra_events=[
                lambda c, prev: ClaimSettled(
                    claim_id=c.id,
                    tenant_id=c.tenant_id,
                    previous_status=prev.value,
                    approved_amount=(
                        str(c.approved_amount) if c.approved_amount is not None else None
                    ),
                    currency_code=c.currency_code,
                    cycle_days=self._cycle_days(c.created_at, c.settled_at),
                )
            ],
        )

    def close_claim(self, claim_id):
        def _m(c):
            c.closed_at = utcnow()

        return self._transition(
            claim_id,
            ClaimStatus.CLOSED,
            mutate=_m,
            extra_events=[
                lambda c, prev: ClaimClosed(
                    claim_id=c.id, tenant_id=c.tenant_id, previous_status=prev.value
                )
            ],
        )

    def reopen_claim(self, claim_id, *, reason=None):
        def _m(c):
            c.reopened_at = utcnow()

        return self._transition(
            claim_id,
            ClaimStatus.UNDER_REVIEW,
            mutate=_m,
            extra_events=[
                lambda c, prev: ClaimReopened(
                    claim_id=c.id, tenant_id=c.tenant_id, previous_status=prev.value, reason=reason
                )
            ],
        )

    # --- read / update ---

    def get_claim(self, claim_id, *, include_deleted=False) -> Claim:
        claim = self._claims.get_by_id(claim_id)
        if claim is None or (claim.is_deleted and not include_deleted):
            raise NotFoundError(f"Claim {claim_id} not found.")
        return claim

    def update_claim(self, claim_id, **data) -> Claim:
        self._tenant_id()
        actor_id = self._actor_id()
        claim = self._claims.get_by_id_or_raise(claim_id)
        if claim.is_deleted:
            raise NotFoundError(f"Claim {claim_id} not found (deleted).")
        if ClaimStateMachine.is_terminal(claim.status):
            raise ValidationError(f"Claim {claim_id} is closed and cannot be edited.")
        data["updated_by"] = actor_id
        self._claims.update(claim, **data)
        self._session.commit()
        self._session.refresh(claim)
        return claim

    def list_claims(self, params) -> Page[Claim]:
        items, total = self._claims.list_claims(
            q=params.q,
            status=params.status,
            claim_type=params.claim_type,
            shipment_id=params.shipment_id,
            equipment_id=params.equipment_id,
            policy_id=params.policy_id,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        return Page.create(
            items=items, total=total, params=PageParams(page=params.page, size=params.size)
        )

    search_claims = list_claims

    # --- delete / restore ---

    def delete_claim(self, claim_id) -> None:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        claim = self._claims.get_by_id_or_raise(claim_id)
        if claim.is_deleted:
            raise NotFoundError(f"Claim {claim_id} is already deleted.")
        self._claims.soft_delete(claim, deleted_by=actor_id)
        self._session.flush()
        self._emit(
            ClaimDeleted(claim_id=claim.id, tenant_id=tenant_id, deleted_by=actor_id),
            aggregate_id=claim.id,
            aggregate_type="Claim",
            tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_claim(self, claim_id) -> Claim:
        tenant_id = self._tenant_id()
        claim = self._claims.get_by_id(claim_id)
        if claim is None:
            raise NotFoundError(f"Claim {claim_id} not found.")
        if not claim.is_deleted:
            raise ValidationError(f"Claim {claim_id} is not deleted; nothing to restore.")
        self._claims.restore(claim)
        self._session.flush()
        self._emit(
            ClaimRestored(claim_id=claim.id, tenant_id=tenant_id),
            aggregate_id=claim.id,
            aggregate_type="Claim",
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(claim)
        return claim

    # --- damage reports / liability ---

    def _load_claim_owned(self, claim_id, tenant_id) -> Claim:
        claim = self._claims.get_by_id(claim_id)
        if claim is None or claim.is_deleted or claim.tenant_id != tenant_id:
            raise NotFoundError(f"Claim {claim_id} not found.")
        return claim

    def create_damage_report(self, claim_id, **data) -> DamageReport:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._load_claim_owned(claim_id, tenant_id)
        if data.get("equipment_id") is not None:
            self._owned(
                self._equipment.get_by_id(data["equipment_id"]),
                tenant_id,
                "Equipment",
                data["equipment_id"],
            )
        report = self._damage.create(
            tenant_id=tenant_id,
            claim_id=claim_id,
            reported_at=data.pop("reported_at", None) or utcnow(),
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()
        self._emit(
            DamageReportCreated(
                damage_report_id=report.id,
                tenant_id=tenant_id,
                claim_id=claim_id,
                damage_type=self._ev(report.damage_type),
            ),
            aggregate_id=report.id,
            aggregate_type="DamageReport",
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(report)
        return report

    def list_damage_reports(self, claim_id) -> List[DamageReport]:
        self._load_claim_owned(claim_id, self._tenant_id())
        return self._damage.list_damage_reports_for_claim(claim_id)

    def create_liability_record(self, claim_id, *, allow_override=False, **data) -> LiabilityRecord:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._load_claim_owned(claim_id, tenant_id)
        self.validate_liability_distribution(
            claim_id, data.get("liability_percentage"), allow_override=allow_override
        )
        record = self._liability.create(
            tenant_id=tenant_id,
            claim_id=claim_id,
            determined_at=data.pop("determined_at", None) or utcnow(),
            determined_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()
        self._emit(
            LiabilityRecordCreated(
                liability_record_id=record.id,
                tenant_id=tenant_id,
                claim_id=claim_id,
                responsible_party_type=self._ev(record.responsible_party_type),
                liability_percentage=(
                    str(record.liability_percentage)
                    if record.liability_percentage is not None
                    else None
                ),
            ),
            aggregate_id=record.id,
            aggregate_type="LiabilityRecord",
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(record)
        return record

    def list_liability_records(self, claim_id) -> List[LiabilityRecord]:
        self._load_claim_owned(claim_id, self._tenant_id())
        return self._liability.list_liability_records_for_claim(claim_id)
