"""Unit tests for EquipmentService with mocked repos / event store / context."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import (
    EquipmentAvailability,
    EquipmentStatus,
    EquipmentOwnershipType,
)
from app.schemas.equipment import EquipmentListParams
from app.services.equipment_service import EquipmentService
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    ValidationError,
)

TENANT = uuid.uuid4()
USER = uuid.uuid4()
EQ = uuid.uuid4()
CAT = uuid.uuid4()
MODEL = uuid.uuid4()
WH = uuid.uuid4()
SHIP = uuid.uuid4()


def _equipment(*, status=EquipmentStatus.ACTIVE, availability=EquipmentAvailability.AVAILABLE, is_deleted=False):
    e = MagicMock()
    e.id = EQ
    e.tenant_id = TENANT
    e.equipment_code = "EQP-1"
    e.asset_tag = "TAG-1"
    e.category_id = CAT
    e.model_id = None
    e.status = status
    e.availability_status = availability
    e.ownership_type = EquipmentOwnershipType.OWNED
    e.is_deleted = is_deleted
    return e


def _owned(*, tenant_id=TENANT, is_deleted=False):
    o = MagicMock()
    o.tenant_id = tenant_id
    o.is_deleted = is_deleted
    return o


def _make():
    session = MagicMock()
    with (
        patch("app.services.equipment_service.EquipmentRepository") as MR,
        patch("app.services.equipment_service.EquipmentCategoryRepository") as MC,
        patch("app.services.equipment_service.EquipmentModelRepository") as MM,
        patch("app.services.equipment_service.WarehouseRepository") as MW,
        patch("app.services.equipment_service.ShipmentRepository") as MS,
        patch("app.services.equipment_service.EventStoreRepository") as ME,
    ):
        svc = EquipmentService(session)
        repo = MR.return_value
        svc._repo = repo
        svc._categories = MC.return_value
        svc._models = MM.return_value
        svc._warehouses = MW.return_value
        svc._shipments = MS.return_value
        svc._event_repo = ME.return_value
        svc._event_repo.next_aggregate_version.return_value = 1

        repo.get_by_code.return_value = None
        repo.get_by_asset_tag.return_value = None
        repo.get_by_serial_number.return_value = None
        svc._categories.get_by_id.return_value = _owned()
        svc._models.get_by_id.return_value = _owned()
        svc._warehouses.get_by_id.return_value = _owned()
        svc._shipments.get_by_id.return_value = _owned()
    return svc, session, repo


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.equipment_service.get_current_tenant", return_value=TENANT),
        patch("app.services.equipment_service.get_current_user_id", return_value=USER),
    ):
        yield


def _ck(**ov):
    base = dict(category_id=CAT, asset_tag="TAG-1", name="Excavator")
    base.update(ov)
    return base


# --- create ---------------------------------------------------------------


def test_create_happy():
    svc, session, repo = _make()
    repo.create.return_value = _equipment()
    svc.create_equipment(equipment_code="EQP-1", **_ck())
    repo.create.assert_called_once()
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()


def test_create_generates_code():
    svc, session, repo = _make()
    repo.create.return_value = _equipment()
    svc.create_equipment(**_ck())
    assert repo.create.call_args.kwargs["equipment_code"].startswith("EQP-")


def test_create_forces_active_available():
    svc, session, repo = _make()
    repo.create.return_value = _equipment()
    svc.create_equipment(status=EquipmentStatus.DECOMMISSIONED, **_ck())
    assert repo.create.call_args.kwargs["status"] == EquipmentStatus.ACTIVE
    assert repo.create.call_args.kwargs["availability_status"] == EquipmentAvailability.AVAILABLE


def test_create_no_tenant():
    svc, session, repo = _make()
    with patch("app.services.equipment_service.get_current_tenant", return_value=None):
        with pytest.raises(ValidationError, match="No tenant"):
            svc.create_equipment(**_ck())


def test_create_cross_tenant_category():
    svc, session, repo = _make()
    svc._categories.get_by_id.return_value = _owned(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Category"):
        svc.create_equipment(**_ck())
    session.commit.assert_not_called()


def test_create_cross_tenant_model():
    svc, session, repo = _make()
    svc._models.get_by_id.return_value = _owned(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Model"):
        svc.create_equipment(model_id=MODEL, **_ck())


def test_create_cross_tenant_warehouse():
    svc, session, repo = _make()
    svc._warehouses.get_by_id.return_value = _owned(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Warehouse"):
        svc.create_equipment(current_warehouse_id=WH, **_ck())


def test_create_duplicate_code():
    svc, session, repo = _make()
    repo.get_by_code.return_value = _equipment()
    with pytest.raises(ConflictError, match="code"):
        svc.create_equipment(equipment_code="EQP-DUP", **_ck())


def test_create_duplicate_asset_tag():
    svc, session, repo = _make()
    repo.get_by_asset_tag.return_value = _equipment()
    with pytest.raises(ConflictError, match="Asset tag"):
        svc.create_equipment(**_ck())


def test_create_duplicate_serial():
    svc, session, repo = _make()
    repo.get_by_serial_number.return_value = _equipment()
    with pytest.raises(ConflictError, match="Serial"):
        svc.create_equipment(serial_number="SER-1", **_ck())


# --- read -----------------------------------------------------------------


def test_get_missing():
    svc, _, repo = _make()
    repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.get_equipment(EQ)


def test_get_deleted_hidden_then_included():
    svc, _, repo = _make()
    repo.get_by_id.return_value = _equipment(is_deleted=True)
    with pytest.raises(NotFoundError):
        svc.get_equipment(EQ)
    assert svc.get_equipment(EQ, include_deleted=True) is not None


def test_list_page():
    svc, _, repo = _make()
    repo.list_equipment.return_value = ([_equipment(), _equipment()], 2)
    page = svc.list_equipment(EquipmentListParams())
    assert page.total == 2 and len(page.items) == 2


# --- update ---------------------------------------------------------------


def test_update_emits_general():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment()
    svc.update_equipment(EQ, name="New Name")
    repo.update.assert_called_once()
    svc._event_repo.append.assert_called_once()


def test_update_location_event():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment()
    svc.update_equipment(EQ, current_location="Yard B")
    assert svc._event_repo.append.call_count == 1


def test_update_spec_event_validates_warehouse():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment()
    svc.update_equipment(EQ, weight_kg=12000, current_warehouse_id=WH)
    svc._warehouses.get_by_id.assert_called()
    # spec + location events
    assert svc._event_repo.append.call_count == 2


def test_update_terminal_blocked():
    svc, _, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.DECOMMISSIONED)
    with pytest.raises(ValidationError, match="terminal"):
        svc.update_equipment(EQ, name="x")


# --- lifecycle ------------------------------------------------------------


def test_deactivate_then_activate():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    assert svc.deactivate_equipment(EQ).status == EquipmentStatus.INACTIVE
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.INACTIVE)
    assert svc.activate_equipment(EQ).status == EquipmentStatus.ACTIVE


def test_reserve_requires_available():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(
        availability=EquipmentAvailability.ASSIGNED
    )
    with pytest.raises(ConflictError, match="not available"):
        svc.reserve_equipment(EQ)


def test_reserve_and_release():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    res = svc.reserve_equipment(EQ, reference="ORD-9")
    assert res.status == EquipmentStatus.RESERVED
    assert res.availability_status == EquipmentAvailability.RESERVED
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.RESERVED)
    rel = svc.release_equipment(EQ)
    assert rel.status == EquipmentStatus.ACTIVE


def test_reserve_transit_deliver_chain():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.RESERVED)
    assert svc.mark_in_transit(EQ).status == EquipmentStatus.IN_TRANSIT
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.IN_TRANSIT)
    assert svc.mark_delivered(EQ).status == EquipmentStatus.ACTIVE


def test_maintenance_cycle():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    assert svc.start_maintenance(EQ, reason="hydraulics").status == EquipmentStatus.UNDER_MAINTENANCE
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.UNDER_MAINTENANCE)
    assert svc.complete_maintenance(EQ).status == EquipmentStatus.ACTIVE


def test_decommission_and_terminal():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    assert svc.decommission_equipment(EQ, reason="write-off").status == EquipmentStatus.DECOMMISSIONED


def test_invalid_transition():
    svc, _, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.UNDER_MAINTENANCE)
    with pytest.raises(StatusTransitionError):
        svc.reserve_equipment(EQ)  # under_maintenance → reserved illegal (also avail guard)


def test_assign_to_shipment():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    res = svc.assign_to_shipment(EQ, shipment_id=SHIP)
    assert res.availability_status == EquipmentAvailability.ASSIGNED
    # EquipmentAssignedToShipment + EquipmentAvailabilityChanged
    assert svc._event_repo.append.call_count == 2


def test_assign_decommissioned_blocked():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.DECOMMISSIONED)
    with pytest.raises(ConflictError, match="cannot be assigned"):
        svc.assign_to_shipment(EQ, shipment_id=SHIP)


def test_assign_cross_tenant_shipment():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    svc._shipments.get_by_id.return_value = _owned(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Shipment"):
        svc.assign_to_shipment(EQ, shipment_id=SHIP)


# --- delete / restore -----------------------------------------------------


def test_delete():
    svc, session, repo = _make()
    eq = _equipment()
    repo.get_by_id_or_raise.return_value = eq
    svc.delete_equipment(EQ)
    repo.soft_delete.assert_called_once_with(eq, deleted_by=USER)
    svc._event_repo.append.assert_called_once()


def test_delete_already_deleted():
    svc, _, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(is_deleted=True)
    with pytest.raises(NotFoundError, match="already deleted"):
        svc.delete_equipment(EQ)


def test_restore():
    svc, session, repo = _make()
    repo.get_by_id.return_value = _equipment(is_deleted=True)
    svc.restore_equipment(EQ)
    repo.restore.assert_called_once()


def test_restore_not_deleted():
    svc, _, repo = _make()
    repo.get_by_id.return_value = _equipment(is_deleted=False)
    with pytest.raises(ValidationError, match="not deleted"):
        svc.restore_equipment(EQ)


# --- category / model reference data --------------------------------------


def test_create_category():
    svc, session, repo = _make()
    svc._categories.get_by_code.return_value = None
    svc._categories.create.return_value = MagicMock(id=CAT)
    svc.create_category(code="EARTH", name="Earthmoving")
    svc._categories.create.assert_called_once()
    session.commit.assert_called_once()
    svc._event_repo.append.assert_called_once()  # EquipmentCategoryCreated


def test_create_category_duplicate():
    svc, session, repo = _make()
    svc._categories.get_by_code.return_value = MagicMock()
    with pytest.raises(ConflictError, match="Category code"):
        svc.create_category(code="EARTH", name="Earthmoving")
    session.commit.assert_not_called()


def test_create_model_validates_category_tenant():
    svc, session, repo = _make()
    svc._categories.get_by_id.return_value = _owned(tenant_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="Category"):
        svc.create_model(code="M1", name="CAT 320", category_id=CAT)


def test_create_model_duplicate():
    svc, session, repo = _make()
    svc._categories.get_by_id.return_value = _owned()
    svc._models.get_by_code.return_value = MagicMock()
    with pytest.raises(ConflictError, match="Model code"):
        svc.create_model(code="M1", name="CAT 320", category_id=CAT)


def test_create_model_happy():
    svc, session, repo = _make()
    svc._categories.get_by_id.return_value = _owned()
    svc._models.get_by_code.return_value = None
    svc._models.create.return_value = MagicMock(id=MODEL)
    svc.create_model(code="M1", name="CAT 320", category_id=CAT)
    svc._event_repo.append.assert_called_once()  # EquipmentModelCreated


def test_update_category_missing():
    svc, _, repo = _make()
    svc._categories.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.update_category(CAT, name="x")


def test_update_model_missing():
    svc, _, repo = _make()
    svc._models.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        svc.update_model(MODEL, name="x")


def test_transition_emits_availability_changed():
    svc, session, repo = _make()
    repo.get_by_id_or_raise.return_value = _equipment(status=EquipmentStatus.ACTIVE)
    svc.reserve_equipment(EQ)
    # EquipmentReserved + EquipmentStatusChanged + EquipmentAvailabilityChanged
    assert svc._event_repo.append.call_count == 3
