"""Shared helpers for SQLite-backed Compliance tests.

Builds a cross-domain schema (tenant, user, warehouse, equipment, vehicle,
shipment + the six compliance tables), stripping the PostgreSQL-only regex CHECK
on ``shipments`` so SQLite can create it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base import Base
from app.models.compliance import (
    AxleWeightProfile,
    ComplianceCheck,
    Escort,
    OperatorCertification,
    Permit,
    RouteRestriction,
)
from app.models.driver import Driver
from app.models.equipment import Equipment, EquipmentCategory, EquipmentModel
from app.models.shipment import Shipment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.warehouse import Warehouse


@compiles(JSONB, "sqlite")
def _jsonb(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


def _strip_pg_checks() -> None:
    for c in list(Shipment.__table__.constraints):
        if isinstance(c, CheckConstraint) and "~" in str(c.sqltext):
            Shipment.__table__.constraints.discard(c)


def make_engine():
    _strip_pg_checks()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__, User.__table__, Warehouse.__table__,
            EquipmentCategory.__table__, EquipmentModel.__table__, Equipment.__table__,
            Vehicle.__table__, Driver.__table__, Shipment.__table__,
            RouteRestriction.__table__, Permit.__table__, Escort.__table__,
            AxleWeightProfile.__table__, ComplianceCheck.__table__,
            OperatorCertification.__table__,
        ],
    )
    return engine


def seed_tenant_user(SessionLocal, *, tenant_id, user_id):
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Compliance T",
                         status="active", isolation_mode="shared"))
            s.commit()
        if s.get(User, user_id) is None:
            s.add(User(id=user_id, tenant_id=tenant_id, email=f"u-{user_id.hex[:8]}@t.test",
                       hashed_password="x", role="manager", is_active=True))
            s.commit()
    finally:
        s.close()


def seed_shipment_with_equipment(
    SessionLocal, *, tenant_id, client_user_id, category_id, equipment_id, shipment_id,
    requires_permit=False, requires_escort=False, hazardous=False, eq_status="active",
):
    """Seed a warehouse, equipment (with flags), and a shipment referencing it."""
    s = SessionLocal()
    try:
        wid = uuid.uuid4()
        s.add(Warehouse(id=wid, tenant_id=tenant_id, code=f"WH-{wid.hex[:6]}", name="D",
                        address_line1="1", city="Riyadh", country="SA",
                        capacity_weight_kg=1_000_000, capacity_volume_m3=1_000_000))
        if s.get(EquipmentCategory, category_id) is None:
            s.add(EquipmentCategory(id=category_id, tenant_id=tenant_id,
                                    code=f"CAT-{category_id.hex[:6]}", name="Earth"))
        s.commit()
        s.add(Equipment(
            id=equipment_id, tenant_id=tenant_id, equipment_code=f"EQP-{equipment_id.hex[:8]}",
            asset_tag=f"TAG-{equipment_id.hex[:8]}", category_id=category_id, name="Excavator",
            ownership_type="owned", status=eq_status, availability_status="available",
            requires_permit=requires_permit, requires_escort=requires_escort, hazardous=hazardous,
            weight_kg=8000, volume_m3=30,
        ))
        s.commit()
        s.add(Shipment(
            id=shipment_id, tenant_id=tenant_id, reference_code=f"SHP-{shipment_id.hex[:8]}",
            client_id=client_user_id, origin_warehouse_id=wid, destination_warehouse_id=wid,
            equipment_id=equipment_id, status="ready", weight_kg=10000, volume_m3=50,
        ))
        s.commit()
    finally:
        s.close()
