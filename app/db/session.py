"""Database session factory and dependency helpers.

This module owns the process-wide SQLAlchemy ``engine``, the ``SessionLocal``
factory, and the ``get_session`` FastAPI dependency. These three symbols are
part of the foundation's public contract and must remain importable with
behavior-compatible semantics.

The engine is configured with connection-pool parameters sourced from
:class:`app.core.config.Settings` (the ``db_pool_*`` / ``db_echo`` fields). A
``session_scope`` context manager is provided for non-request code paths
(scripts, workers, startup tasks) that need a committed unit of work, and a thin
re-export of :func:`app.db.tenant.apply_tenant_guc` lets callers attach the
current tenant to a session for Row-Level Security.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.tenant import apply_tenant_guc as apply_tenant_guc  # re-exported for callers
from app.observability.logging import get_logger

logger = get_logger(__name__)


def _build_engine() -> Engine:
    """Create a SQLAlchemy engine with pool settings drawn from config.

    SQLite (commonly used in tests) does not support the queue-pool sizing
    parameters, so they are only applied for server-class databases. This keeps
    the same factory usable across ``development``/``test`` and production.
    """

    settings = get_settings()
    engine_kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
        "echo": settings.db_echo,
    }

    # Pool sizing is meaningful for connection-pooled backends (e.g. Postgres)
    # but not for SQLite, whose default SingletonThreadPool/NullPool rejects
    # these arguments. Detect by URL scheme.
    if not settings.database_url.startswith("sqlite"):
        engine_kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle_seconds,
        )

    return create_engine(settings.database_url, **engine_kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a database session.

    The session is always closed when the request completes; transaction
    management (commit/rollback) is left to the calling endpoint/service so that
    business semantics stay explicit.
    """
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope(tenant_id: uuid.UUID | None = None) -> Iterator[Session]:
    """Provide a transactional session scope for non-request code paths.

    Commits on success, rolls back on any exception, and always closes the
    session. When ``tenant_id`` is supplied, the tenant GUC is applied so that
    Row-Level Security policies see the correct tenant for the unit of work.

    Example::

        with session_scope(tenant_id) as session:
            session.add(obj)
    """
    session: Session = SessionLocal()
    try:
        if tenant_id is not None:
            apply_tenant_guc(session, tenant_id)
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Database error in session_scope; rolled back")
        raise
    except Exception:
        # Non-DB error inside the scope still requires a clean rollback so we
        # never leave a half-applied transaction open.
        session.rollback()
        logger.exception("Unexpected error in session_scope; rolled back")
        raise
    finally:
        session.close()


__all__ = [
    "engine",
    "SessionLocal",
    "get_session",
    "session_scope",
    "apply_tenant_guc",
]
