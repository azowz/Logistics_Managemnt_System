"""Shared helpers for SQLite-backed Shipment tests.

The production ``shipments`` table carries a PostgreSQL-only regex CHECK
(``currency_code ~ '^[A-Z]{3}$'``) that SQLite cannot parse. These helpers
strip such PG-only CHECK constraints from the in-memory test schema (they are
irrelevant on SQLite) and seed the FK prerequisites a shipment references.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register all models on Base.metadata
from app.db.base import Base
from app.models.customer import Customer
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.models.warehouse import Warehouse


def _strip_pg_only_checks() -> None:
    """Remove regex (``~``) CHECK constraints unsupported by SQLite (idempotent)."""
    for c in list(Shipment.__table__.constraints):
        if isinstance(c, CheckConstraint) and "~" in str(c.sqltext):
            Shipment.__table__.constraints.discard(c)


def make_engine():
    """Return a shared-connection in-memory SQLite engine with the schema built."""
    _strip_pg_only_checks()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__,
            User.__table__,
            Customer.__table__,
            Order.__table__,
            Warehouse.__table__,
            Driver.__table__,
            Vehicle.__table__,
            Shipment.__table__,
        ],
    )
    return engine


def seed_prereqs(
    SessionLocal,
    *,
    tenant_id: uuid.UUID,
    client_id: uuid.UUID,
    origin_id: uuid.UUID,
    dest_id: uuid.UUID,
    capacity: float = 1_000_000.0,
) -> None:
    """Seed a tenant, a client user, and two warehouses for a shipment."""
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(
                Tenant(
                    id=tenant_id,
                    slug=f"t-{tenant_id.hex[:8]}",
                    name="Shipment Tenant",
                    status="active",
                    isolation_mode="shared",
                )
            )
        if s.get(User, client_id) is None:
            s.add(
                User(
                    id=client_id,
                    tenant_id=tenant_id,
                    email=f"client-{client_id.hex[:8]}@t.test",
                    hashed_password="x",
                    role="client",
                    is_active=True,
                )
            )
        for wid, code in ((origin_id, "ORIG"), (dest_id, "DEST")):
            if s.get(Warehouse, wid) is None:
                s.add(
                    Warehouse(
                        id=wid,
                        tenant_id=tenant_id,
                        code=f"{code}-{wid.hex[:6]}",
                        name=f"{code} WH",
                        address_line1="1 St",
                        city="Riyadh",
                        country="SA",
                        capacity_weight_kg=capacity,
                        capacity_volume_m3=capacity,
                    )
                )
        s.commit()
    finally:
        s.close()


def seed_driver_and_vehicle(
    SessionLocal,
    *,
    tenant_id: uuid.UUID,
    driver_user_id: uuid.UUID,
    driver_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    capacity: float = 1_000_000.0,
    driver_available: bool = True,
) -> None:
    """Seed a driver (with its driver-role user) and an active vehicle."""
    s = SessionLocal()
    try:
        if s.get(User, driver_user_id) is None:
            s.add(
                User(
                    id=driver_user_id,
                    tenant_id=tenant_id,
                    email=f"drv-{driver_user_id.hex[:8]}@t.test",
                    hashed_password="x",
                    role="driver",
                    is_active=True,
                )
            )
            s.commit()
        if s.get(Driver, driver_id) is None:
            s.add(
                Driver(
                    id=driver_id,
                    tenant_id=tenant_id,
                    user_id=driver_user_id,
                    license_number=f"LIC-{driver_id.hex[:6]}",
                    is_available=driver_available,
                )
            )
        if s.get(Vehicle, vehicle_id) is None:
            s.add(
                Vehicle(
                    id=vehicle_id,
                    tenant_id=tenant_id,
                    plate_number=f"PLT-{vehicle_id.hex[:6]}",
                    status="active",
                    capacity_weight_kg=capacity,
                    capacity_volume_m3=capacity,
                )
            )
        s.commit()
    finally:
        s.close()
