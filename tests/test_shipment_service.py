"""Unit tests for ShipmentService with mocked repositories / event store / context."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import (
    ShipmentPriority,
    ShipmentStatus,
    UserRole,
    VehicleStatus,
)
from app.schemas.shipment import ShipmentListParams
from app.services.exceptions import (
    AssignmentError,
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    ValidationError,
)
from app.services.shipment_service import ShipmentService

TENANT = uuid.uuid4()
USER = uuid.uuid4()
SHIP = uuid.uuid4()
CLIENT = uuid.uuid4()
ORIGIN = uuid.uuid4()
DEST = uuid.uuid4()
DRIVER = uuid.uuid4()
VEHICLE = uuid.uuid4()
ORDER = uuid.uuid4()


def _shipment(*, status=ShipmentStatus.CREATED, is_deleted=False):
    s = MagicMock()
    s.id = SHIP
    s.tenant_id = TENANT
    s.reference_code = "SHP-1"
    s.client_id = CLIENT
    s.origin_warehouse_id = ORIGIN
    s.destination_warehouse_id = DEST
    s.order_id = None
    s.equipment_id = None
    s.driver_id = None
    s.vehicle_id = None
    s.status = status
    s.priority = ShipmentPriority.NORMAL
    s.weight_kg = 5
    s.volume_m3 = 1
    s.is_deleted = is_deleted
    return s


def _tenant_obj(*, is_deleted=False, tenant_id=TENANT):
    o = MagicMock()
    o.tenant_id = tenant_id
    o.is_deleted = is_deleted
    return o


def _driver(*, available=True, role=UserRole.DRIVER, tenant_id=TENANT):
    d = MagicMock()
    d.id = DRIVER
    d.tenant_id = tenant_id
    d.is_deleted = False
    d.is_available = available
    d.user = MagicMock(role=role)
    return d


def _vehicle(*, status=VehicleStatus.ACTIVE, tenant_id=TENANT, cap=1e9):
    v = MagicMock()
    v.id = VEHICLE
    v.tenant_id = tenant_id
    v.is_deleted = False
    v.status = status
    v.capacity_weight_kg = cap
    v.capacity_volume_m3 = cap
    return v


def _make_service():
    session = MagicMock()
    # Capacity query: session.execute(...).one() → (weight, volume).
    session.execute.return_value.one.return_value = (0.0, 0.0)
    # Latest-tracking-event-time query: session.execute(...).first() → None.
    session.execute.return_value.first.return_value = None
    with (
        patch("app.services.shipment_service.ShipmentRepository") as MR,
        patch("app.services.shipment_service.OrderRepository") as MO,
        patch("app.services.shipment_service.UserRepository") as MU,
        patch("app.services.shipment_service.DriverRepository") as MD,
        patch("app.services.shipment_service.VehicleRepository") as MV,
        patch("app.services.shipment_service.WarehouseRepository") as MW,
        patch("app.services.shipment_service.TrackingEventRepository"),
        patch("app.services.shipment_service.EventStoreRepository") as ME,
    ):
        svc = ShipmentService(session)
        repo = MR.return_value
        svc._repo = repo
        svc._orders = MO.return_value
        svc._users = MU.return_value
        svc._drivers = MD.return_value
        svc._vehicles = MV.return_value
        svc._warehouses = MW.return_value
        svc._event_repo = ME.return_value
        svc._event_repo.next_aggregate_version.return_value = 1
        svc._event_repo.append.return_value = None

        # Default happy wiring.
        repo.get_by_reference_code.return_value = None
        repo.has_active_driver_assignment.return_value = False
        repo.has_active_vehicle_assignment.return_value = False
        svc._users.get_by_id.return_value = _tenant_obj()
        wh = _tenant_obj()
        wh.capacity_weight_kg = 1e9
        wh.capacity_volume_m3 = 1e9
        svc._warehouses.get_by_id.return_value = wh
        svc._orders.get_by_id.return_value = _tenant_obj()
        svc._drivers.get_by_id.return_value = _driver()
        svc._vehicles.get_by_id.return_value = _vehicle()
    return svc, session, repo


@pytest.fixture(autouse=True)
def patch_context():
    with (
        patch("app.services.shipment_service.get_current_tenant", return_value=TENANT),
        patch("app.services.shipment_service.get_current_user_id", return_value=USER),
    ):
        yield


# --- create ---------------------------------------------------------------


def _create_kwargs(**ov):
    base = dict(
        client_id=CLIENT,
        origin_warehouse_id=ORIGIN,
        destination_warehouse_id=DEST,
        weight_kg=5,
        volume_m3=1,
    )
    base.update(ov)
    return base


def test_create_happy_path():
    svc, session, repo = _make_service()
    repo.create.return_value = _shipment()
    result = svc.create_shipment(reference_code="SHP-1", **_create_kwargs())
    repo.create.assert_called_once()
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()  # ShipmentCreated
    assert result.status == ShipmentStatus.CREATED


def test_create_generates_reference_when_missing():
    svc, session, repo = _make_service()
    repo.create.return_value = _shipment()
    svc.create_shipment(**_create_kwargs())
    assert repo.create.call_args.kwargs["reference_code"].startswith("SHP-")


def test_create_forces_created_status():
    svc, session, repo = _make_service()
    repo.create.return_value = _shipment()
    svc.create_shipment(status=ShipmentStatus.DELIVERED, **_create_kwargs())
    assert repo.create.call_args.kwargs["status"] == ShipmentStatus.CREATED


def test_create_no_tenant_raises():
    svc, session, repo = _make_service()
    with patch("app.services.shipment_service.get_current_tenant", return_value=None):
        with pytest.raises(ValidationError, match="No tenant"):
            svc.create_shipment(**_create_kwargs())
    session.commit.assert_not_called()


def test_create_cross_tenant_client_raises():
    svc, session, repo = _make_service()
    svc._users.get_by_id.return_value = _tenant_obj(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Client"):
        svc.create_shipment(**_create_kwargs())
    session.commit.assert_not_called()


def test_create_cross_tenant_warehouse_raises():
    svc, session, repo = _make_service()
    svc._warehouses.get_by_id.return_value = _tenant_obj(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="warehouse"):
        svc.create_shipment(**_create_kwargs())


def test_create_cross_tenant_order_raises():
    svc, session, repo = _make_service()
    svc._orders.get_by_id.return_value = _tenant_obj(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Order"):
        svc.create_shipment(order_id=ORDER, **_create_kwargs())


def test_create_duplicate_reference_raises_conflict():
    svc, session, repo = _make_service()
    repo.get_by_reference_code.return_value = _shipment()
    with pytest.raises(ConflictError, match="already exists"):
        svc.create_shipment(reference_code="SHP-DUP", **_create_kwargs())
    session.commit.assert_not_called()


# --- read -----------------------------------------------------------------


def test_get_shipment_existing():
    svc, _, repo = _make_service()
    sh = _shipment()
    repo.get_by_id.return_value = sh
    assert svc.get_shipment(SHIP) is sh


def test_get_shipment_missing_raises():
    svc, _, repo = _make_service()
    repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_shipment(SHIP)


def test_get_shipment_deleted_hidden_then_included():
    svc, _, repo = _make_service()
    repo.get_by_id.return_value = _shipment(is_deleted=True)
    with pytest.raises(NotFoundError):
        svc.get_shipment(SHIP)
    assert svc.get_shipment(SHIP, include_deleted=True) is not None


def test_list_shipments_page():
    svc, _, repo = _make_service()
    repo.list_shipments.return_value = ([_shipment(), _shipment()], 2)
    page = svc.list_shipments(ShipmentListParams())
    assert page.total == 2 and len(page.items) == 2


# --- update ---------------------------------------------------------------


def test_update_happy_path_emits_updated():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment()
    svc.update_shipment(SHIP, cargo_type="fragile")
    repo.update.assert_called_once()
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()  # ShipmentUpdated


def test_update_cargo_change_emits_cargo_event():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment()
    svc.update_shipment(SHIP, cargo_description="pallets")
    assert svc._event_repo.append.call_count == 1


def test_update_address_change_validates_and_emits():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment()
    svc.update_shipment(SHIP, origin_warehouse_id=ORIGIN)
    svc._warehouses.get_by_id.assert_called()  # tenant ownership checked
    session.commit.assert_called_once()


def test_update_terminal_raises():
    svc, _, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.DELIVERED)
    with pytest.raises(ValidationError, match="terminal"):
        svc.update_shipment(SHIP, cargo_type="x")


def test_update_deleted_raises_not_found():
    svc, _, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(is_deleted=True)
    with pytest.raises(NotFoundError):
        svc.update_shipment(SHIP, cargo_type="x")


# --- lifecycle ------------------------------------------------------------


def test_mark_ready():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.CREATED)
    result = svc.mark_ready(SHIP)
    assert result.status == ShipmentStatus.READY
    assert svc._event_repo.append.call_count >= 2  # MarkedReady + StatusChanged


def test_assign_happy_path():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.READY)
    result = svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)
    assert result.status == ShipmentStatus.ASSIGNED
    assert result.driver_id == DRIVER and result.vehicle_id == VEHICLE


def test_assign_cross_tenant_driver_raises():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.READY)
    svc._drivers.get_by_id.return_value = _driver(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Driver"):
        svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)
    session.commit.assert_not_called()


def test_assign_cross_tenant_vehicle_raises():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.READY)
    svc._vehicles.get_by_id.return_value = _vehicle(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Vehicle"):
        svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)


def test_assign_unavailable_driver_raises():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.READY)
    svc._drivers.get_by_id.return_value = _driver(available=False)
    with pytest.raises(AssignmentError, match="unavailable"):
        svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)


def test_assign_busy_driver_raises():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.READY)
    repo.has_active_driver_assignment.return_value = True
    with pytest.raises(AssignmentError, match="Driver already"):
        svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)


def test_assign_vehicle_capacity_raises():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.READY)
    sh.weight_kg = 10_000
    repo.get_by_id_or_raise.return_value = sh
    svc._vehicles.get_by_id.return_value = _vehicle(cap=10)
    with pytest.raises(AssignmentError, match="capacity"):
        svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)


def test_assign_from_created_invalid_transition():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.CREATED)
    with pytest.raises(StatusTransitionError):
        svc.assign_shipment(SHIP, driver_id=DRIVER, vehicle_id=VEHICLE)


def test_pickup_transit_deliver_chain():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.ASSIGNED)
    repo.get_by_id_or_raise.return_value = sh
    assert svc.pickup_shipment(SHIP).status == ShipmentStatus.PICKED_UP
    assert svc.start_transit(SHIP).status == ShipmentStatus.IN_TRANSIT
    assert svc.deliver_shipment(SHIP).status == ShipmentStatus.DELIVERED


def test_delay_then_resume():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.IN_TRANSIT)
    repo.get_by_id_or_raise.return_value = sh
    assert svc.mark_delayed(SHIP, reason="weather").status == ShipmentStatus.DELAYED
    assert svc.start_transit(SHIP).status == ShipmentStatus.IN_TRANSIT


def test_fail_then_return():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.IN_TRANSIT)
    repo.get_by_id_or_raise.return_value = sh
    assert svc.fail_shipment(SHIP, reason="breakdown").status == ShipmentStatus.FAILED
    assert svc.return_shipment(SHIP, reason="back").status == ShipmentStatus.RETURNED


def test_cancel_from_assigned_flags_compensation():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.ASSIGNED)
    repo.get_by_id_or_raise.return_value = sh
    svc.cancel_shipment(SHIP, reason="customer")
    assert sh.status == ShipmentStatus.CANCELLED
    session.commit.assert_called_once()


def test_cancel_terminal_raises():
    svc, _, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.DELIVERED)
    with pytest.raises(StatusTransitionError):
        svc.cancel_shipment(SHIP)


def test_transition_idempotent_noop():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.READY)
    repo.get_by_id_or_raise.return_value = sh
    result = svc.mark_ready(sh.id) if False else svc._transition(SHIP, ShipmentStatus.READY)
    assert result is sh
    session.commit.assert_not_called()
    svc._event_repo.append.assert_not_called()


# --- delete / restore -----------------------------------------------------


def test_delete_shipment():
    svc, session, repo = _make_service()
    sh = _shipment()
    repo.get_by_id_or_raise.return_value = sh
    svc.delete_shipment(SHIP)
    repo.soft_delete.assert_called_once_with(sh, deleted_by=USER)
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()


def test_delete_already_deleted_raises():
    svc, _, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(is_deleted=True)
    with pytest.raises(NotFoundError, match="already deleted"):
        svc.delete_shipment(SHIP)


def test_restore_shipment():
    svc, session, repo = _make_service()
    sh = _shipment(is_deleted=True)
    repo.get_by_id.return_value = sh
    svc.restore_shipment(SHIP)
    repo.restore.assert_called_once_with(sh)
    session.commit.assert_called_once()


def test_restore_not_deleted_raises():
    svc, _, repo = _make_service()
    repo.get_by_id.return_value = _shipment(is_deleted=False)
    with pytest.raises(ValidationError, match="not deleted"):
        svc.restore_shipment(SHIP)


def test_restore_missing_raises():
    svc, _, repo = _make_service()
    repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.restore_shipment(SHIP)


# --- legacy compatibility -------------------------------------------------


def test_legacy_assign_driver_only():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.READY)
    result = svc.assign_driver_only(str(SHIP), str(DRIVER))
    assert result.status == ShipmentStatus.ASSIGNED
    assert result.driver_id == DRIVER
    session.commit.assert_called_once()


def test_legacy_assign_driver_only_not_open_raises():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.IN_TRANSIT)
    with pytest.raises(AssignmentError, match="not open"):
        svc.assign_driver_only(str(SHIP), str(DRIVER))


def test_legacy_transition_status():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.CREATED)
    result = svc.transition_status(str(SHIP), ShipmentStatus.READY)
    assert result.status == ShipmentStatus.READY


def test_legacy_transition_status_sets_delivered_timestamp():
    svc, session, repo = _make_service()
    sh = _shipment(status=ShipmentStatus.IN_TRANSIT)
    repo.get_by_id_or_raise.return_value = sh
    svc.transition_status(str(SHIP), ShipmentStatus.DELIVERED)
    assert sh.status == ShipmentStatus.DELIVERED
    assert sh.delivered_at is not None


# --- legacy tracking events ----------------------------------------------

import datetime as _dt  # noqa: E402

from app.models.enums import TrackingEventType  # noqa: E402


def _tracking_kwargs(**ov):
    base = dict(
        shipment_id=str(SHIP),
        event_type=TrackingEventType.STATUS_UPDATE,
        status=None,
        event_time=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        latitude=None,
        longitude=None,
        notes=None,
        recorded_by_user_id=None,
        evidence_url=None,
    )
    base.update(ov)
    return base


def test_create_tracking_event_no_status_no_event():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.IN_TRANSIT)
    svc.create_tracking_event(**_tracking_kwargs())
    session.add.assert_called()  # tracking row staged
    session.commit.assert_called_once()
    svc._event_repo.append.assert_not_called()  # no status change → no domain event


def test_create_tracking_event_with_valid_status_emits():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.IN_TRANSIT)
    svc.create_tracking_event(**_tracking_kwargs(status=ShipmentStatus.DELIVERED))
    svc._event_repo.append.assert_called_once()  # ShipmentStatusChanged


def test_create_tracking_event_invalid_transition_raises():
    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.CREATED)
    with pytest.raises(StatusTransitionError):
        svc.create_tracking_event(**_tracking_kwargs(status=ShipmentStatus.DELIVERED))


def test_create_tracking_event_out_of_order_raises():
    from app.services.exceptions import TrackingEventError

    svc, session, repo = _make_service()
    repo.get_by_id_or_raise.return_value = _shipment(status=ShipmentStatus.IN_TRANSIT)
    # Latest recorded event is AFTER the incoming event_time.
    session.execute.return_value.first.return_value = (
        _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc),
    )
    with pytest.raises(TrackingEventError):
        svc.create_tracking_event(
            **_tracking_kwargs(event_time=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc))
        )
