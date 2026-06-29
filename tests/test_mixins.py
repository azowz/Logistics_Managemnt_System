"""Unit tests for ORM mixins (app.db.mixins).

Tests verify both the pure-Python behaviour of mixin methods (soft_delete,
restore, is_deleted) and the SQLAlchemy column definitions that the mixins
contribute to concrete models.

A lightweight, isolated SQLite database is spun up within this module so the
mixin integration can be verified end-to-end without touching the application's
main database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin, TenantMixin


# ---------------------------------------------------------------------------
# Isolated declarative base (avoids polluting the application Base.metadata)
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _FullRecord(_TestBase, SoftDeleteMixin, TimestampMixin, AuditMixin):
    """Concrete model that exercises all audit/soft-delete columns."""

    __tablename__ = "_test_full_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="test")


class _TenantRecord(_TestBase, TenantMixin):
    """Concrete model that exercises the tenant column."""

    __tablename__ = "_test_tenant_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


# Build the schema once for the module.
_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
_TestBase.metadata.create_all(_engine)
_Factory = sessionmaker(bind=_engine, autocommit=False, autoflush=False, future=True)


@pytest.fixture()
def session() -> Session:
    """Provide a session that is rolled back after each test."""
    s = _Factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


# ---------------------------------------------------------------------------
# SoftDeleteMixin — is_deleted property
# ---------------------------------------------------------------------------


def test_soft_delete_initially_not_deleted(session: Session) -> None:
    r = _FullRecord(name="alice")
    session.add(r)
    session.flush()
    assert r.is_deleted is False


def test_soft_delete_deleted_at_initially_none(session: Session) -> None:
    r = _FullRecord(name="bob")
    session.add(r)
    session.flush()
    assert r.deleted_at is None


# ---------------------------------------------------------------------------
# SoftDeleteMixin — soft_delete()
# ---------------------------------------------------------------------------


def test_soft_delete_sets_deleted_at(session: Session) -> None:
    r = _FullRecord(name="carol")
    session.add(r)
    session.flush()

    r.soft_delete()
    assert r.deleted_at is not None


def test_soft_delete_deleted_at_is_datetime(session: Session) -> None:
    r = _FullRecord(name="dave")
    session.add(r)
    session.flush()

    r.soft_delete()
    assert isinstance(r.deleted_at, datetime)


def test_soft_delete_is_deleted_becomes_true(session: Session) -> None:
    r = _FullRecord(name="eve")
    session.add(r)
    session.flush()

    r.soft_delete()
    assert r.is_deleted is True


def test_soft_delete_is_idempotent(session: Session) -> None:
    """Second call must not overwrite the original deletion timestamp."""
    r = _FullRecord(name="frank")
    session.add(r)
    session.flush()

    r.soft_delete()
    first_ts = r.deleted_at

    r.soft_delete()  # idempotent
    assert r.deleted_at == first_ts


# ---------------------------------------------------------------------------
# SoftDeleteMixin — restore()
# ---------------------------------------------------------------------------


def test_restore_clears_deleted_at(session: Session) -> None:
    r = _FullRecord(name="grace")
    session.add(r)
    session.flush()

    r.soft_delete()
    assert r.is_deleted is True

    r.restore()
    assert r.deleted_at is None


def test_restore_is_deleted_becomes_false(session: Session) -> None:
    r = _FullRecord(name="heidi")
    session.add(r)
    session.flush()

    r.soft_delete()
    r.restore()
    assert r.is_deleted is False


def test_restore_on_active_record_is_noop(session: Session) -> None:
    """Restoring a non-deleted record must leave it with deleted_at=None."""
    r = _FullRecord(name="ivan")
    session.add(r)
    session.flush()

    r.restore()  # already active
    assert r.deleted_at is None


def test_soft_delete_restore_cycle(session: Session) -> None:
    """A full delete→restore→delete cycle must work correctly."""
    r = _FullRecord(name="judy")
    session.add(r)
    session.flush()

    r.soft_delete()
    assert r.is_deleted is True

    r.restore()
    assert r.is_deleted is False

    r.soft_delete()
    assert r.is_deleted is True


# ---------------------------------------------------------------------------
# TimestampMixin — column presence
# ---------------------------------------------------------------------------


def test_timestamp_mixin_created_at_column_exists() -> None:
    """TimestampMixin must add a 'created_at' column to the mapped table."""
    from sqlalchemy import inspect as sa_inspect

    cols = {c["name"] for c in sa_inspect(_engine).get_columns("_test_full_record")}
    assert "created_at" in cols


def test_timestamp_mixin_updated_at_column_exists() -> None:
    from sqlalchemy import inspect as sa_inspect

    cols = {c["name"] for c in sa_inspect(_engine).get_columns("_test_full_record")}
    assert "updated_at" in cols


# ---------------------------------------------------------------------------
# AuditMixin — column presence
# ---------------------------------------------------------------------------


def test_audit_mixin_created_by_column_exists() -> None:
    from sqlalchemy import inspect as sa_inspect

    cols = {c["name"] for c in sa_inspect(_engine).get_columns("_test_full_record")}
    assert "created_by" in cols


def test_audit_mixin_updated_by_column_exists() -> None:
    from sqlalchemy import inspect as sa_inspect

    cols = {c["name"] for c in sa_inspect(_engine).get_columns("_test_full_record")}
    assert "updated_by" in cols


def test_audit_mixin_created_by_defaults_to_none(session: Session) -> None:
    r = _FullRecord(name="ken")
    session.add(r)
    session.flush()
    assert r.created_by is None


def test_audit_mixin_created_by_accepts_uuid(session: Session) -> None:
    actor = uuid.uuid4()
    r = _FullRecord(name="lana", created_by=actor)
    session.add(r)
    session.flush()
    # SQLite returns uuid as string; normalize for comparison.
    stored = r.created_by
    if isinstance(stored, str):
        stored = uuid.UUID(stored)
    assert stored == actor


# ---------------------------------------------------------------------------
# TenantMixin — column presence and NOT NULL
# ---------------------------------------------------------------------------


def test_tenant_mixin_tenant_id_column_exists() -> None:
    from sqlalchemy import inspect as sa_inspect

    cols = {c["name"] for c in sa_inspect(_engine).get_columns("_test_tenant_record")}
    assert "tenant_id" in cols


def test_tenant_mixin_tenant_id_not_nullable() -> None:
    from sqlalchemy import inspect as sa_inspect

    cols = {
        c["name"]: c
        for c in sa_inspect(_engine).get_columns("_test_tenant_record")
    }
    assert cols["tenant_id"]["nullable"] is False


def test_tenant_mixin_stores_and_retrieves_uuid(session: Session) -> None:
    tid = uuid.uuid4()
    r = _TenantRecord(tenant_id=tid)
    session.add(r)
    session.flush()

    stored = r.tenant_id
    if isinstance(stored, str):
        stored = uuid.UUID(stored)
    assert stored == tid
