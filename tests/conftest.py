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
