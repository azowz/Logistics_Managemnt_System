"""Per-request context middleware: request id, tenant scope, access logging.

For every inbound HTTP request this middleware:

1. Resolves a correlation id from the configured ``request_id_header`` (or mints
   a new time-ordered uuid7 hex when absent) and binds it to the loguru context
   so every log line emitted while handling the request carries ``request_id``.
2. Resolves the tenant from the configured ``tenant_header`` (a UUID); on a
   missing or malformed header the tenant is left ``None`` (platform/unscoped).
   The tenant is pushed onto the :mod:`app.db.tenant` ContextVar for the
   duration of the request and reset afterwards.
3. Times the request and logs ``method path status latency`` at completion.
4. Echoes the correlation id back on the response via ``request_id_header``.

The middleware NEVER swallows downstream exceptions -- the global exception
handlers (installed in :mod:`app.core.exceptions`) own the error response shape.
It does, however, always reset the request-id and tenant ContextVars in a
``finally`` block so context never leaks between requests served on the same
worker task.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.db.tenant import (
    reset_current_tenant,
    reset_current_user_id,
    set_current_tenant,
    set_current_user_id,
)
from app.db.uuidv7 import uuid7
from app.observability.logging import bind_request_id, get_logger, reset_request_id

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from contextvars import Token

    from starlette.middleware.base import RequestResponseEndpoint

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Establish request-id + tenant context and emit access logs."""

    async def dispatch(
        self, request: Request, call_next: "RequestResponseEndpoint"
    ) -> Response:
        settings = get_settings()
        request_id_header = settings.request_id_header
        tenant_header = settings.tenant_header

        # --- Correlation id -------------------------------------------------
        # Honour an inbound id (set by an upstream gateway) so traces correlate
        # end-to-end; otherwise mint a fresh, time-ordered uuid7 hex.
        incoming_id = request.headers.get(request_id_header)
        request_id = incoming_id.strip() if incoming_id and incoming_id.strip() else uuid7().hex

        # --- Tenant resolution ----------------------------------------------
        # A missing header is the common, legitimate case (unauthenticated /
        # platform-scoped routes); a malformed value is logged and treated as
        # absent rather than failing the request here.
        tenant_id = self._resolve_tenant(request, tenant_header)

        rid_token = bind_request_id(request_id)
        tenant_token: "Token[uuid.UUID | None]" = set_current_tenant(tenant_id)
        # The acting user is resolved later from the JWT (auth dependency); bind
        # None now so the per-request context is always cleaned up afterwards.
        user_token: "Token[uuid.UUID | None]" = set_current_user_id(None)

        start = time.perf_counter()
        status_code = 500  # Assume failure until a response is produced.
        try:
            response = await call_next(request)
            status_code = response.status_code
            # Echo the correlation id so clients can quote it in support tickets.
            response.headers[request_id_header] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            # Bind structured fields so JSON sinks index them as first-class keys.
            logger.bind(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=status_code,
                latency_ms=round(elapsed_ms, 2),
                tenant_id=str(tenant_id) if tenant_id is not None else None,
            ).info(
                "{method} {path} -> {status} ({latency_ms} ms)",
                method=request.method,
                path=request.url.path,
                status=status_code,
                latency_ms=round(elapsed_ms, 2),
            )
            # Always restore context, even when the handler raised, so state
            # never bleeds into the next request on this task.
            reset_current_user_id(user_token)
            reset_current_tenant(tenant_token)
            reset_request_id(rid_token)

    @staticmethod
    def _resolve_tenant(request: Request, tenant_header: str) -> uuid.UUID | None:
        """Parse the tenant UUID from ``tenant_header``; ``None`` if absent/bad.

        A malformed tenant header is logged at WARNING and treated as unscoped
        rather than rejected here -- authorization layers downstream decide
        whether an unscoped request is permitted for the target route.
        """

        raw = request.headers.get(tenant_header)
        if not raw or not raw.strip():
            return None
        try:
            return uuid.UUID(raw.strip())
        except ValueError as exc:
            logger.warning(
                "Ignoring malformed tenant header {header}={value!r}: {error}",
                header=tenant_header,
                value=raw,
                error=str(exc),
            )
            return None


__all__ = ["RequestContextMiddleware"]
