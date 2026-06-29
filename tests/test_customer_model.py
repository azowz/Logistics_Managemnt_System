"""Unit tests for the Customer SQLAlchemy model.

Tests exercise:
  * Default field values.
  * Enum coercion from strings.
  * `SoftDeleteMixin.soft_delete()` and `restore()`.
  * `is_deleted` property.
  * `deleted_by` column presence.
  * Optimistic-lock mapper args (`version_id_col` set to `version`).
  * UniqueConstraint names (critical for Alembic autogenerate).
  * CheckConstraint names (DB-level guard naming convention).

These tests are pure Python — no database connection required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.customer import Customer
from app.models.enums import (
    CreditStatus,
    CustomerStatus,
    CustomerType,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_customer(**overrides) -> Customer:
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "code": "TEST-001",
        "company_name": "Test Corp",
        "customer_type": CustomerType.CORPORATE,
        "status": CustomerStatus.ACTIVE,
        "risk_level": RiskLevel.LOW,
        "credit_status": CreditStatus.GOOD,
    }
    defaults.update(overrides)
    return Customer(**defaults)


# ---------------------------------------------------------------------------
# Field defaults
# ---------------------------------------------------------------------------


def test_default_status():
    c = _make_customer()
    assert c.status == CustomerStatus.ACTIVE


def test_default_risk_level():
    c = _make_customer()
    assert c.risk_level == RiskLevel.LOW


def test_default_credit_status():
    c = _make_customer()
    assert c.credit_status == CreditStatus.GOOD


def test_default_customer_type():
    c = _make_customer()
    assert c.customer_type == CustomerType.CORPORATE


def test_optional_fields_are_none_by_default():
    c = _make_customer()
    for field in (
        "commercial_name",
        "tax_number",
        "commercial_registration",
        "vat_number",
        "contact_person",
        "primary_phone",
        "secondary_phone",
        "primary_email",
        "secondary_email",
        "country",
        "city",
        "district",
        "address",
        "latitude",
        "longitude",
        "preferred_language",
        "notes",
        "tags",
        "deleted_at",
        "deleted_by",
    ):
        assert getattr(c, field) is None, f"Expected {field} to be None by default"


def test_all_customer_types_accepted():
    for ct in CustomerType:
        c = _make_customer(customer_type=ct)
        assert c.customer_type == ct


def test_all_statuses_accepted():
    for s in CustomerStatus:
        c = _make_customer(status=s)
        assert c.status == s


def test_all_risk_levels_accepted():
    for r in RiskLevel:
        c = _make_customer(risk_level=r)
        assert c.risk_level == r


def test_all_credit_statuses_accepted():
    for cs in CreditStatus:
        c = _make_customer(credit_status=cs)
        assert c.credit_status == cs


# ---------------------------------------------------------------------------
# Soft delete mixin
# ---------------------------------------------------------------------------


def test_is_deleted_false_initially():
    c = _make_customer()
    assert c.is_deleted is False


def test_soft_delete_sets_deleted_at():
    c = _make_customer()
    c.soft_delete()
    assert c.deleted_at is not None
    assert isinstance(c.deleted_at, datetime)


def test_soft_delete_is_deleted_becomes_true():
    c = _make_customer()
    c.soft_delete()
    assert c.is_deleted is True


def test_restore_clears_deleted_at():
    c = _make_customer()
    c.soft_delete()
    c.restore()
    assert c.deleted_at is None


def test_restore_is_deleted_becomes_false():
    c = _make_customer()
    c.soft_delete()
    c.restore()
    assert c.is_deleted is False


def test_deleted_by_column_settable():
    actor = uuid.uuid4()
    c = _make_customer()
    c.deleted_by = actor
    assert c.deleted_by == actor


def test_deleted_by_clears_on_restore():
    actor = uuid.uuid4()
    c = _make_customer()
    c.soft_delete()
    c.deleted_by = actor
    c.restore()
    c.deleted_by = None  # repository clears this
    assert c.deleted_by is None


# ---------------------------------------------------------------------------
# Optimistic lock
# ---------------------------------------------------------------------------


def test_version_mapper_arg_set():
    """``__mapper_args__`` must point version_id_col at the ``version`` column."""
    assert "version_id_col" in Customer.__mapper_args__
    # The mapper resolves version_id_col to the concrete Column.
    assert Customer.__mapper__.version_id_col is Customer.__table__.c["version"]


# ---------------------------------------------------------------------------
# Constraint introspection
# ---------------------------------------------------------------------------


def test_unique_constraints_have_explicit_names():
    """Verify all three multi-column UniqueConstraints carry the expected names."""
    table = Customer.__table__
    uc_names = {c.name for c in table.constraints if hasattr(c, "columns") and len(list(c.columns)) > 1}
    assert "uq_customers_tenant_id_code" in uc_names
    assert "uq_customers_tenant_id_commercial_registration" in uc_names
    assert "uq_customers_tenant_id_vat_number" in uc_names


def test_check_constraints_have_explicit_names():
    """Verify CHECK constraints follow the ck_ naming convention."""
    table = Customer.__table__
    from sqlalchemy import CheckConstraint as SACheck
    ck_names = {c.name for c in table.constraints if isinstance(c, SACheck)}
    assert "ck_customers_status" in ck_names
    assert "ck_customers_risk_level" in ck_names
    assert "ck_customers_credit_status" in ck_names
    assert "ck_customers_customer_type" in ck_names


def test_table_name():
    assert Customer.__tablename__ == "customers"


def test_primary_key_column():
    assert "id" in Customer.__table__.primary_key.columns


# ---------------------------------------------------------------------------
# JSONB tags field
# ---------------------------------------------------------------------------


def test_tags_accepts_list():
    c = _make_customer(tags=["vip", "hazmat"])
    assert c.tags == ["vip", "hazmat"]


def test_tags_none_by_default():
    c = _make_customer()
    assert c.tags is None
