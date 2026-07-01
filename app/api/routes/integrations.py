"""External Integrations & Webhooks API routes (context #21, Sprint 13).

Management endpoints use user JWT + RBAC (ADMIN/MANAGER; ADMIN for secret revoke/rotate).
The single inbound endpoint uses partner API-key auth. Literal paths precede dynamic
ones. Response schemas never expose ``key_hash`` or webhook secrets; plaintext key /
secret appear only in one-time create/rotate responses.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_session
from app.integrations import crypto
from app.integrations.auth import AuthenticatedPartner, get_current_api_key_partner
from app.integrations.policies import get_inbound_rate_limiter
from app.models.enums import UserRole
from app.schemas.integration import (
    DeliveryListParams,
    InboundIntegrationEventCreate,
    InboundIntegrationEventRead,
    IntegrationPartnerCreate,
    IntegrationPartnerRead,
    IntegrationPartnerUpdate,
    PartnerApiKeyCreate,
    PartnerApiKeyCreatedRead,
    PartnerApiKeyRead,
    PartnerListParams,
    SubscriptionListParams,
    WebhookDeliveryAttemptRead,
    WebhookDeliveryRead,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreatedRead,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from app.services.exceptions import ValidationError
from app.services.integration_service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])

_MANAGE = (UserRole.ADMIN, UserRole.MANAGER)
_ADMIN = (UserRole.ADMIN,)


# ===================== Partners (literal before dynamic) =====================


@router.post("/partners", response_model=IntegrationPartnerRead, status_code=status.HTTP_201_CREATED,
             summary="Create an integration partner.")
def create_partner(payload: IntegrationPartnerCreate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_MANAGE))) -> IntegrationPartnerRead:
    partner = IntegrationService(session).create_partner(**payload.model_dump())
    return IntegrationPartnerRead.model_validate(partner)


@router.get("/partners", response_model=list[IntegrationPartnerRead], summary="List integration partners.")
def list_partners(params: PartnerListParams = Depends(), session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_MANAGE))) -> list[IntegrationPartnerRead]:
    items, _ = IntegrationService(session).list_partners(
        q=params.q, partner_type=params.partner_type, status=params.status,
        include_deleted=params.include_deleted, sort_by=params.sort_by, sort_dir=params.sort_dir,
        limit=params.size, offset=params.offset,
    )
    return [IntegrationPartnerRead.model_validate(p) for p in items]


@router.get("/partners/search", response_model=list[IntegrationPartnerRead], summary="Search integration partners.")
def search_partners(params: PartnerListParams = Depends(), session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_MANAGE))) -> list[IntegrationPartnerRead]:
    return list_partners(params=params, session=session, current_user=current_user)


@router.get("/partners/{partner_id}", response_model=IntegrationPartnerRead, summary="Get an integration partner.")
def get_partner(partner_id: uuid.UUID, session: Session = Depends(get_session),
                current_user=Depends(require_roles(*_MANAGE))) -> IntegrationPartnerRead:
    return IntegrationPartnerRead.model_validate(IntegrationService(session).get_partner(partner_id))


@router.patch("/partners/{partner_id}", response_model=IntegrationPartnerRead, summary="Update an integration partner.")
def update_partner(partner_id: uuid.UUID, payload: IntegrationPartnerUpdate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_MANAGE))) -> IntegrationPartnerRead:
    partner = IntegrationService(session).update_partner(partner_id, **payload.model_dump(exclude_unset=True))
    return IntegrationPartnerRead.model_validate(partner)


@router.post("/partners/{partner_id}/activate", response_model=IntegrationPartnerRead, summary="Activate a partner.")
def activate_partner(partner_id: uuid.UUID, session: Session = Depends(get_session),
                     current_user=Depends(require_roles(*_MANAGE))) -> IntegrationPartnerRead:
    return IntegrationPartnerRead.model_validate(IntegrationService(session).activate_partner(partner_id))


@router.post("/partners/{partner_id}/suspend", response_model=IntegrationPartnerRead, summary="Suspend a partner.")
def suspend_partner(partner_id: uuid.UUID, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_MANAGE))) -> IntegrationPartnerRead:
    return IntegrationPartnerRead.model_validate(IntegrationService(session).suspend_partner(partner_id))


@router.delete("/partners/{partner_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft-delete a partner.")
def delete_partner(partner_id: uuid.UUID, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_MANAGE))):
    IntegrationService(session).delete_partner(partner_id)


# ===================== API keys =====================


@router.post("/partners/{partner_id}/api-keys", response_model=PartnerApiKeyCreatedRead,
             status_code=status.HTTP_201_CREATED, summary="Create a partner API key (plaintext shown once).")
def create_api_key(partner_id: uuid.UUID, payload: PartnerApiKeyCreate, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_MANAGE))) -> PartnerApiKeyCreatedRead:
    key, plaintext = IntegrationService(session).create_api_key(partner_id, **payload.model_dump())
    data = PartnerApiKeyRead.model_validate(key).model_dump()
    return PartnerApiKeyCreatedRead(**data, api_key=plaintext)


@router.get("/partners/{partner_id}/api-keys", response_model=list[PartnerApiKeyRead],
            summary="List a partner's API keys (no hash/plaintext).")
def list_api_keys(partner_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_MANAGE))) -> list[PartnerApiKeyRead]:
    return [PartnerApiKeyRead.model_validate(k) for k in IntegrationService(session).list_api_keys(partner_id)]


@router.post("/api-keys/{api_key_id}/revoke", response_model=PartnerApiKeyRead, summary="Revoke an API key (ADMIN).")
def revoke_api_key(api_key_id: uuid.UUID, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_ADMIN))) -> PartnerApiKeyRead:
    return PartnerApiKeyRead.model_validate(IntegrationService(session).revoke_api_key(api_key_id))


@router.post("/api-keys/{api_key_id}/rotate", response_model=PartnerApiKeyCreatedRead,
             summary="Rotate an API key (ADMIN; new plaintext shown once).")
def rotate_api_key(api_key_id: uuid.UUID, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_ADMIN))) -> PartnerApiKeyCreatedRead:
    key, plaintext = IntegrationService(session).rotate_api_key(api_key_id)
    data = PartnerApiKeyRead.model_validate(key).model_dump()
    return PartnerApiKeyCreatedRead(**data, api_key=plaintext)


# ===================== Webhook subscriptions =====================


@router.post("/webhooks/subscriptions", response_model=WebhookSubscriptionCreatedRead,
             status_code=status.HTTP_201_CREATED, summary="Create a webhook subscription (secret shown once).")
def create_subscription(payload: WebhookSubscriptionCreate, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_MANAGE))) -> WebhookSubscriptionCreatedRead:
    sub, secret = IntegrationService(session).create_subscription(
        payload.partner_id, name=payload.name, target_url=payload.target_url, event_types=payload.event_types,
        max_retries=payload.max_retries, timeout_seconds=payload.timeout_seconds,
        subscription_metadata=payload.subscription_metadata,
    )
    data = WebhookSubscriptionRead.model_validate(sub).model_dump()
    return WebhookSubscriptionCreatedRead(**data, secret=secret)


@router.get("/webhooks/subscriptions", response_model=list[WebhookSubscriptionRead],
            summary="List webhook subscriptions.")
def list_subscriptions(params: SubscriptionListParams = Depends(), session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_MANAGE))) -> list[WebhookSubscriptionRead]:
    items, _ = IntegrationService(session).list_subscriptions(
        q=params.q, partner_id=params.partner_id, status=params.status, include_deleted=params.include_deleted,
        sort_by=params.sort_by, sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
    )
    return [WebhookSubscriptionRead.model_validate(s) for s in items]


@router.get("/webhooks/subscriptions/search", response_model=list[WebhookSubscriptionRead],
            summary="Search webhook subscriptions.")
def search_subscriptions(params: SubscriptionListParams = Depends(), session: Session = Depends(get_session),
                         current_user=Depends(require_roles(*_MANAGE))) -> list[WebhookSubscriptionRead]:
    return list_subscriptions(params=params, session=session, current_user=current_user)


@router.get("/webhooks/subscriptions/{subscription_id}", response_model=WebhookSubscriptionRead,
            summary="Get a webhook subscription.")
def get_subscription(subscription_id: uuid.UUID, session: Session = Depends(get_session),
                     current_user=Depends(require_roles(*_MANAGE))) -> WebhookSubscriptionRead:
    return WebhookSubscriptionRead.model_validate(IntegrationService(session).get_subscription(subscription_id))


@router.patch("/webhooks/subscriptions/{subscription_id}", response_model=WebhookSubscriptionRead,
              summary="Update a webhook subscription.")
def update_subscription(subscription_id: uuid.UUID, payload: WebhookSubscriptionUpdate,
                        session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_MANAGE))) -> WebhookSubscriptionRead:
    sub = IntegrationService(session).update_subscription(subscription_id, **payload.model_dump(exclude_unset=True))
    return WebhookSubscriptionRead.model_validate(sub)


@router.post("/webhooks/subscriptions/{subscription_id}/activate", response_model=WebhookSubscriptionRead,
             summary="Activate a webhook subscription.")
def activate_subscription(subscription_id: uuid.UUID, session: Session = Depends(get_session),
                          current_user=Depends(require_roles(*_MANAGE))) -> WebhookSubscriptionRead:
    return WebhookSubscriptionRead.model_validate(IntegrationService(session).activate_subscription(subscription_id))


@router.post("/webhooks/subscriptions/{subscription_id}/deactivate", response_model=WebhookSubscriptionRead,
             summary="Deactivate a webhook subscription.")
def deactivate_subscription(subscription_id: uuid.UUID, session: Session = Depends(get_session),
                            current_user=Depends(require_roles(*_MANAGE))) -> WebhookSubscriptionRead:
    return WebhookSubscriptionRead.model_validate(IntegrationService(session).deactivate_subscription(subscription_id))


@router.post("/webhooks/subscriptions/{subscription_id}/rotate-secret", response_model=WebhookSubscriptionCreatedRead,
             summary="Rotate a webhook signing secret (ADMIN; new secret shown once).")
def rotate_subscription_secret(subscription_id: uuid.UUID, session: Session = Depends(get_session),
                               current_user=Depends(require_roles(*_ADMIN))) -> WebhookSubscriptionCreatedRead:
    sub, secret = IntegrationService(session).rotate_subscription_secret(subscription_id)
    data = WebhookSubscriptionRead.model_validate(sub).model_dump()
    return WebhookSubscriptionCreatedRead(**data, secret=secret)


@router.delete("/webhooks/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Soft-delete a webhook subscription.")
def delete_subscription(subscription_id: uuid.UUID, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_MANAGE))):
    IntegrationService(session).delete_subscription(subscription_id)


# ===================== Deliveries =====================


@router.get("/webhooks/deliveries", response_model=list[WebhookDeliveryRead], summary="List webhook deliveries.")
def list_deliveries(params: DeliveryListParams = Depends(), session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_MANAGE))) -> list[WebhookDeliveryRead]:
    items, _ = IntegrationService(session).list_deliveries(
        subscription_id=params.subscription_id, partner_id=params.partner_id, status=params.status,
        external_event_type=params.external_event_type, sort_by=params.sort_by, sort_dir=params.sort_dir,
        limit=params.size, offset=params.offset,
    )
    return [WebhookDeliveryRead.model_validate(d) for d in items]


@router.get("/webhooks/deliveries/{delivery_id}", response_model=WebhookDeliveryRead, summary="Get a webhook delivery.")
def get_delivery(delivery_id: uuid.UUID, session: Session = Depends(get_session),
                 current_user=Depends(require_roles(*_MANAGE))) -> WebhookDeliveryRead:
    return WebhookDeliveryRead.model_validate(IntegrationService(session).get_delivery(delivery_id))


@router.post("/webhooks/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryRead,
             summary="Retry a failed webhook delivery.")
def retry_delivery(delivery_id: uuid.UUID, session: Session = Depends(get_session),
                   current_user=Depends(require_roles(*_MANAGE))) -> WebhookDeliveryRead:
    return WebhookDeliveryRead.model_validate(IntegrationService(session).retry_delivery(delivery_id))


@router.post("/webhooks/deliveries/{delivery_id}/cancel", response_model=WebhookDeliveryRead,
             summary="Cancel a pending/failed webhook delivery.")
def cancel_delivery(delivery_id: uuid.UUID, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_MANAGE))) -> WebhookDeliveryRead:
    return WebhookDeliveryRead.model_validate(IntegrationService(session).cancel_delivery(delivery_id))


@router.get("/webhooks/deliveries/{delivery_id}/attempts", response_model=list[WebhookDeliveryAttemptRead],
            summary="List a delivery's attempts.")
def list_delivery_attempts(delivery_id: uuid.UUID, session: Session = Depends(get_session),
                           current_user=Depends(require_roles(*_MANAGE))) -> list[WebhookDeliveryAttemptRead]:
    return [WebhookDeliveryAttemptRead.model_validate(a)
            for a in IntegrationService(session).list_delivery_attempts(delivery_id)]


# ===================== Inbound (partner API-key auth) =====================


@router.post("/inbound/events", response_model=InboundIntegrationEventRead, status_code=status.HTTP_201_CREATED,
             summary="Receive an authenticated, signed inbound integration event.")
async def receive_inbound_event(
    request: Request,
    principal: AuthenticatedPartner = Depends(get_current_api_key_partner),
    x_mesaar_signature: Optional[str] = Header(default=None),
    x_mesaar_timestamp: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> InboundIntegrationEventRead:
    # M2: rate-limit per (tenant, api_key) AFTER successful API-key authentication.
    # tenant/api_key come from the authenticated key context, never from the client.
    decision = get_inbound_rate_limiter().check(
        f"{principal.context.tenant_id}:{principal.context.api_key_id}", now=time.time())
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this API key.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    raw = (await request.body()).decode("utf-8")
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise ValidationError("Request body must be valid JSON.")
    if not isinstance(parsed, dict):
        raise ValidationError("Request body must be a JSON object.")
    try:
        payload = InboundIntegrationEventCreate(**parsed)
    except PydanticValidationError as exc:
        raise ValidationError(f"Invalid inbound event body: {exc.errors()[0]['msg']}")

    # Verify the HMAC signature using the presented plaintext key as the shared secret.
    signature_valid = bool(
        x_mesaar_signature
        and crypto.verify_signature(principal.api_key, raw, x_mesaar_signature, timestamp=x_mesaar_timestamp)
    )
    row = IntegrationService(session).receive_inbound_event(
        partner_id=principal.context.partner_id, api_key_id=principal.context.api_key_id,
        idempotency_key=payload.idempotency_key, event_type=payload.event_type,
        payload=payload.payload, signature_valid=signature_valid,
    )
    return InboundIntegrationEventRead.model_validate(row)


__all__ = ["router"]
