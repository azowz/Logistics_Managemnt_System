"""Partner API-key authentication for inbound integration endpoints (Sprint 13).

Separate from user JWT auth. A partner presents ``Authorization: Bearer <api_key>``.
We authenticate the key under **platform scope** (the prefix lookup must span tenants
because the caller's tenant is unknown until the key resolves), then bind the partner's
tenant to the request context so the route's session is RLS-scoped correctly.

The presented plaintext key doubles as the inbound HMAC shared secret, so the route can
verify ``X-Mesaar-Signature`` without a second secret store. Storage stays hash-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.db.session import session_scope
from app.db.tenant import PLATFORM_TENANT_ID, set_current_tenant, set_current_user_id
from app.services.integration_service import ApiKeyAuthContext, IntegrationService

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing partner API key.",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True, slots=True)
class AuthenticatedPartner:
    """Resolved inbound principal: the auth context plus the presented plaintext key."""

    context: ApiKeyAuthContext
    api_key: str


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise _UNAUTHORIZED
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise _UNAUTHORIZED
    return parts[1].strip()


def get_current_api_key_partner(
    authorization: str | None = Header(default=None),
) -> AuthenticatedPartner:
    """FastAPI dependency: authenticate a partner API key and bind its tenant context.

    Authentication (and the ``last_used_at`` stamp) runs in its own platform-scoped
    transaction; on success the partner's tenant is bound so the request's own session
    is scoped to that tenant via RLS.
    """
    api_key = _extract_bearer(authorization)
    with session_scope(PLATFORM_TENANT_ID) as session:
        context = IntegrationService(session).authenticate_api_key(api_key)
    if context is None:
        raise _UNAUTHORIZED
    # Bind the partner's tenant for the remainder of the request (route session is
    # RLS-scoped to it); API keys are service principals, so there is no acting user.
    set_current_tenant(context.tenant_id)
    set_current_user_id(None)
    return AuthenticatedPartner(context=context, api_key=api_key)


__all__ = ["AuthenticatedPartner", "get_current_api_key_partner", "get_current_api_key_partner"]
