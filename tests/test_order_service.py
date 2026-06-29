"""Unit tests for OrderService with mocked repositories, event store, context vars."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import (
    OrderPriority,
    OrderSource,
    OrderStatus,
    OrderType,
)
from app.schemas.order import OrderListParams
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    ValidationError,
)
from app.services.order_service import OrderService

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
ORDER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_order(*, status: OrderStatus = OrderStatus.DRAFT, is_deleted: bool = False) -> MagicMock:
    o = MagicMock()
    o.id = ORDER_ID
    o.tenant_id = TENANT_ID
    o.customer_id = CUSTOMER_ID
    o.order_number = "ORD-0001"
    o.order_type = OrderType.STANDARD
    o.order_source = OrderSource.WEB
    o.priority = OrderPriority.NORMAL
    o.status = status
    o.assigned_dispatcher_id = None
    o.picked_up_at = None
    o.delivered_at = None
    o.is_deleted = is_deleted
    return o


def _make_customer(*, is_deleted: bool = False) -> MagicMock:
    c = MagicMock()
    c.id = CUSTOMER_ID
    c.is_deleted = is_deleted
    return c


def _make_service():
    """Return (svc, session, order_repo, customer_repo, event_repo).

    The user repo is wired internally with a default dispatcher in the current
    tenant so assign_order's validation passes by default.
    """
    session = MagicMock()
    with (
        patch("app.services.order_service.OrderRepository") as MockRepo,
        patch("app.services.order_service.CustomerRepository") as MockCustRepo,
        patch("app.services.order_service.UserRepository") as MockUserRepo,
        patch("app.services.order_service.EventStoreRepository") as MockEventRepo,
    ):
        order_repo = MockRepo.return_value
        customer_repo = MockCustRepo.return_value
        user_repo = MockUserRepo.return_value
        event_repo = MockEventRepo.return_value
        event_repo.next_aggregate_version.return_value = 1
        event_repo.append.return_value = None

        dispatcher = MagicMock()
        dispatcher.id = USER_ID
        dispatcher.tenant_id = TENANT_ID
        dispatcher.is_deleted = False
        user_repo.get_by_id.return_value = dispatcher

        svc = OrderService(session)
        svc._repo = order_repo
        svc._customer_repo = customer_repo
        svc._user_repo = user_repo
        svc._event_repo = event_repo
    return svc, session, order_repo, customer_repo, event_repo


@pytest.fixture(autouse=True)
def patch_context():
    with (
        patch("app.services.order_service.get_current_tenant", return_value=TENANT_ID),
        patch("app.services.order_service.get_current_user_id", return_value=USER_ID),
    ):
        yield


# --- create ---------------------------------------------------------------


def test_create_order_happy_path():
    svc, session, repo, cust_repo, event_repo = _make_service()
    cust_repo.get_by_id.return_value = _make_customer()
    repo.get_by_order_number.return_value = None
    order = _make_order()
    repo.create.return_value = order

    result = svc.create_order(customer_id=CUSTOMER_ID, customer_type=None, order_number="ORD-0001")

    repo.create.assert_called_once()
    session.commit.assert_called_once()
    event_repo.append.assert_called_once()  # OrderCreated
    assert result is order


def test_create_order_generates_number_when_missing():
    svc, session, repo, cust_repo, event_repo = _make_service()
    cust_repo.get_by_id.return_value = _make_customer()
    repo.get_by_order_number.return_value = None
    repo.create.return_value = _make_order()

    svc.create_order(customer_id=CUSTOMER_ID)

    created_number = repo.create.call_args.kwargs["order_number"]
    assert created_number.startswith("ORD-")


def test_create_order_missing_customer_raises_validation():
    svc, session, repo, cust_repo, _ = _make_service()
    cust_repo.get_by_id.return_value = None

    with pytest.raises(ValidationError, match="does not exist"):
        svc.create_order(customer_id=CUSTOMER_ID)
    session.commit.assert_not_called()


def test_create_order_deleted_customer_raises_validation():
    svc, session, repo, cust_repo, _ = _make_service()
    cust_repo.get_by_id.return_value = _make_customer(is_deleted=True)

    with pytest.raises(ValidationError):
        svc.create_order(customer_id=CUSTOMER_ID)


def test_create_order_duplicate_number_raises_conflict():
    svc, session, repo, cust_repo, _ = _make_service()
    cust_repo.get_by_id.return_value = _make_customer()
    repo.get_by_order_number.return_value = _make_order()

    with pytest.raises(ConflictError, match="already exists"):
        svc.create_order(customer_id=CUSTOMER_ID, order_number="ORD-DUP")
    session.commit.assert_not_called()


def test_create_order_forces_draft_status():
    svc, session, repo, cust_repo, _ = _make_service()
    cust_repo.get_by_id.return_value = _make_customer()
    repo.get_by_order_number.return_value = None
    repo.create.return_value = _make_order()

    svc.create_order(customer_id=CUSTOMER_ID, status=OrderStatus.DELIVERED)
    assert repo.create.call_args.kwargs["status"] == OrderStatus.DRAFT


def test_create_order_no_tenant_raises():
    svc, _, repo, cust_repo, _ = _make_service()
    with patch("app.services.order_service.get_current_tenant", return_value=None):
        with pytest.raises(ValidationError, match="No tenant"):
            svc.create_order(customer_id=CUSTOMER_ID)


# --- read -----------------------------------------------------------------


def test_get_order_returns_existing():
    svc, _, repo, _, _ = _make_service()
    order = _make_order()
    repo.get_by_id.return_value = order
    assert svc.get_order(ORDER_ID) is order


def test_get_order_missing_raises():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_order(ORDER_ID)


def test_get_order_deleted_hidden_by_default():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id.return_value = _make_order(is_deleted=True)
    with pytest.raises(NotFoundError):
        svc.get_order(ORDER_ID)


def test_get_order_deleted_included():
    svc, _, repo, _, _ = _make_service()
    order = _make_order(is_deleted=True)
    repo.get_by_id.return_value = order
    assert svc.get_order(ORDER_ID, include_deleted=True) is order


def test_list_orders_returns_page():
    svc, _, repo, _, _ = _make_service()
    repo.list_orders.return_value = ([_make_order(), _make_order()], 2)
    page = svc.list_orders(OrderListParams())
    assert page.total == 2
    assert len(page.items) == 2


# --- update ---------------------------------------------------------------


def test_update_order_happy_path():
    svc, session, repo, _, event_repo = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order()
    svc.update_order(ORDER_ID, special_instructions="leave at gate")
    repo.update.assert_called_once()
    session.commit.assert_called_once()


def test_update_order_priority_change_emits_event():
    svc, session, repo, _, event_repo = _make_service()
    order = _make_order()
    order.priority = OrderPriority.NORMAL
    repo.get_by_id_or_raise.return_value = order
    svc.update_order(ORDER_ID, priority=OrderPriority.URGENT)
    # OrderPriorityChanged should be among emitted events.
    assert event_repo.append.call_count >= 1


def test_update_order_terminal_raises_validation():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.DELIVERED)
    with pytest.raises(ValidationError, match="terminal"):
        svc.update_order(ORDER_ID, special_instructions="x")


def test_update_order_deleted_raises_not_found():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(is_deleted=True)
    with pytest.raises(NotFoundError):
        svc.update_order(ORDER_ID, special_instructions="x")


# --- transitions ----------------------------------------------------------


def test_submit_order():
    svc, session, repo, _, event_repo = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.DRAFT)
    result = svc.submit_order(ORDER_ID)
    assert result.status == OrderStatus.SUBMITTED
    session.commit.assert_called_once()
    # OrderSubmitted + OrderStatusChanged
    assert event_repo.append.call_count >= 2


def test_approve_order():
    svc, session, repo, _, event_repo = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.SUBMITTED)
    svc.approve_order(ORDER_ID, reason="ok")
    session.commit.assert_called_once()


def test_full_happy_path_chain():
    svc, session, repo, _, event_repo = _make_service()
    order = _make_order(status=OrderStatus.SCHEDULED)
    repo.get_by_id_or_raise.return_value = order

    svc.assign_order(ORDER_ID, assigned_dispatcher_id=USER_ID)
    assert order.status == OrderStatus.ASSIGNED

    svc.start_transit_order(ORDER_ID)
    assert order.status == OrderStatus.IN_TRANSIT

    svc.deliver_order(ORDER_ID)
    assert order.status == OrderStatus.DELIVERED


def test_invalid_transition_raises():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.DRAFT)
    # draft cannot go straight to delivered
    with pytest.raises(StatusTransitionError):
        svc.deliver_order(ORDER_ID)


def test_transition_idempotent_noop():
    svc, session, repo, _, event_repo = _make_service()
    order = _make_order(status=OrderStatus.SUBMITTED)
    repo.get_by_id_or_raise.return_value = order
    # submitting an already-submitted order is a no-op
    result = svc.submit_order(ORDER_ID)
    assert result is order
    session.commit.assert_not_called()
    event_repo.append.assert_not_called()


def test_cancel_from_in_transit_flags_compensation():
    svc, session, repo, _, event_repo = _make_service()
    order = _make_order(status=OrderStatus.IN_TRANSIT)
    repo.get_by_id_or_raise.return_value = order
    svc.cancel_order(ORDER_ID, reason="incident")
    assert order.status == OrderStatus.CANCELLED
    session.commit.assert_called_once()


def test_cancel_terminal_order_raises():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.DELIVERED)
    with pytest.raises(StatusTransitionError):
        svc.cancel_order(ORDER_ID)


def test_fail_order():
    svc, session, repo, _, event_repo = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.ASSIGNED)
    svc.fail_order(ORDER_ID, reason="vehicle breakdown")
    session.commit.assert_called_once()


def test_assign_sets_dispatcher():
    svc, session, repo, _, _ = _make_service()
    order = _make_order(status=OrderStatus.SCHEDULED)
    repo.get_by_id_or_raise.return_value = order
    svc.assign_order(ORDER_ID, assigned_dispatcher_id=USER_ID)
    assert order.assigned_dispatcher_id == USER_ID


def test_assign_unknown_dispatcher_raises_validation():
    svc, session, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.SCHEDULED)
    svc._user_repo.get_by_id.return_value = None  # dispatcher not found / cross-tenant
    with pytest.raises(ValidationError, match="Dispatcher"):
        svc.assign_order(ORDER_ID, assigned_dispatcher_id=uuid.uuid4())
    session.commit.assert_not_called()


def test_assign_cross_tenant_dispatcher_raises_validation():
    svc, session, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(status=OrderStatus.SCHEDULED)
    foreign = MagicMock()
    foreign.tenant_id = uuid.uuid4()  # different tenant
    foreign.is_deleted = False
    svc._user_repo.get_by_id.return_value = foreign
    with pytest.raises(ValidationError, match="Dispatcher"):
        svc.assign_order(ORDER_ID, assigned_dispatcher_id=uuid.uuid4())
    session.commit.assert_not_called()


# --- delete / restore -----------------------------------------------------


def test_delete_order():
    svc, session, repo, _, event_repo = _make_service()
    order = _make_order()
    repo.get_by_id_or_raise.return_value = order
    svc.delete_order(ORDER_ID)
    repo.soft_delete.assert_called_once_with(order, deleted_by=USER_ID)
    session.commit.assert_called_once()
    event_repo.append.assert_called_once()


def test_delete_already_deleted_raises():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id_or_raise.return_value = _make_order(is_deleted=True)
    with pytest.raises(NotFoundError, match="already deleted"):
        svc.delete_order(ORDER_ID)


def test_restore_order():
    svc, session, repo, _, event_repo = _make_service()
    order = _make_order(is_deleted=True)
    repo.get_by_id.return_value = order
    result = svc.restore_order(ORDER_ID)
    repo.restore.assert_called_once_with(order)
    session.commit.assert_called_once()
    assert result is order


def test_restore_not_deleted_raises_validation():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id.return_value = _make_order(is_deleted=False)
    with pytest.raises(ValidationError, match="not deleted"):
        svc.restore_order(ORDER_ID)


def test_restore_missing_raises_not_found():
    svc, _, repo, _, _ = _make_service()
    repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.restore_order(ORDER_ID)
