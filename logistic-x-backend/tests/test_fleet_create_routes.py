"""Regression: the basic create endpoints persist rows in the caller's tenant.

``tenant_id`` is NOT NULL on users/drivers/vehicles/warehouses and is not part of
the request payloads, so the route must take it from the authenticated user.
Before the fix every one of these endpoints failed with an IntegrityError (500).
"""

from __future__ import annotations

import types
import uuid
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import drivers, users, vehicles, warehouses
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.base import Base
from app.db.session import get_session
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.warehouse import Warehouse

_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(bind=_engine, autocommit=False, autoflush=False, expire_on_commit=False)
_TABLES = [t.__table__ for t in (Tenant, User, Warehouse, Vehicle, Driver)]
_TENANT = uuid.uuid4()


def _session() -> Iterator[Session]:
    s = _Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    Base.metadata.create_all(_engine, tables=_TABLES)
    s = _Session()
    s.add(Tenant(id=_TENANT, slug="fleet-tenant", name="Fleet", status="active"))
    s.commit()
    s.close()

    app = FastAPI()
    install_exception_handlers(app)
    for module in (users, drivers, vehicles, warehouses):
        app.include_router(module.router)
    app.dependency_overrides[get_session] = _session
    admin = types.SimpleNamespace(
        id=uuid.uuid4(), tenant_id=_TENANT, role=UserRole.ADMIN, is_active=True
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    Base.metadata.drop_all(_engine, tables=_TABLES)


def _tenant_of(model, row_id: str) -> uuid.UUID:
    s = _Session()
    try:
        return s.get(model, uuid.UUID(row_id)).tenant_id
    finally:
        s.close()


def test_create_user_uses_admin_tenant(client: TestClient) -> None:
    r = client.post(
        "/users",
        json={
            "email": "driver1@example.com",
            "full_name": "Driver One",
            "password": "a-strong-password-123",
            "role": "driver",
        },
    )
    assert r.status_code == 201, r.text
    assert _tenant_of(User, r.json()["id"]) == _TENANT


def test_create_warehouse_vehicle_driver_use_caller_tenant(client: TestClient) -> None:
    wh = client.post(
        "/warehouses",
        json={
            "code": "WH-1",
            "name": "Main depot",
            "address_line1": "Street 1",
            "city": "Riyadh",
            "country": "SA",
            "capacity_weight_kg": 1000,
            "capacity_volume_m3": 100,
        },
    )
    assert wh.status_code == 201, wh.text
    assert _tenant_of(Warehouse, wh.json()["id"]) == _TENANT

    vehicle = client.post(
        "/vehicles",
        json={"plate_number": "ABC-123", "capacity_weight_kg": 500, "capacity_volume_m3": 20},
    )
    assert vehicle.status_code == 201, vehicle.text
    assert _tenant_of(Vehicle, vehicle.json()["id"]) == _TENANT

    user = client.post(
        "/users",
        json={
            "email": "driver2@example.com",
            "full_name": "Driver Two",
            "password": "a-strong-password-123",
            "role": "driver",
        },
    )
    driver = client.post(
        "/drivers",
        json={"user_id": user.json()["id"], "license_number": "LIC-001"},
    )
    assert driver.status_code == 201, driver.text
    assert _tenant_of(Driver, driver.json()["id"]) == _TENANT
