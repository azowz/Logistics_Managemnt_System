"""Cross-tenant isolation gate (Postgres-only) — the M1 exit criterion.

This is the authoritative proof that Row-Level Security isolates tenants and that
``SET LOCAL`` does not leak across transactions on a pooled connection
(docs/07 M1 exit gate; docs/11 §7). It requires a real PostgreSQL database and is
**skipped** unless ``TEST_DATABASE_URL`` points at one (CI provides it; Docker
compose `db` works locally). It applies the same RLS policy the migration ships.

Run locally, e.g.:
    TEST_DATABASE_URL=postgresql+psycopg2://mesaar:mesaar@localhost:5432/mesaar_test \\
        .venv/Scripts/pytest tests/test_tenant_isolation_pg.py
"""

from __future__ import annotations

import os
import uuid

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_DB.startswith("postgres"),
    reason="requires a PostgreSQL TEST_DATABASE_URL",
)

NIL = "00000000-0000-0000-0000-000000000000"
_POLICY_TABLE = "users"


def _set_tenant(conn, tenant_id: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text("SELECT set_config('app.current_tenant', :v, true)"), {"v": tenant_id}
    )


@pytest.fixture()
def pg_engine():
    from sqlalchemy import text

    from app.db.base import Base
    import app.models.tenant  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.driver  # noqa: F401
    import app.models.vehicle  # noqa: F401
    import app.models.warehouse  # noqa: F401
    import app.models.shipment  # noqa: F401
    import app.models.shipment_tracking_event  # noqa: F401
    from sqlalchemy import create_engine

    engine = create_engine(TEST_DB)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    # Apply the same RLS policy the migration ships, for the users table.
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {_POLICY_TABLE} ENABLE ROW LEVEL SECURITY"))
        conn.execute(text(f"ALTER TABLE {_POLICY_TABLE} FORCE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                f"""
                CREATE POLICY tenant_isolation ON {_POLICY_TABLE}
                  USING (
                    tenant_id = current_setting('app.current_tenant', true)::uuid
                    OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid
                  )
                  WITH CHECK (
                    tenant_id = current_setting('app.current_tenant', true)::uuid
                    OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid
                  )
                """
            )
        )
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed(engine):
    """Seed two tenants and one user each (under platform scope)."""
    from sqlalchemy import text

    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        _set_tenant(conn, NIL)  # platform can write any tenant's rows
        for tid, slug in ((tenant_a, "tenant-a"), (tenant_b, "tenant-b")):
            conn.execute(
                text(
                    "INSERT INTO tenants (id, slug, name, status, isolation_mode, created_at, updated_at) "
                    "VALUES (:id, :slug, :slug, 'active', 'shared', now(), now())"
                ),
                {"id": str(tid), "slug": slug},
            )
        for tid, email in ((tenant_a, "a@x.com"), (tenant_b, "b@x.com")):
            conn.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, hashed_password, role, is_active, created_at, updated_at) "
                    "VALUES (:id, :tid, :email, 'x', 'client', true, now(), now())"
                ),
                {"id": str(uuid.uuid4()), "tid": str(tid), "email": email},
            )
    return tenant_a, tenant_b


def test_tenant_sees_only_its_own_rows(pg_engine) -> None:
    from sqlalchemy import text

    tenant_a, tenant_b = _seed(pg_engine)
    with pg_engine.connect() as conn:
        with conn.begin():
            _set_tenant(conn, str(tenant_a))
            emails = {r[0] for r in conn.execute(text("SELECT email FROM users"))}
        assert emails == {"a@x.com"}

        with conn.begin():
            _set_tenant(conn, str(tenant_b))
            emails = {r[0] for r in conn.execute(text("SELECT email FROM users"))}
        assert emails == {"b@x.com"}


def test_unset_tenant_sees_nothing_fail_closed(pg_engine) -> None:
    from sqlalchemy import text

    _seed(pg_engine)
    with pg_engine.connect() as conn:
        with conn.begin():
            # No set_config at all -> current_setting returns NULL -> deny all.
            rows = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
        assert rows == 0


def test_platform_scope_sees_all(pg_engine) -> None:
    from sqlalchemy import text

    _seed(pg_engine)
    with pg_engine.connect() as conn:
        with conn.begin():
            _set_tenant(conn, NIL)
            rows = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
        assert rows == 2


def test_set_local_does_not_leak_across_transactions(pg_engine) -> None:
    from sqlalchemy import text

    tenant_a, tenant_b = _seed(pg_engine)
    # Reuse ONE connection (simulating a pooled checkout) across two txns with
    # different tenants; SET LOCAL must reset at each commit so no leak occurs.
    with pg_engine.connect() as conn:
        with conn.begin():
            _set_tenant(conn, str(tenant_a))
            a = {r[0] for r in conn.execute(text("SELECT email FROM users"))}
        # New transaction, no set_config -> must be fail-closed, NOT tenant_a.
        with conn.begin():
            leaked = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
        assert a == {"a@x.com"}
        assert leaked == 0, "SET LOCAL leaked into the next transaction"
