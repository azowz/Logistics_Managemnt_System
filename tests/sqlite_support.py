"""Shared building blocks for the per-domain ``*_sqlite.py`` test helpers.

Each domain helper creates only the tables its tests need in a single-connection
in-memory SQLite database. PostgreSQL-only DDL (JSONB, ``~`` regex CHECKs) is
handled globally by compile rules in ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register every mapper before create_all)
from app.db.base import Base
from app.models.tenant import Tenant
from app.models.user import User


def make_sqlite_engine(models: Iterable[type]) -> Engine:
    """Return an in-memory SQLite engine with the tables of ``models`` created.

    ``StaticPool`` keeps one shared connection so a TestClient thread sees the
    same in-memory database the fixtures seeded.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[m.__table__ for m in models])
    return engine


def seed_tenant_user(
    SessionLocal,
    *,
    tenant_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    role: str = "manager",
) -> None:
    """Idempotently insert a tenant and (optionally) one active user in it."""
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(
                Tenant(
                    id=tenant_id,
                    slug=f"t-{tenant_id.hex[:8]}",
                    name="Test tenant",
                    status="active",
                    isolation_mode="shared",
                )
            )
            s.commit()
        if user_id is not None and s.get(User, user_id) is None:
            s.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=f"u-{user_id.hex[:8]}@t.test",
                    hashed_password="x",
                    role=role,
                    is_active=True,
                )
            )
            s.commit()
    finally:
        s.close()
