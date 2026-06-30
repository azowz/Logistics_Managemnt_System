"""Unit tests for InsuranceService and ClaimsService with mocked repos/context."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import (
    ClaimStatus,
    ClaimType,
    InsurancePolicyStatus,
    InsurancePolicyType,
)
from app.services.claims_service import ClaimsService
from app.services.exceptions import ConflictError, NotFoundError, StatusTransitionError, ValidationError
from app.services.insurance_service import InsuranceService

TENANT = uuid.uuid4()
USER = uuid.uuid4()
POLICY = uuid.uuid4()
CLAIM = uuid.uuid4()


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.insurance_service.get_current_tenant", return_value=TENANT),
        patch("app.services.insurance_service.get_current_user_id", return_value=USER),
        patch("app.services.claims_service.get_current_tenant", return_value=TENANT),
        patch("app.services.claims_service.get_current_user_id", return_value=USER),
    ):
        yield


# ---------------- InsuranceService ----------------


def _policy(*, status=InsurancePolicyStatus.DRAFT, is_deleted=False, covers_shipment=True):
    p = MagicMock()
    p.id = POLICY
    p.tenant_id = TENANT
    p.status = status
    p.is_deleted = is_deleted
    p.policy_type = InsurancePolicyType.CARGO
    p.policy_number = "POL-1"
    p.covers_shipment = covers_shipment
    p.covers_equipment = True
    p.covers_third_party = True
    return p


def _make_insurance():
    session = MagicMock()
    with (
        patch("app.services.insurance_service.InsurancePolicyRepository") as MP,
        patch("app.services.insurance_service.CoverageRuleRepository") as MC,
        patch("app.services.insurance_service.EventStoreRepository") as ME,
    ):
        svc = InsuranceService(session)
        svc._policies = MP.return_value
        svc._rules = MC.return_value
        svc._event_repo = ME.return_value
        svc._event_repo.next_aggregate_version.return_value = 1
        svc._policies.get_by_number.return_value = None
    return svc, session


def test_create_policy():
    svc, session = _make_insurance()
    svc._policies.create.return_value = _policy()
    svc.create_policy(policy_number="POL-1", policy_type=InsurancePolicyType.CARGO)
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()


def test_create_policy_duplicate():
    svc, session = _make_insurance()
    svc._policies.get_by_number.return_value = _policy()
    with pytest.raises(ConflictError):
        svc.create_policy(policy_number="POL-DUP", policy_type=InsurancePolicyType.CARGO)


def test_policy_lifecycle():
    svc, session = _make_insurance()
    svc._policies.get_by_id_or_raise.return_value = _policy(status=InsurancePolicyStatus.DRAFT)
    assert svc.activate_policy(POLICY).status == InsurancePolicyStatus.ACTIVE
    svc._policies.get_by_id_or_raise.return_value = _policy(status=InsurancePolicyStatus.ACTIVE)
    assert svc.suspend_policy(POLICY).status == InsurancePolicyStatus.SUSPENDED
    svc._policies.get_by_id_or_raise.return_value = _policy(status=InsurancePolicyStatus.ACTIVE)
    assert svc.cancel_policy(POLICY).status == InsurancePolicyStatus.CANCELLED


def test_policy_invalid_transition():
    svc, session = _make_insurance()
    svc._policies.get_by_id_or_raise.return_value = _policy(status=InsurancePolicyStatus.DRAFT)
    with pytest.raises(StatusTransitionError):
        svc.suspend_policy(POLICY)  # draft → suspended illegal


def test_coverage_rule_create_and_update():
    svc, session = _make_insurance()
    svc._policies.get_by_id.return_value = _policy()
    rule = MagicMock(id=uuid.uuid4(), tenant_id=TENANT, policy_id=POLICY)
    rule.coverage_type = MagicMock(value="shipment_loss")
    svc._rules.create.return_value = rule
    svc.create_coverage_rule(policy_id=POLICY, coverage_type="shipment_loss")
    svc._rules.get_by_id_or_raise.return_value = rule
    rule.is_deleted = False
    svc.update_coverage_rule(rule.id, active=False)
    assert svc._event_repo.append.call_count == 2


def test_get_update_list_policy():
    svc, session = _make_insurance()
    svc._policies.get_by_id.return_value = _policy()
    assert svc.get_policy(POLICY).id == POLICY
    svc._policies.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_policy(POLICY)
    svc._policies.get_by_id_or_raise.return_value = _policy(status=InsurancePolicyStatus.ACTIVE)
    svc.update_policy(POLICY, notes="x")
    svc._policies.update.assert_called_once()
    svc._policies.list_policies.return_value = ([_policy()], 1)
    from app.schemas.insurance import InsurancePolicyListParams
    assert svc.list_policies(InsurancePolicyListParams()).total == 1


def test_update_terminal_policy_blocked():
    svc, session = _make_insurance()
    svc._policies.get_by_id_or_raise.return_value = _policy(status=InsurancePolicyStatus.CANCELLED)
    with pytest.raises(ValidationError, match="terminal"):
        svc.update_policy(POLICY, notes="x")


def test_coverage_rule_cross_tenant_policy():
    svc, session = _make_insurance()
    svc._policies.get_by_id.return_value = _policy(is_deleted=False)
    svc._policies.get_by_id.return_value.tenant_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="Policy"):
        svc.create_coverage_rule(policy_id=POLICY, coverage_type="shipment_loss")


# ---------------- ClaimsService ----------------


def _claim(*, status=ClaimStatus.CREATED, is_deleted=False, claim_type=ClaimType.SHIPMENT_LOSS,
           claimed_amount=Decimal("1000"), policy_id=POLICY):
    c = MagicMock()
    c.id = CLAIM
    c.tenant_id = TENANT
    c.status = status
    c.is_deleted = is_deleted
    c.claim_type = claim_type
    c.claim_number = "CLM-1"
    c.policy_id = policy_id
    c.shipment_id = None
    c.equipment_id = None
    c.claimed_amount = claimed_amount
    c.approved_amount = None
    return c


def _owned(*, tenant_id=TENANT, is_deleted=False):
    o = MagicMock(); o.tenant_id = tenant_id; o.is_deleted = is_deleted
    return o


def _make_claims():
    session = MagicMock()
    with (
        patch("app.services.claims_service.ClaimRepository") as MC,
        patch("app.services.claims_service.InsurancePolicyRepository") as MP,
        patch("app.services.claims_service.DamageReportRepository") as MD,
        patch("app.services.claims_service.LiabilityRecordRepository") as ML,
        patch("app.services.claims_service.ShipmentRepository") as MS,
        patch("app.services.claims_service.OrderRepository") as MO,
        patch("app.services.claims_service.CustomerRepository") as MCu,
        patch("app.services.claims_service.EquipmentRepository") as ME_,
        patch("app.services.claims_service.ComplianceCheckRepository") as MCh,
        patch("app.services.claims_service.PermitRepository") as MPe,
        patch("app.services.claims_service.EventStoreRepository") as MEv,
    ):
        svc = ClaimsService(session)
        svc._claims = MC.return_value
        svc._policies = MP.return_value
        svc._damage = MD.return_value
        svc._liability = ML.return_value
        svc._shipments = MS.return_value
        svc._orders = MO.return_value
        svc._customers = MCu.return_value
        svc._equipment = ME_.return_value
        svc._checks = MCh.return_value
        svc._permits = MPe.return_value
        svc._event_repo = MEv.return_value
        svc._event_repo.next_aggregate_version.return_value = 1
        svc._claims.get_by_number.return_value = None
        svc._policies.get_by_id.return_value = _policy(status=InsurancePolicyStatus.ACTIVE)
        svc._liability.total_liability_percentage.return_value = 0.0
    return svc, session


def test_create_claim():
    svc, session = _make_claims()
    svc._claims.create.return_value = _claim()
    svc.create_claim(claim_type=ClaimType.SHIPMENT_LOSS, policy_id=POLICY)
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called()


def test_create_equipment_damage_requires_equipment():
    svc, session = _make_claims()
    with pytest.raises(ValidationError, match="equipment_id"):
        svc.create_claim(claim_type=ClaimType.EQUIPMENT_DAMAGE)


def test_create_claim_cross_tenant_shipment():
    svc, session = _make_claims()
    svc._shipments.get_by_id.return_value = _owned(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Shipment"):
        svc.create_claim(claim_type=ClaimType.SHIPMENT_LOSS, shipment_id=uuid.uuid4())


def test_claim_review_approve_settle_close():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.CREATED)
    assert svc.submit_claim_for_review(CLAIM).status == ClaimStatus.UNDER_REVIEW
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.UNDER_REVIEW)
    approved = svc.approve_claim(CLAIM, approved_amount=Decimal("500"))
    assert approved.status == ClaimStatus.APPROVED
    settled_claim = _claim(status=ClaimStatus.APPROVED)
    settled_claim.approved_amount = Decimal("500")
    svc._claims.get_by_id_or_raise.return_value = settled_claim
    assert svc.settle_claim(CLAIM, settlement_notes="paid").status == ClaimStatus.SETTLED
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.SETTLED)
    assert svc.close_claim(CLAIM).status == ClaimStatus.CLOSED


def test_approve_requires_amount():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.UNDER_REVIEW)
    with pytest.raises(ValidationError, match="approved_amount"):
        svc.approve_claim(CLAIM, approved_amount=None)


def test_approve_exceeds_claimed_without_override():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.UNDER_REVIEW, claimed_amount=Decimal("100"))
    with pytest.raises(ValidationError, match="exceed"):
        svc.approve_claim(CLAIM, approved_amount=Decimal("500"))


def test_approve_without_active_policy_blocked():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.UNDER_REVIEW)
    svc._policies.get_by_id.return_value = _policy(status=InsurancePolicyStatus.SUSPENDED)
    with pytest.raises(ValidationError, match="active"):
        svc.approve_claim(CLAIM, approved_amount=Decimal("500"))


def test_approve_policy_does_not_cover_type():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.UNDER_REVIEW)
    svc._policies.get_by_id.return_value = _policy(status=InsurancePolicyStatus.ACTIVE, covers_shipment=False)
    with pytest.raises(ValidationError, match="does not cover"):
        svc.approve_claim(CLAIM, approved_amount=Decimal("500"))


def test_reject_requires_reason():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.UNDER_REVIEW)
    with pytest.raises(ValidationError, match="rejection reason"):
        svc.reject_claim(CLAIM, reason="")


def test_settle_requires_approved_amount():
    svc, session = _make_claims()
    c = _claim(status=ClaimStatus.APPROVED); c.approved_amount = None
    svc._claims.get_by_id_or_raise.return_value = c
    with pytest.raises(ValidationError, match="approved_amount"):
        svc.settle_claim(CLAIM, settlement_notes="x")


def test_reopen_closed_claim():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.CLOSED)
    assert svc.reopen_claim(CLAIM, reason="new evidence").status == ClaimStatus.UNDER_REVIEW


def test_liability_distribution_exceeds_100():
    svc, session = _make_claims()
    svc._claims.get_by_id.return_value = _claim()
    svc._liability.total_liability_percentage.return_value = 80.0
    with pytest.raises(ValidationError, match="exceed 100"):
        svc.create_liability_record(CLAIM, responsible_party_type="carrier", liability_percentage=Decimal("30"))


def test_liability_override_allows_excess():
    svc, session = _make_claims()
    svc._claims.get_by_id.return_value = _claim()
    svc._liability.total_liability_percentage.return_value = 80.0
    svc._liability.create.return_value = MagicMock(id=uuid.uuid4(), tenant_id=TENANT, claim_id=CLAIM,
                                                   responsible_party_type=MagicMock(value="carrier"),
                                                   liability_percentage=Decimal("30"))
    svc.create_liability_record(CLAIM, allow_override=True, responsible_party_type="carrier",
                                liability_percentage=Decimal("30"))
    svc._event_repo.append.assert_called()


def test_delete_restore_claim():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim()
    svc.delete_claim(CLAIM)
    svc._claims.soft_delete.assert_called_once()
    svc._claims.get_by_id.return_value = _claim(is_deleted=True)
    svc.restore_claim(CLAIM)
    svc._claims.restore.assert_called_once()


def test_create_damage_report():
    svc, session = _make_claims()
    svc._claims.get_by_id.return_value = _claim()
    svc._damage.create.return_value = MagicMock(id=uuid.uuid4(), tenant_id=TENANT, claim_id=CLAIM,
                                                damage_type=MagicMock(value="cargo_damage"))
    svc.create_damage_report(CLAIM, damage_type="cargo_damage", severity="high")
    svc._event_repo.append.assert_called()


def test_get_update_list_claim():
    svc, session = _make_claims()
    svc._claims.get_by_id.return_value = _claim()
    assert svc.get_claim(CLAIM).id == CLAIM
    svc._claims.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_claim(CLAIM)
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.CREATED)
    svc.update_claim(CLAIM, notes="x")
    svc._claims.update.assert_called_once()
    svc._claims.list_claims.return_value = ([_claim()], 1)
    from app.schemas.insurance import ClaimListParams
    assert svc.list_claims(ClaimListParams()).total == 1


def test_update_closed_claim_blocked():
    svc, session = _make_claims()
    svc._claims.get_by_id_or_raise.return_value = _claim(status=ClaimStatus.CLOSED)
    with pytest.raises(ValidationError, match="closed"):
        svc.update_claim(CLAIM, notes="x")


def test_list_damage_and_liability():
    svc, session = _make_claims()
    svc._claims.get_by_id.return_value = _claim()
    svc._damage.list_damage_reports_for_claim.return_value = []
    svc._liability.list_liability_records_for_claim.return_value = []
    assert svc.list_damage_reports(CLAIM) == []
    assert svc.list_liability_records(CLAIM) == []


def test_restore_not_deleted_claim():
    svc, session = _make_claims()
    svc._claims.get_by_id.return_value = _claim(is_deleted=False)
    with pytest.raises(ValidationError, match="not deleted"):
        svc.restore_claim(CLAIM)
