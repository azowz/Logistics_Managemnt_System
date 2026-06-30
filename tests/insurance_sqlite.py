"""Shared helpers for SQLite-backed Insurance & Claims tests.

Builds the full cross-domain schema needed by claims (tenant, user, customer,
order, warehouse, equipment, shipment, compliance, insurance/claims tables),
stripping the PostgreSQL-only regex CHECKs (``~``) so SQLite can create the
``shipments`` / ``insurance_policies`` / ``claims`` tables.
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
from app.models.compliance import ComplianceCheck, Permit
from app.models.customer import Customer
from app.models.equipment import Equipment, EquipmentCategory
from app.models.insurance import (
    Claim,
    CoverageRule,
    DamageReport,
    InsurancePolicy,
    LiabilityRecord,
)
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.warehouse import Warehouse


@compiles(JSONB, "sqlite")
def _jsonb(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


def _strip_pg_checks() -> None:
    for model in (Shipment, InsurancePolicy, Claim):
        for c in list(model.__table__.constraints):
            if isinstance(c, CheckConstraint) and "~" in str(c.sqltext):
                model.__table__.constraints.discard(c)


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
            Tenant.__table__, User.__table__, Customer.__table__, Order.__table__,
            Warehouse.__table__, EquipmentCategory.__table__, Equipment.__table__,
            Shipment.__table__, Permit.__table__, ComplianceCheck.__table__,
            InsurancePolicy.__table__, CoverageRule.__table__, Claim.__table__,
            DamageReport.__table__, LiabilityRecord.__table__,
        ],
    )
    return engine


def seed_tenant_user(SessionLocal, *, tenant_id, user_id):
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Ins T",
                         status="active", isolation_mode="shared"))
            s.commit()
        if s.get(User, user_id) is None:
            s.add(User(id=user_id, tenant_id=tenant_id, email=f"u-{user_id.hex[:8]}@t.test",
                       hashed_password="x", role="manager", is_active=True))
            s.commit()
    finally:
        s.close()


def seed_active_policy(SessionLocal, *, tenant_id, policy_id, covers_shipment=True,
                       covers_equipment=True, covers_third_party=True):
    s = SessionLocal()
    try:
        s.add(InsurancePolicy(
            id=policy_id, tenant_id=tenant_id, policy_number=f"POL-{policy_id.hex[:8]}",
            policy_type="cargo", status="active", currency_code="SAR",
            covers_shipment=covers_shipment, covers_equipment=covers_equipment,
            covers_third_party=covers_third_party,
        ))
        s.commit()
    finally:
        s.close()


def seed_shipment(SessionLocal, *, tenant_id, client_user_id, shipment_id, status="failed"):
    s = SessionLocal()
    try:
        wid = uuid.uuid4()
        s.add(Warehouse(id=wid, tenant_id=tenant_id, code=f"W{wid.hex[:6]}", name="d",
                        address_line1="1", city="R", country="SA",
                        capacity_weight_kg=1e6, capacity_volume_m3=1e6))
        s.commit()
        s.add(Shipment(id=shipment_id, tenant_id=tenant_id, reference_code=f"S{shipment_id.hex[:6]}",
                       client_id=client_user_id, origin_warehouse_id=wid, destination_warehouse_id=wid,
                       status=status, weight_kg=100, volume_m3=2))
        s.commit()
    finally:
        s.close()


def seed_equipment(SessionLocal, *, tenant_id, category_id, equipment_id, status="active"):
    s = SessionLocal()
    try:
        if s.get(EquipmentCategory, category_id) is None:
            s.add(EquipmentCategory(id=category_id, tenant_id=tenant_id, code=f"C{category_id.hex[:6]}", name="Earth"))
            s.commit()
        s.add(Equipment(id=equipment_id, tenant_id=tenant_id, equipment_code=f"EQP-{equipment_id.hex[:8]}",
                        asset_tag=f"TAG-{equipment_id.hex[:8]}", category_id=category_id, name="Excavator",
                        ownership_type="owned", status=status, availability_status="available"))
        s.commit()
    finally:
        s.close()


def seed_compliance_check(SessionLocal, *, tenant_id, check_id, shipment_id=None, status="failed"):
    s = SessionLocal()
    try:
        s.add(ComplianceCheck(id=check_id, tenant_id=tenant_id, shipment_id=shipment_id,
                              check_type="permit_required", status=status, blocking=True))
        s.commit()
    finally:
        s.close()
