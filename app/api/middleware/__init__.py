"""ASGI/Starlette middleware for the Mesaar API.

Currently exposes :class:`~app.api.middleware.request_context.RequestContextMiddleware`,
which establishes per-request correlation (request id) and tenant scoping and
emits structured access logs.
"""

from __future__ import annotations

from app.api.middleware.request_context import RequestContextMiddleware

__all__ = ["RequestContextMiddleware"]
