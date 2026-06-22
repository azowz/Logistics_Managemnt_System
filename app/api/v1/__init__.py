"""Versioned (``/v1``) API package.

Houses the v1 router assembly (:func:`app.api.v1.router.build_v1_router`) which
mounts the existing business routers under the configured ``api_v1_prefix``
(ADR-005). Kept as a thin package so future API versions (``/v2``) can live as
sibling packages without disturbing v1.
"""

from __future__ import annotations

from app.api.v1.router import build_v1_router

__all__ = ["build_v1_router"]
