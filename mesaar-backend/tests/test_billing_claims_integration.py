"""Integration tests proving Billing consumes Claims outcomes without owning the
claim lifecycle (Sprint 9, context #18 ↔ #17)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.billing import Invoice, Settlement
from app.models.enums import ClaimStatus, SettlementStatus, SettlementType
from app.models.insurance import Claim
from app.services.exceptions import ValidationError
from app.services.settlement_service import SettlementService
from billing_sqlite import make_engine, seed_claim, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.settlement_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.settlement_service.get_current_user_id", return_value=_USER),
        patch("app.services.settlement_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


def _svc():
    return SettlementService(_Session())


def test_settlement_references_approved_claim():
    cid = uuid.uuid4()
    seed_claim(
        _Session,
        tenant_id=_TENANT,
        claim_id=cid,
        status="approved",
        approved_amount=1000,
    )
    stl = _svc().create_settlement(
        settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("600")
    )
    assert stl.claim_id == cid and stl.status == SettlementStatus.DRAFT


def test_settlement_rejects_unapproved_claim():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="created", approved_amount=0)
    with pytest.raises(ValidationError):
        _svc().create_settlement(
            settlement_type=SettlementType.CLAIM_PAYOUT,
            claim_id=cid,
            amount=Decimal("1"),
        )


def test_settlement_rejects_cross_tenant_claim():
    other = uuid.uuid4()
    cid = uuid.uuid4()
    seed_tenant_user(_Session, tenant_id=other, user_id=uuid.uuid4())
    seed_claim(_Session, tenant_id=other, claim_id=cid, status="approved", approved_amount=1000)
    with pytest.raises(ValidationError):
        _svc().create_settlement(
            settlement_type=SettlementType.CLAIM_PAYOUT,
            claim_id=cid,
            amount=Decimal("1"),
        )


def test_settlement_amount_bounded_by_approved_claim_amount():
    cid = uuid.uuid4()
    seed_claim(
        _Session,
        tenant_id=_TENANT,
        claim_id=cid,
        status="approved",
        approved_amount=500,
    )
    with pytest.raises(ValidationError):
        _svc().create_settlement(
            settlement_type=SettlementType.CLAIM_PAYOUT,
            claim_id=cid,
            amount=Decimal("600"),
        )


def test_settlement_can_be_settled_after_approval():
    cid = uuid.uuid4()
    seed_claim(
        _Session,
        tenant_id=_TENANT,
        claim_id=cid,
        status="approved",
        approved_amount=1000,
    )
    svc = _svc()
    stl = svc.create_settlement(
        settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("400")
    )
    svc.submit_settlement_for_approval(stl.id)
    svc.approve_settlement(stl.id)
    settled = svc.settle_settlement(stl.id)
    assert settled.status == SettlementStatus.SETTLED


def test_claim_lifecycle_unchanged_by_settlement():
    cid = uuid.uuid4()
    seed_claim(
        _Session,
        tenant_id=_TENANT,
        claim_id=cid,
        status="approved",
        approved_amount=1000,
    )
    svc = _svc()
    stl = svc.consume_claim_settlement(claim_id=cid, amount=Decimal("700"))
    # the claim row is untouched — Billing never mutates the claim aggregate
    s = _Session()
    try:
        claim = s.get(Claim, cid)
        assert claim.status == ClaimStatus.APPROVED
        assert claim.approved_amount == Decimal("1000.00")
    finally:
        s.close()
    assert stl.amount == Decimal("700.00")


def test_offset_settlement_also_bounded():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="settled", approved_amount=200)
    with pytest.raises(ValidationError):
        _svc().create_settlement(
            settlement_type=SettlementType.CLAIM_OFFSET,
            claim_id=cid,
            amount=Decimal("250"),
        )


@pytest.mark.parametrize(
    "settlement_type", [SettlementType.CLAIM_PAYOUT, SettlementType.CLAIM_OFFSET]
)
def test_update_cannot_bypass_approved_claim_amount(settlement_type):
    claim_id = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=claim_id, approved_amount=500)
    with _Session() as session:
        service = SettlementService(session)
        settlement = service.create_settlement(
            settlement_type=settlement_type, claim_id=claim_id, amount=Decimal("400")
        )
        with pytest.raises(ValidationError, match="exceeds the approved claim amount"):
            service.update_settlement(settlement.id, amount=Decimal("600"))
        session.rollback()
        assert service.get_settlement(settlement.id).amount == Decimal("400.00")


def test_rejected_claim_adjustment_does_not_leave_a_settlement():
    claim_id, invoice_id = uuid.uuid4(), uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=claim_id, approved_amount=500)
    with _Session() as session:
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=_TENANT,
                invoice_number=f"INV-{invoice_id.hex}",
                status="paid",
                total_amount=Decimal("100"),
            )
        )
        session.commit()
        with pytest.raises(ValidationError, match="paid"):
            SettlementService(session).consume_claim_settlement(
                claim_id=claim_id, amount=Decimal("100"), invoice_id=invoice_id
            )

    with _Session() as session:
        assert session.scalar(select(Settlement).where(Settlement.claim_id == claim_id)) is None
        assert session.get(Invoice, invoice_id).claim_adjustment_amount == Decimal("0.00")


def test_failed_consumed_event_rolls_back_settlement_and_invoice_together():
    claim_id, invoice_id = uuid.uuid4(), uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=claim_id, approved_amount=500)
    with _Session() as session:
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=_TENANT,
                invoice_number=f"INV-{invoice_id.hex}",
                status="issued",
                subtotal_amount=Decimal("200"),
                total_amount=Decimal("200"),
            )
        )
        session.commit()
        service = SettlementService(session)

        def fail_consumed_event(envelope):
            if envelope.event_type == "ClaimSettlementConsumed":
                raise RuntimeError("outbox unavailable")

        service._event_repo.append.side_effect = fail_consumed_event
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            service.consume_claim_settlement(
                claim_id=claim_id, amount=Decimal("100"), invoice_id=invoice_id
            )

    with _Session() as session:
        assert session.scalar(select(Settlement).where(Settlement.claim_id == claim_id)) is None
        invoice = session.get(Invoice, invoice_id)
        assert invoice.total_amount == Decimal("200.00")
        assert invoice.claim_adjustment_amount == Decimal("0.00")


def test_claim_consumption_commits_once_after_both_events():
    claim_id = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=claim_id, approved_amount=500)
    with _Session() as session:
        service = SettlementService(session)
        with patch.object(session, "commit", wraps=session.commit) as commit:
            service.consume_claim_settlement(claim_id=claim_id, amount=Decimal("100"))
        commit.assert_called_once()
        assert [c.args[0].event_type for c in service._event_repo.append.call_args_list] == [
            "SettlementCreated",
            "ClaimSettlementConsumed",
        ]
