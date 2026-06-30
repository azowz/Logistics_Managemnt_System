"""Unit tests for ComplianceService with mocked repositories / event store / context."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import EscortStatus, PermitStatus, PermitType
from app.services.compliance_service import ComplianceService
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    ValidationError,
)

TENANT = uuid.uuid4()
USER = uuid.uuid4()
PERMIT = uuid.uuid4()
ESCORT = uuid.uuid4()


def _permit(*, status=PermitStatus.DRAFT, is_deleted=False):
    p = MagicMock()
    p.id = PERMIT
    p.tenant_id = TENANT
    p.status = status
    p.is_deleted = is_deleted
    p.permit_type = PermitType.OVERSIZE
    p.permit_number = "PMT-1"
    p.shipment_id = None
    p.equipment_id = None
    p.valid_from = None
    p.valid_until = None
    return p


def _escort(*, status=EscortStatus.PLANNED, is_deleted=False):
    e = MagicMock()
    e.id = ESCORT
    e.tenant_id = TENANT
    e.status = status
    e.is_deleted = is_deleted
    e.escort_type = MagicMock(value="police_escort")
    e.shipment_id = None
    e.permit_id = None
    e.scheduled_start = None
    e.scheduled_end = None
    return e


def _make():
    session = MagicMock()
    with (
        patch("app.services.compliance_service.PermitRepository") as MP,
        patch("app.services.compliance_service.EscortRepository") as ME_,
        patch("app.services.compliance_service.RouteRestrictionRepository") as MR,
        patch("app.services.compliance_service.AxleWeightProfileRepository") as MA,
        patch("app.services.compliance_service.ComplianceCheckRepository") as MC,
        patch("app.services.compliance_service.OperatorCertificationRepository") as MO,
        patch("app.services.compliance_service.ShipmentRepository") as MS,
        patch("app.services.compliance_service.EquipmentRepository") as MEq,
        patch("app.services.compliance_service.VehicleRepository") as MV,
        patch("app.services.compliance_service.UserRepository") as MU,
        patch("app.services.compliance_service.EventStoreRepository") as MEv,
        patch("app.services.compliance_service.ComplianceValidationService"),
    ):
        svc = ComplianceService(session)
        svc._permits = MP.return_value
        svc._escorts = ME_.return_value
        svc._restrictions = MR.return_value
        svc._axles = MA.return_value
        svc._checks = MC.return_value
        svc._certs = MO.return_value
        svc._shipments = MS.return_value
        svc._equipment = MEq.return_value
        svc._vehicles = MV.return_value
        svc._users = MU.return_value
        svc._event_repo = MEv.return_value
        svc._event_repo.next_aggregate_version.return_value = 1
        svc._permits.get_by_number.return_value = None
    return svc, session


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.compliance_service.get_current_tenant", return_value=TENANT),
        patch("app.services.compliance_service.get_current_user_id", return_value=USER),
    ):
        yield


# --- permits --------------------------------------------------------------


def test_create_permit_happy():
    svc, session = _make()
    svc._permits.create.return_value = _permit()
    svc.create_permit(permit_number="PMT-1", permit_type=PermitType.OVERSIZE)
    svc._permits.create.assert_called_once()
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()


def test_create_permit_generates_number():
    svc, session = _make()
    svc._permits.create.return_value = _permit()
    svc.create_permit(permit_type=PermitType.OVERSIZE)
    assert svc._permits.create.call_args.kwargs["permit_number"].startswith("PMT-")


def test_create_permit_duplicate():
    svc, session = _make()
    svc._permits.get_by_number.return_value = _permit()
    with pytest.raises(ConflictError, match="already exists"):
        svc.create_permit(permit_number="PMT-DUP", permit_type=PermitType.OVERSIZE)


def test_create_permit_cross_tenant_shipment():
    svc, session = _make()
    foreign = MagicMock(tenant_id=uuid.uuid4(), is_deleted=False)
    svc._shipments.get_by_id.return_value = foreign
    with pytest.raises(ValidationError, match="Shipment"):
        svc.create_permit(permit_type=PermitType.OVERSIZE, shipment_id=uuid.uuid4())


def test_permit_full_lifecycle():
    svc, session = _make()
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.DRAFT)
    assert svc.submit_permit(PERMIT).status == PermitStatus.SUBMITTED
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.SUBMITTED)
    assert svc.mark_under_review(PERMIT).status == PermitStatus.UNDER_REVIEW
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.UNDER_REVIEW)
    assert svc.approve_permit(PERMIT).status == PermitStatus.APPROVED
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.APPROVED)
    assert svc.activate_permit(PERMIT).status == PermitStatus.ACTIVE
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.ACTIVE)
    assert svc.expire_permit(PERMIT).status == PermitStatus.EXPIRED


def test_permit_reject_and_cancel():
    svc, session = _make()
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.UNDER_REVIEW)
    assert svc.reject_permit(PERMIT, reason="incomplete").status == PermitStatus.REJECTED
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.APPROVED)
    assert svc.cancel_permit(PERMIT, reason="withdrawn").status == PermitStatus.CANCELLED


def test_permit_invalid_transition():
    svc, session = _make()
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.DRAFT)
    with pytest.raises(StatusTransitionError):
        svc.activate_permit(PERMIT)  # draft → active illegal


def test_permit_idempotent_noop():
    svc, session = _make()
    p = _permit(status=PermitStatus.SUBMITTED)
    svc._permits.get_by_id_or_raise.return_value = p
    result = svc._permit_transition(PERMIT, PermitStatus.SUBMITTED)
    assert result is p
    session.commit.assert_not_called()


def test_permit_delete_restore():
    svc, session = _make()
    svc._permits.get_by_id_or_raise.return_value = _permit()
    svc.delete_permit(PERMIT)
    svc._permits.soft_delete.assert_called_once()
    svc._permits.get_by_id.return_value = _permit(is_deleted=True)
    svc.restore_permit(PERMIT)
    svc._permits.restore.assert_called_once()


# --- escorts --------------------------------------------------------------


def test_escort_create_schedule_cancel():
    svc, session = _make()
    svc._escorts.create.return_value = _escort()
    svc.create_escort(escort_type="police_escort")
    svc._escorts.get_by_id_or_raise.return_value = _escort(status=EscortStatus.PLANNED)
    assert svc.schedule_escort(ESCORT).status == EscortStatus.SCHEDULED
    svc._escorts.get_by_id_or_raise.return_value = _escort(status=EscortStatus.SCHEDULED)
    assert svc.cancel_escort(ESCORT).status == EscortStatus.CANCELLED


def test_schedule_cancelled_escort_raises():
    svc, session = _make()
    svc._escorts.get_by_id_or_raise.return_value = _escort(status=EscortStatus.CANCELLED)
    with pytest.raises(ConflictError):
        svc.schedule_escort(ESCORT)


# --- route restrictions / axle / certs ------------------------------------


def test_create_and_update_route_restriction():
    svc, session = _make()
    rr = MagicMock(id=uuid.uuid4(), tenant_id=TENANT, is_deleted=False)
    rr.restriction_type = MagicMock(value="height_limit")
    rr.region = "Riyadh"
    svc._restrictions.create.return_value = rr
    svc.create_route_restriction(restriction_type="height_limit", region="Riyadh")
    svc._restrictions.get_by_id_or_raise.return_value = rr
    svc.update_route_restriction(rr.id, active=False)
    assert svc._event_repo.append.call_count == 2


def test_create_axle_profile():
    svc, session = _make()
    svc._axles.create.return_value = MagicMock(id=uuid.uuid4(), tenant_id=TENANT,
                                               equipment_id=None, vehicle_id=None, is_compliant=True)
    svc.create_axle_weight_profile(axle_count=3, total_weight=30000)
    svc._event_repo.append.assert_called_once()


def test_operator_certification_create_expire():
    svc, session = _make()
    svc._users.get_by_id.return_value = MagicMock(tenant_id=TENANT, is_deleted=False)
    cert = MagicMock(id=uuid.uuid4(), tenant_id=TENANT, user_id=USER, certification_type="crane")
    cert.status = MagicMock(value="active")
    svc._certs.create.return_value = cert
    svc.create_operator_certification(user_id=USER, certification_type="crane")
    svc._event_repo.append.assert_called()

    from app.models.enums import OperatorCertificationStatus
    live = MagicMock(id=cert.id, tenant_id=TENANT, is_deleted=False, status=OperatorCertificationStatus.ACTIVE)
    svc._certs.get_by_id_or_raise.return_value = live
    result = svc.expire_operator_certification(cert.id)
    assert result.status == OperatorCertificationStatus.EXPIRED


def test_create_cert_cross_tenant_user():
    svc, session = _make()
    svc._users.get_by_id.return_value = MagicMock(tenant_id=uuid.uuid4(), is_deleted=False)
    with pytest.raises(ValidationError, match="User"):
        svc.create_operator_certification(user_id=uuid.uuid4(), certification_type="crane")


# --- override -------------------------------------------------------------


def test_update_permit_and_terminal_block():
    svc, session = _make()
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.DRAFT)
    svc.update_permit(PERMIT, notes="x")
    svc._permits.update.assert_called_once()
    svc._permits.get_by_id_or_raise.return_value = _permit(status=PermitStatus.EXPIRED)
    with pytest.raises(ValidationError, match="terminal"):
        svc.update_permit(PERMIT, notes="y")


def test_get_permit_and_missing():
    svc, session = _make()
    svc._permits.get_by_id.return_value = _permit()
    assert svc.get_permit(PERMIT).id == PERMIT
    svc._permits.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_permit(PERMIT)


def test_get_check_missing():
    svc, session = _make()
    svc._checks.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_check(uuid.uuid4())


def test_list_page_helpers():
    svc, session = _make()
    svc._permits.list_permits.return_value = ([_permit()], 1)
    svc._escorts.list_escorts.return_value = ([_escort()], 1)
    svc._checks.list_checks.return_value = ([], 0)
    assert svc.list_permits(_lp()).total == 1
    assert svc.list_escorts(_lp(escort=True)).total == 1
    assert svc.list_checks(_lp(check=True)).total == 0


def _lp(*, escort=False, check=False):
    from app.schemas.compliance import (
        ComplianceCheckListParams,
        EscortListParams,
        PermitListParams,
    )
    if escort:
        return EscortListParams()
    if check:
        return ComplianceCheckListParams()
    return PermitListParams()


def test_validate_dispatch_clearance_delegates_to_gate():
    svc, session = _make()
    svc._shipments.get_by_id.return_value = MagicMock(tenant_id=TENANT, is_deleted=False)
    from app.services.compliance_service import DispatchGateResult
    svc._gate = MagicMock()
    svc._gate.validate_dispatch.return_value = DispatchGateResult(allowed=True)
    result = svc.validate_dispatch_clearance(uuid.uuid4(), stage="assign")
    assert result.allowed is True
    svc._gate.validate_dispatch.assert_called_once()


def test_validate_dispatch_clearance_cross_tenant_shipment():
    svc, session = _make()
    svc._shipments.get_by_id.return_value = MagicMock(tenant_id=uuid.uuid4(), is_deleted=False)
    with pytest.raises(ValidationError, match="Shipment"):
        svc.validate_dispatch_clearance(uuid.uuid4())


def test_list_helpers():
    svc, session = _make()
    svc._certs.list_certifications.return_value = ([], 0)
    svc._restrictions.list_restrictions.return_value = ([], 0)
    assert svc.list_certifications(user_id=USER) == ([], 0)
    assert svc.list_route_restrictions(region="X") == ([], 0)


def test_apply_override():
    svc, session = _make()
    from app.models.enums import ComplianceCheckStatus
    check = MagicMock(id=uuid.uuid4(), tenant_id=TENANT, is_deleted=False,
                      status=ComplianceCheckStatus.FAILED, blocking=True)
    svc._checks.get_by_id_or_raise.return_value = check
    svc.apply_compliance_override(check.id, reason="authorized")
    assert check.status == ComplianceCheckStatus.OVERRIDDEN
    assert check.blocking is False
    svc._event_repo.append.assert_called_once()
