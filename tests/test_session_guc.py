"""Unit tests for the tenant-GUC ``after_begin`` listener (RLS chokepoint).

The listener is what makes RLS effective on pooled connections: it issues
``SELECT set_config('app.current_tenant', ..., true)`` at the start of each
transaction, reading the request-local tenant ContextVar and falling back to the
platform (nil-UUID) tenant. These tests exercise that logic with a fake
connection so they run on any backend (the real listener no-ops off PostgreSQL).
"""

from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.session import _apply_tenant_guc_on_begin
from app.db.tenant import (
    PLATFORM_TENANT_ID,
    get_current_tenant,
    reset_current_tenant,
    reset_current_user_id,
    set_current_tenant,
    set_current_user_id,
)

_GUC = "app.current_tenant"
_USER_GUC = "app.current_user_id"


class _FakeDialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeConnection:
    """Records ``execute`` calls so we can assert the emitted GUC SQL."""

    def __init__(self, dialect_name: str) -> None:
        self.dialect = _FakeDialect(dialect_name)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, clause, params=None):  # noqa: ANN001 - test double
        self.calls.append((str(clause), params or {}))
        return None


def test_listener_is_registered_on_session() -> None:
    assert event.contains(Session, "after_begin", _apply_tenant_guc_on_begin)


def test_applies_tenant_and_user_gucs_on_postgres() -> None:
    tenant, actor = uuid.uuid4(), uuid.uuid4()
    tt = set_current_tenant(tenant)
    ut = set_current_user_id(actor)
    conn = _FakeConnection("postgresql")
    try:
        _apply_tenant_guc_on_begin(None, None, conn)
    finally:
        reset_current_user_id(ut)
        reset_current_tenant(tt)

    # Two GUCs are applied per transaction: tenant first, then acting user.
    assert len(conn.calls) == 2
    assert all("set_config" in sql for sql, _ in conn.calls)
    assert conn.calls[0][1] == {"guc": _GUC, "value": str(tenant)}
    assert conn.calls[1][1] == {"guc": _USER_GUC, "value": str(actor)}


def test_falls_back_to_platform_tenant_and_empty_user() -> None:
    # Nothing bound -> platform tenant + empty (system) user.
    assert get_current_tenant() is None
    conn = _FakeConnection("postgresql")
    _apply_tenant_guc_on_begin(None, None, conn)

    assert len(conn.calls) == 2
    assert conn.calls[0][1]["value"] == str(PLATFORM_TENANT_ID)
    assert conn.calls[1][1] == {"guc": _USER_GUC, "value": ""}


def test_noop_off_postgres() -> None:
    token = set_current_tenant(uuid.uuid4())
    conn = _FakeConnection("sqlite")
    try:
        _apply_tenant_guc_on_begin(None, None, conn)
    finally:
        reset_current_tenant(token)
    assert conn.calls == []


def test_contextvar_set_get_reset_roundtrip() -> None:
    assert get_current_tenant() is None
    a, b = uuid.uuid4(), uuid.uuid4()
    ta = set_current_tenant(a)
    assert get_current_tenant() == a
    tb = set_current_tenant(b)
    assert get_current_tenant() == b
    reset_current_tenant(tb)
    assert get_current_tenant() == a
    reset_current_tenant(ta)
    assert get_current_tenant() is None
