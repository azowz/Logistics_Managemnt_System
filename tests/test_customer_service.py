"""Unit tests for CustomerService.

All external collaborators (repository, event store, context vars) are mocked.
No database connection is required.

Coverage:
  * create_customer — happy path, duplicate code, duplicate CR, duplicate VAT
  * get_customer — found, not found, soft-deleted (include/exclude)
  * list_customers — delegates to repo; pagination envelope
  * update_customer — partial update, contact-only changes, conflict guard
  * activate_customer / suspend_customer — valid transitions, invalid transitions, idempotent
  * delete_customer — happy path, already-deleted guard
  * restore_customer — happy path, not-deleted guard
"""

from __future__ import annotations

import uuid
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import CustomerStatus, CustomerType, RiskLevel, CreditStatus
from app.services.customer_service import CustomerService
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    ValidationError,
)

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_customer(
    *,
    status: CustomerStatus = CustomerStatus.ACTIVE,
    is_deleted: bool = False,
) -> MagicMock:
    c = MagicMock()
    c.id = CUSTOMER_ID
    c.tenant_id = TENANT_ID
    c.code = "TEST-001"
    c.company_name = "Test Corp"
    c.customer_type = CustomerType.CORPORATE
    c.status = status
    c.risk_level = RiskLevel.LOW
    c.credit_status = CreditStatus.GOOD
    c.commercial_registration = None
    c.vat_number = None
    c.is_deleted = is_deleted
    c.deleted_at = MagicMock() if is_deleted else None
    return c


def _make_service() -> tuple[CustomerService, MagicMock, MagicMock, MagicMock]:
    """Return (svc, mock_session, mock_repo, mock_event_repo)."""
    session = MagicMock()

    with (
        patch("app.services.customer_service.CustomerRepository") as MockRepo,
        patch("app.services.customer_service.EventStoreRepository") as MockEventRepo,
    ):
        mock_repo = MockRepo.return_value
        mock_event_repo = MockEventRepo.return_value
        mock_event_repo.next_aggregate_version.return_value = 1
        mock_event_repo.append.return_value = None

        svc = CustomerService(session)
        svc._repo = mock_repo
        svc._event_repo = mock_event_repo

    return svc, session, mock_repo, mock_event_repo


@pytest.fixture(autouse=True)
def patch_context_vars():
    """Patch tenant/user context vars used by CustomerService."""
    with (
        patch(
            "app.services.customer_service.get_current_tenant",
            return_value=TENANT_ID,
        ),
        patch(
            "app.services.customer_service.get_current_user_id",
            return_value=USER_ID,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# create_customer
# ---------------------------------------------------------------------------


def test_create_customer_happy_path():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer()

    repo.get_by_code.return_value = None
    repo.create.return_value = customer

    result = svc.create_customer(
        code="TEST-001",
        company_name="Test Corp",
        customer_type=CustomerType.CORPORATE,
    )

    repo.create.assert_called_once()
    session.flush.assert_called()
    session.commit.assert_called()
    event_repo.append.assert_called_once()
    assert result is customer


def test_create_customer_duplicate_code_raises_conflict():
    svc, session, repo, _ = _make_service()
    repo.get_by_code.return_value = _make_customer()

    with pytest.raises(ConflictError, match="already exists"):
        svc.create_customer(
            code="TEST-001",
            company_name="Test Corp",
            customer_type=CustomerType.CORPORATE,
        )

    repo.create.assert_not_called()
    session.commit.assert_not_called()


def test_create_customer_duplicate_commercial_registration_raises_conflict():
    svc, session, repo, _ = _make_service()
    repo.get_by_code.return_value = None
    repo.get_by_commercial_registration.return_value = _make_customer()

    with pytest.raises(ConflictError, match="Commercial registration"):
        svc.create_customer(
            code="NEW-001",
            company_name="Test Corp",
            customer_type=CustomerType.CORPORATE,
            commercial_registration="CR-999",
        )

    session.commit.assert_not_called()


def test_create_customer_duplicate_vat_raises_conflict():
    svc, session, repo, _ = _make_service()
    repo.get_by_code.return_value = None
    repo.get_by_commercial_registration.return_value = None
    repo.get_by_vat_number.return_value = _make_customer()

    with pytest.raises(ConflictError, match="VAT number"):
        svc.create_customer(
            code="NEW-001",
            company_name="Test Corp",
            customer_type=CustomerType.CORPORATE,
            vat_number="VAT-123",
        )

    session.commit.assert_not_called()


def test_create_customer_code_uppercased():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer()
    repo.get_by_code.return_value = None
    repo.create.return_value = customer

    svc.create_customer(
        code="lower",
        company_name="Corp",
        customer_type=CustomerType.CORPORATE,
    )

    call_kwargs = repo.create.call_args.kwargs
    assert call_kwargs["code"] == "LOWER"


# ---------------------------------------------------------------------------
# get_customer
# ---------------------------------------------------------------------------


def test_get_customer_returns_existing():
    svc, _, repo, _ = _make_service()
    customer = _make_customer()
    repo.get_by_id.return_value = customer

    result = svc.get_customer(CUSTOMER_ID)
    assert result is customer


def test_get_customer_raises_not_found_when_missing():
    svc, _, repo, _ = _make_service()
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        svc.get_customer(CUSTOMER_ID)


def test_get_customer_raises_not_found_for_soft_deleted_when_not_including():
    svc, _, repo, _ = _make_service()
    repo.get_by_id.return_value = _make_customer(is_deleted=True)

    with pytest.raises(NotFoundError):
        svc.get_customer(CUSTOMER_ID, include_deleted=False)


def test_get_customer_returns_soft_deleted_when_include_deleted():
    svc, _, repo, _ = _make_service()
    customer = _make_customer(is_deleted=True)
    repo.get_by_id.return_value = customer

    result = svc.get_customer(CUSTOMER_ID, include_deleted=True)
    assert result is customer


# ---------------------------------------------------------------------------
# list_customers
# ---------------------------------------------------------------------------


def test_list_customers_returns_page():
    svc, _, repo, _ = _make_service()
    customers = [_make_customer() for _ in range(3)]
    repo.list_customers.return_value = (customers, 3)

    from app.schemas.customer import CustomerListParams
    params = CustomerListParams()

    page = svc.list_customers(params)

    assert page.total == 3
    assert page.page == 1
    assert len(page.items) == 3


def test_list_customers_empty():
    svc, _, repo, _ = _make_service()
    repo.list_customers.return_value = ([], 0)

    from app.schemas.customer import CustomerListParams
    params = CustomerListParams()

    page = svc.list_customers(params)
    assert page.total == 0
    assert page.items == []
    assert page.pages == 0


# ---------------------------------------------------------------------------
# update_customer
# ---------------------------------------------------------------------------


def test_update_customer_happy_path():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer()
    repo.get_by_id_or_raise.return_value = customer

    result = svc.update_customer(CUSTOMER_ID, company_name="New Name")

    repo.update.assert_called_once()
    session.commit.assert_called_once()
    assert result is customer


def test_update_customer_raises_not_found_for_deleted():
    svc, _, repo, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_customer(is_deleted=True)

    with pytest.raises(NotFoundError):
        svc.update_customer(CUSTOMER_ID, company_name="New")


def test_update_customer_duplicate_cr_raises_conflict():
    svc, _, repo, _ = _make_service()
    existing = _make_customer()
    existing.commercial_registration = "OLD-CR"
    repo.get_by_id_or_raise.return_value = existing

    conflicting = _make_customer()
    conflicting.id = uuid.uuid4()  # different customer
    repo.get_by_commercial_registration.return_value = conflicting

    with pytest.raises(ConflictError, match="Commercial registration"):
        svc.update_customer(CUSTOMER_ID, commercial_registration="DUPE-CR")


def test_update_customer_same_cr_no_conflict():
    """Updating to the same CR as what's already set should not raise."""
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer()
    customer.commercial_registration = "SAME-CR"
    repo.get_by_id_or_raise.return_value = customer
    # `get_by_commercial_registration` returns the SAME customer (not a different one).
    repo.get_by_commercial_registration.return_value = customer

    # Should not raise.
    svc.update_customer(CUSTOMER_ID, commercial_registration="SAME-CR")
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# activate_customer
# ---------------------------------------------------------------------------


def test_activate_customer_from_suspended():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer(status=CustomerStatus.SUSPENDED)
    repo.get_by_id_or_raise.return_value = customer

    result = svc.activate_customer(CUSTOMER_ID)

    assert customer.status == CustomerStatus.ACTIVE
    session.commit.assert_called_once()
    # At minimum CustomerActivated + CustomerStatusChanged
    assert event_repo.append.call_count >= 2


def test_activate_customer_already_active_is_noop():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer(status=CustomerStatus.ACTIVE)
    repo.get_by_id_or_raise.return_value = customer

    result = svc.activate_customer(CUSTOMER_ID)

    assert result is customer
    session.commit.assert_not_called()
    event_repo.append.assert_not_called()


def test_activate_customer_deleted_raises_not_found():
    svc, _, repo, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_customer(is_deleted=True)

    with pytest.raises(NotFoundError):
        svc.activate_customer(CUSTOMER_ID)


# ---------------------------------------------------------------------------
# suspend_customer
# ---------------------------------------------------------------------------


def test_suspend_customer_from_active():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer(status=CustomerStatus.ACTIVE)
    repo.get_by_id_or_raise.return_value = customer

    svc.suspend_customer(CUSTOMER_ID, reason="Non-payment")

    assert customer.status == CustomerStatus.SUSPENDED
    session.commit.assert_called_once()
    # CustomerSuspended + CustomerStatusChanged
    assert event_repo.append.call_count >= 2


def test_suspend_customer_invalid_transition_from_inactive():
    svc, _, repo, _ = _make_service()
    customer = _make_customer(status=CustomerStatus.INACTIVE)
    repo.get_by_id_or_raise.return_value = customer

    with pytest.raises(StatusTransitionError):
        svc.suspend_customer(CUSTOMER_ID)


# ---------------------------------------------------------------------------
# delete_customer
# ---------------------------------------------------------------------------


def test_delete_customer_soft_deletes():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer()
    repo.get_by_id_or_raise.return_value = customer

    svc.delete_customer(CUSTOMER_ID)

    repo.soft_delete.assert_called_once_with(customer, deleted_by=USER_ID)
    session.commit.assert_called_once()
    event_repo.append.assert_called_once()


def test_delete_customer_already_deleted_raises_not_found():
    svc, _, repo, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_customer(is_deleted=True)

    with pytest.raises(NotFoundError, match="already deleted"):
        svc.delete_customer(CUSTOMER_ID)


# ---------------------------------------------------------------------------
# restore_customer
# ---------------------------------------------------------------------------


def test_restore_customer_happy_path():
    svc, session, repo, event_repo = _make_service()
    customer = _make_customer(is_deleted=True)
    repo.get_by_id.return_value = customer

    result = svc.restore_customer(CUSTOMER_ID)

    repo.restore.assert_called_once_with(customer)
    session.commit.assert_called_once()
    event_repo.append.assert_called_once()
    assert result is customer


def test_restore_customer_not_found_raises():
    svc, _, repo, _ = _make_service()
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        svc.restore_customer(CUSTOMER_ID)


def test_restore_customer_not_deleted_raises_validation_error():
    svc, _, repo, _ = _make_service()
    repo.get_by_id.return_value = _make_customer(is_deleted=False)

    with pytest.raises(ValidationError, match="not deleted"):
        svc.restore_customer(CUSTOMER_ID)


# ---------------------------------------------------------------------------
# no tenant context
# ---------------------------------------------------------------------------


def test_create_customer_no_tenant_raises():
    svc, _, repo, _ = _make_service()
    repo.get_by_code.return_value = None

    with patch(
        "app.services.customer_service.get_current_tenant",
        return_value=None,
    ):
        with pytest.raises(ValidationError, match="No tenant"):
            svc.create_customer(
                code="X",
                company_name="Corp",
                customer_type=CustomerType.CORPORATE,
            )
