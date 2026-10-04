"""Partner API-key authentication + authorization for inbound integration endpoints.

Separate from user JWT auth. A partner presents ``Authorization: Bearer <api_key>``.
We authenticate the key under **platform scope** (the prefix lookup must span tenants
because the caller's tenant is unknown until the key resolves), then bind the partner's
tenant to the request context so the route's session is RLS-scoped correctly.

Sprint 14 adds enforcement of the two fields Sprint 13 only persisted:
* **allowed_ips** — if set on the key, the request source IP must match (exact or CIDR);
  empty/null allows any source. Uses ``request.client.host`` (``X-Forwarded-For`` is only
  honoured behind a trusted proxy, which is a deployment concern — not trusted by default).
* **scopes** — :func:`require_api_key_scopes` gates an endpoint on required scopes (403).

The presented plaintext key doubles as the inbound HMAC shared secret, so the route can
verify ``X-Mesaar-Signature`` without a second secret store. Storage stays hash-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status

from app.db.session import session_scope
from app.db.tenant import PLATFORM_TENANT_ID, set_current_tenant, set_current_user_id
from app.integrations.policies import (
    ALL_SCOPES,
    SCOPE_DELIVERIES_READ,
    SCOPE_INBOUND_WRITE,
    SCOPE_WEBHOOKS_READ,
    SCOPE_WEBHOOKS_WRITE,
    ip_allowed,
)
from app.services.integration_service import ApiKeyAuthContext, IntegrationService

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing partner API key.",
    headers={"WWW-Authenticate": "Bearer"},
)
_IP_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Source IP is not allowed for this API key.",
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


def _client_ip(request: Request | None) -> str | None:
    """Best-effort source IP. Uses the socket peer; X-Forwarded-For is NOT trusted here
    (honour it only behind a configured trusted proxy — a deployment concern)."""
    if request is None or request.client is None:
        return None
    return request.client.host


def get_current_api_key_partner(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedPartner:
    """FastAPI dependency: authenticate a partner API key, enforce allowed-IP, bind tenant.

    Authentication (and the ``last_used_at`` stamp) runs in its own platform-scoped
    transaction; on success the partner's tenant is bound so the request's own session is
    scoped to that tenant via RLS. Allowed-IP enforcement runs after a successful auth.
    """
    api_key = _extract_bearer(authorization)
    with session_scope(PLATFORM_TENANT_ID) as session:
        context = IntegrationService(session).authenticate_api_key(api_key)
    if context is None:
        raise _UNAUTHORIZED
    # Enforce allowed-IP (empty/None allows any). Distinct 403 by design — the key is
    # already authenticated; this is an authorization decision, not existence disclosure.
    if not ip_allowed(_client_ip(request), context.allowed_ips):
        raise _IP_FORBIDDEN
    # Bind the partner's tenant for the remainder of the request (route session is
    # RLS-scoped to it); API keys are service principals, so there is no acting user.
    set_current_tenant(context.tenant_id)
    set_current_user_id(None)
    return AuthenticatedPartner(context=context, api_key=api_key)


def require_api_key_scopes(*required: str):
    """Dependency factory: require the authenticated key to hold all ``required`` scopes.

    Missing scope → 403. Revoked/expired/suspended keys are already rejected upstream by
    :func:`get_current_api_key_partner` (401), so scope checks only run for a valid key.
    """

    def dependency(
        principal: AuthenticatedPartner = Depends(get_current_api_key_partner),
    ) -> AuthenticatedPartner:
        held = set(principal.context.scopes or ())
        if not set(required).issubset(held):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key is missing required scope(s): {', '.join(sorted(required))}.",
            )
        return principal

    return dependency


__all__ = [
    "AuthenticatedPartner",
    "get_current_api_key_partner",
    "require_api_key_scopes",
    "SCOPE_INBOUND_WRITE",
    "SCOPE_DELIVERIES_READ",
    "SCOPE_WEBHOOKS_READ",
    "SCOPE_WEBHOOKS_WRITE",
    "ALL_SCOPES",
]
