"""Metadata-level checks for the M1 multi-tenancy model changes (no DB needed).

These assert the *shape* of the mapped schema — that every aggregate carries a
``tenant_id`` FK to ``tenants`` and that natural keys became per-tenant
composites (ADR-001 / docs/03 §3.2). They run on any backend because they only
introspect ``Base.metadata``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import UniqueConstraint

from app.db.base import Base
from app.db.tenant import PLATFORM_TENANT_ID

# Import models so they register on Base.metadata.
import app.models.tenant  # noqa: F401
import app.models.user  # noqa: F401
import app.models.driver  # noqa: F401
import app.models.vehicle  # noqa: F401
import app.models.warehouse  # noqa: F401
import app.models.shipment  # noqa: F401
import app.models.shipment_tracking_event  # noqa: F401

TENANT_TABLES = [
    "users",
    "drivers",
    "vehicles",
    "warehouses",
    "shipments",
    "shipment_tracking_events",
]


def _unique_col_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(c.name for c in con.columns)
        for con in table.constraints
        if isinstance(con, UniqueConstraint)
    }


def test_platform_tenant_is_nil_uuid() -> None:
    assert PLATFORM_TENANT_ID == uuid.UUID("00000000-0000-0000-0000-000000000000")


def test_tenants_table_exists_and_has_no_tenant_id() -> None:
    assert "tenants" in Base.metadata.tables
    # The boundary table itself is not tenant-scoped.
    assert "tenant_id" not in Base.metadata.tables["tenants"].columns


def test_every_aggregate_has_tenant_id_fk_to_tenants() -> None:
    for name in TENANT_TABLES:
        cols = Base.metadata.tables[name].columns
        assert "tenant_id" in cols, f"{name} is missing tenant_id"
        col = cols["tenant_id"]
        assert col.nullable is False, f"{name}.tenant_id must be NOT NULL"
        fks = list(col.foreign_keys)
        assert fks, f"{name}.tenant_id has no FK"
        assert fks[0].column.table.name == "tenants"


def test_per_tenant_composite_uniques() -> None:
    assert ("tenant_id", "email") in _unique_col_sets("users")
    assert ("tenant_id", "code") in _unique_col_sets("warehouses")
    assert ("tenant_id", "reference_code") in _unique_col_sets("shipments")
    assert ("tenant_id", "plate_number") in _unique_col_sets("vehicles")
    assert ("tenant_id", "vin") in _unique_col_sets("vehicles")
    assert ("tenant_id", "user_id") in _unique_col_sets("drivers")
    assert ("tenant_id", "license_number") in _unique_col_sets("drivers")


def test_old_single_column_uniques_are_gone() -> None:
    # Email/code/etc. must NOT be unique on their own anymore.
    assert ("email",) not in _unique_col_sets("users")
    assert ("code",) not in _unique_col_sets("warehouses")
    assert ("reference_code",) not in _unique_col_sets("shipments")
