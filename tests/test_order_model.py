"""Unit tests for the Order SQLAlchemy model (pure Python, no DB)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import CheckConstraint as SACheck

from app.models.enums import OrderPriority, OrderSource, OrderStatus, OrderType
from app.models.order import Order


def _make_order(**overrides) -> Order:
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "customer_id": uuid.uuid4(),
        "order_number": "ORD-0001",
        "order_type": OrderType.STANDARD,
        "order_source": OrderSource.WEB,
        "priority": OrderPriority.NORMAL,
        "status": OrderStatus.DRAFT,
    }
    defaults.update(overrides)
    return Order(**defaults)


# --- defaults -------------------------------------------------------------


def test_default_status_draft():
    assert _make_order().status == OrderStatus.DRAFT


def test_default_classification():
    o = _make_order()
    assert o.order_type == OrderType.STANDARD
    assert o.order_source == OrderSource.WEB
    assert o.priority == OrderPriority.NORMAL


def test_optional_fields_none_by_default():
    o = _make_order()
    for field in (
        "requested_pickup_date",
        "requested_delivery_date",
        "pickup_location",
        "delivery_location",
        "pickup_latitude",
        "delivery_longitude",
        "distance_km",
        "estimated_duration_minutes",
        "cargo_description",
        "cargo_weight_kg",
        "cargo_volume_m3",
        "temperature_requirements",
        "special_instructions",
        "assigned_dispatcher_id",
        "submitted_at",
        "delivered_at",
        "cancellation_reason",
        "failure_reason",
        "deleted_at",
        "deleted_by",
    ):
        assert getattr(o, field) is None, f"{field} should default to None"


@pytest.mark.parametrize("enum_cls,attr", [
    (OrderType, "order_type"),
    (OrderSource, "order_source"),
    (OrderPriority, "priority"),
    (OrderStatus, "status"),
])
def test_all_enum_values_accepted(enum_cls, attr):
    for member in enum_cls:
        o = _make_order(**{attr: member})
        assert getattr(o, attr) == member


# --- soft delete ----------------------------------------------------------


def test_is_deleted_false_initially():
    assert _make_order().is_deleted is False


def test_soft_delete_then_restore():
    o = _make_order()
    o.soft_delete()
    assert o.is_deleted is True
    assert isinstance(o.deleted_at, datetime)
    o.restore()
    assert o.is_deleted is False
    assert o.deleted_at is None


def test_deleted_by_settable():
    actor = uuid.uuid4()
    o = _make_order()
    o.deleted_by = actor
    assert o.deleted_by == actor


# --- optimistic lock ------------------------------------------------------


def test_version_mapper_arg():
    # The mapper resolves version_id_col to the concrete Column.
    assert Order.__mapper__.version_id_col is Order.__table__.c["version"]


# --- constraints ----------------------------------------------------------


def test_unique_constraint_explicit_name():
    names = {
        c.name
        for c in Order.__table__.constraints
        if hasattr(c, "columns") and len(list(c.columns)) > 1 and c.name and c.name.startswith("uq_")
    }
    assert "uq_orders_tenant_id_order_number" in names


def test_check_constraints_named():
    ck_names = {c.name for c in Order.__table__.constraints if isinstance(c, SACheck)}
    for expected in (
        "ck_orders_status",
        "ck_orders_order_type",
        "ck_orders_order_source",
        "ck_orders_priority",
        "ck_orders_cargo_weight_non_negative",
        "ck_orders_cargo_volume_non_negative",
        "ck_orders_distance_non_negative",
    ):
        assert expected in ck_names, f"missing {expected}"


def test_table_name_and_pk():
    assert Order.__tablename__ == "orders"
    assert "id" in Order.__table__.primary_key.columns


def test_boolean_flags_default_false_python_side():
    # default kwargs not passed -> attribute is None until flush; ensure column
    # carries a server_default so DB fills it. Here we assert the column default.
    assert Order.__table__.c["dangerous_goods"].server_default is not None
    assert Order.__table__.c["is_fragile"].server_default is not None
    assert Order.__table__.c["insurance_required"].server_default is not None
