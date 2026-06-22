"""Application-wide constants for the Mesaar logistics backend.

This module centralizes small, stable, non-secret values that several layers of
the application reference: the platform/nil tenant id, default pagination
bounds, and default header names. Keeping these here avoids magic literals
scattered across the codebase and gives a single, import-safe source of truth.

Nothing in this module performs I/O, reads the environment, or imports from
heavyweight subpackages, so it is safe to import from anywhere (including very
early during application bootstrap) without risking circular imports.
"""

from __future__ import annotations

import uuid
from typing import Final

# ---------------------------------------------------------------------------
# Tenancy.
# ---------------------------------------------------------------------------
# The nil UUID identifies the "platform" tenant: rows owned by the platform
# itself rather than by any customer tenant. The canonical definition lives in
# ``app.db.tenant``; we re-declare the literal here (instead of importing it) so
# this constants module stays dependency-free and import-cycle-safe. The value
# MUST stay in sync with ``app.db.tenant.PLATFORM_TENANT_ID``.
PLATFORM_TENANT_ID: Final[uuid.UUID] = uuid.UUID("00000000-0000-0000-0000-000000000000")

# ---------------------------------------------------------------------------
# Pagination.
# ---------------------------------------------------------------------------
# Defaults and bounds shared by ``app.common.pagination.PageParams``. Centralized
# so API docs, validators and clients agree on the same numbers.
DEFAULT_PAGE: Final[int] = 1
MIN_PAGE: Final[int] = 1

DEFAULT_PAGE_SIZE: Final[int] = 50
MIN_PAGE_SIZE: Final[int] = 1
MAX_PAGE_SIZE: Final[int] = 200

# ---------------------------------------------------------------------------
# HTTP header name defaults.
# ---------------------------------------------------------------------------
# These mirror the defaults on :class:`app.core.config.Settings`. They exist so
# code paths that do not (or cannot) load settings still have a sane fallback,
# and so tests can reference the canonical names without a settings instance.
DEFAULT_REQUEST_ID_HEADER: Final[str] = "X-Request-ID"
DEFAULT_TENANT_HEADER: Final[str] = "X-Tenant-ID"

# ---------------------------------------------------------------------------
# Authentication.
# ---------------------------------------------------------------------------
# OAuth2 bearer token type, returned in token responses and the Authorization
# scheme. Lower-cased per RFC 6750 conventions used across the codebase.
BEARER_TOKEN_TYPE: Final[str] = "bearer"

__all__ = [
    "PLATFORM_TENANT_ID",
    "DEFAULT_PAGE",
    "MIN_PAGE",
    "DEFAULT_PAGE_SIZE",
    "MIN_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "DEFAULT_REQUEST_ID_HEADER",
    "DEFAULT_TENANT_HEADER",
    "BEARER_TOKEN_TYPE",
]
