"""Pydantic schemas for External Integrations & Webhooks (context #21, Sprint 13).

Security-critical boundary rules baked into the read schemas:

* ``key_hash`` is **never** exposed. Plaintext keys appear only in the one-time
  ``PartnerApiKeyCreatedRead`` (create/rotate response).
* Webhook secrets (``encrypted_secret``) are **never** exposed. The plaintext secret
  appears only in the one-time ``WebhookSubscriptionCreatedRead`` (create/rotate).
* ``tenant_id`` is never accepted from the client on any create/update schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    ApiKeyStatus,
    InboundEventStatus,
    IntegrationPartnerStatus,
    IntegrationPartnerType,
    SigningAlgorithm,
    WebhookDeliveryStatus,
    WebhookSubscriptionStatus,
)
from app.schemas.common import IdModel, TimestampMixin

_PARTNER_SORT = {"created_at", "updated_at", "name", "status", "partner_type"}
_SUB_SORT = {"created_at", "updated_at", "name", "status"}
_DELIVERY_SORT = {"created_at", "updated_at", "status", "external_event_type"}
_INBOUND_SORT = {"created_at", "updated_at", "status", "event_type"}


# --- Partners ---------------------------------------------------------------


class IntegrationPartnerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    partner_type: IntegrationPartnerType
    contact_email: Optional[str] = Field(default=None, max_length=320)
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = Field(default=None, max_length=4000)
    partner_metadata: Optional[dict] = None


class IntegrationPartnerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    partner_type: Optional[IntegrationPartnerType] = None
    contact_email: Optional[str] = Field(default=None, max_length=320)
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = Field(default=None, max_length=4000)
    partner_metadata: Optional[dict] = None


class IntegrationPartnerRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    name: str
    partner_type: IntegrationPartnerType
    status: IntegrationPartnerStatus
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    partner_metadata: Optional[dict] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


# --- API keys ---------------------------------------------------------------


class PartnerApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: Optional[List[str]] = None
    allowed_ips: Optional[List[str]] = None
    expires_at: Optional[datetime] = None

    @field_validator("scopes")
    @classmethod
    def scopes_non_empty(cls, v):
        if v is not None and any(not str(s).strip() for s in v):
            raise ValueError("scopes must not contain blank entries.")
        return v


class PartnerApiKeyRead(IdModel):
    """Safe read view — NEVER includes key_hash or plaintext."""

    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    name: str
    key_prefix: str
    status: ApiKeyStatus
    scopes: Optional[List[str]] = None
    allowed_ips: Optional[List[str]] = None
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PartnerApiKeyCreatedRead(PartnerApiKeyRead):
    """One-time create/rotate response — includes the plaintext key exactly once."""

    api_key: str = Field(description="Plaintext API key. Shown only once; store it securely.")


# --- Webhook subscriptions --------------------------------------------------


class WebhookSubscriptionCreate(BaseModel):
    partner_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    target_url: str = Field(min_length=1, max_length=2048)
    event_types: List[str] = Field(min_length=1)
    max_retries: int = Field(default=5, ge=0, le=20)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    subscription_metadata: Optional[dict] = None


class WebhookSubscriptionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    target_url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    event_types: Optional[List[str]] = Field(default=None, min_length=1)
    max_retries: Optional[int] = Field(default=None, ge=0, le=20)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=120)
    subscription_metadata: Optional[dict] = None


class WebhookSubscriptionRead(IdModel, TimestampMixin):
    """Safe read view — NEVER includes the signing secret."""

    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    name: str
    target_url: str
    event_types: List[str]
    status: WebhookSubscriptionStatus
    signing_algorithm: SigningAlgorithm
    max_retries: int
    timeout_seconds: int
    subscription_metadata: Optional[dict] = None
    # Non-secret secret-encryption metadata (Sprint 14) — the ciphertext/secret is NEVER exposed.
    encryption_provider: Optional[str] = None
    encryption_key_id: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class WebhookSubscriptionCreatedRead(WebhookSubscriptionRead):
    """One-time create/rotate response — includes the signing secret exactly once."""

    secret: str = Field(description="Plaintext signing secret. Shown only once; store it securely.")


# --- Deliveries -------------------------------------------------------------


class WebhookDeliveryRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    subscription_id: uuid.UUID
    partner_id: uuid.UUID
    source_event_id: uuid.UUID
    source_event_type: str
    external_event_type: str
    aggregate_type: Optional[str] = None
    aggregate_id: Optional[uuid.UUID] = None
    status: WebhookDeliveryStatus
    payload: dict
    payload_hash: str
    signature: str
    attempt_count: int
    next_attempt_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class WebhookDeliveryAttemptRead(IdModel):
    tenant_id: uuid.UUID
    delivery_id: uuid.UUID
    attempt_number: int
    status: str
    requested_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    http_status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# --- Inbound ----------------------------------------------------------------


class InboundIntegrationEventCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=128)
    payload: Optional[dict] = None


class InboundIntegrationEventRead(IdModel):
    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    api_key_id: uuid.UUID
    idempotency_key: str
    event_type: str
    payload: Optional[dict] = None
    signature_valid: bool
    status: InboundEventStatus
    received_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# --- List params ------------------------------------------------------------


class _ListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PartnerListParams(_ListParams):
    partner_type: Optional[IntegrationPartnerType] = None
    status: Optional[IntegrationPartnerStatus] = None
    include_deleted: bool = False
    sort_by: str = "created_at"

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _PARTNER_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_PARTNER_SORT))}.")
        return v


class SubscriptionListParams(_ListParams):
    partner_id: Optional[uuid.UUID] = None
    status: Optional[WebhookSubscriptionStatus] = None
    include_deleted: bool = False
    sort_by: str = "created_at"

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _SUB_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_SUB_SORT))}.")
        return v


class DeliveryListParams(_ListParams):
    subscription_id: Optional[uuid.UUID] = None
    partner_id: Optional[uuid.UUID] = None
    status: Optional[WebhookDeliveryStatus] = None
    external_event_type: Optional[str] = Field(default=None, max_length=128)
    sort_by: str = "created_at"

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _DELIVERY_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_DELIVERY_SORT))}.")
        return v


__all__ = [
    "IntegrationPartnerCreate",
    "IntegrationPartnerUpdate",
    "IntegrationPartnerRead",
    "PartnerApiKeyCreate",
    "PartnerApiKeyRead",
    "PartnerApiKeyCreatedRead",
    "WebhookSubscriptionCreate",
    "WebhookSubscriptionUpdate",
    "WebhookSubscriptionRead",
    "WebhookSubscriptionCreatedRead",
    "WebhookDeliveryRead",
    "WebhookDeliveryAttemptRead",
    "InboundIntegrationEventCreate",
    "InboundIntegrationEventRead",
    "PartnerListParams",
    "SubscriptionListParams",
    "DeliveryListParams",
]
