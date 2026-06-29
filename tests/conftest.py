"""Pytest configuration and shared fixtures.

Environment is configured **before** any ``app`` import so the SQLAlchemy engine
(built at import time in :mod:`app.db.session`) uses an in-memory SQLite database
and a valid settings object. This lets the unit suite run with no Postgres,
Redis, or ``.env`` present. Postgres-only tests (RLS / tenant isolation) opt in
via the ``TEST_DATABASE_URL`` environment variable and skip otherwise.
"""

from __future__ import annotations

import os

# Must run before `app.*` is imported (the engine is built at import time).
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-that-is-32+chars-long!!")
os.environ.setdefault("ENVIRONMENT", "test")

# ---------------------------------------------------------------------------
# Cross-dialect test shim: render PostgreSQL ``JSONB`` as ``JSON`` on SQLite.
#
# Production runs on PostgreSQL where JSONB is native; the in-memory SQLite used
# by the unit/integration suite has no JSONB renderer. Registering this compile
# rule lets ``Base.metadata.create_all()`` build JSONB-bearing tables (tenants,
# customers, event_store, ...) under SQLite without touching production models.
# ---------------------------------------------------------------------------
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _render_jsonb_as_json_on_sqlite(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"
