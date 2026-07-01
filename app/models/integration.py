"""External Integrations & Webhooks domain models (context #21, Sprint 13).

A partner-facing integration surface. Partners authenticate with tenant-scoped API
keys, subscribe to selected (externally-named, sanitized) domain events, and receive
signed outbound webhooks; they may also POST audited inbound events. This context is a
**consumer** — it never mutates source aggregates. Secrets are never stored in the
clear that can be avoided: API keys are bcrypt-hashed; outbound webhook secrets are
encrypted at rest (they must be recoverable to sign). See app/integrations/crypto.py.

All tables are tenant-scoped (RLS). Partners/keys/subscriptions are auditable +
soft-deletable + optimistic-locked; deliveries/attempts/inbound rows are largely
append-only operational records.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    ApiKeyStatus,
    InboundEventStatus,
    IntegrationPartnerStatus,
    IntegrationPartnerType,
    SigningAlgorithm,
    WebhookAttemptStatus,
    WebhookDeliveryStatus,
    WebhookSubscriptionStatus,
)


def _enum_values(enum_cls) -> list[str]:
    return [member.value for member in enum_cls]


class IntegrationPartner(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "integration_partners"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_integration_partners_tenant_id_name"),
        CheckConstraint(
            "partner_type IN ('customer', 'carrier', 'vendor', 'government', 'internal', 'other')",
            name="partner_type",
        ),
        CheckConstraint("status IN ('active', 'inactive', 'suspended')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    partner_type: Mapped[IntegrationPartnerType] = mapped_column(
        SAEnum(IntegrationPartnerType, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, index=True,
    )
    status: Mapped[IntegrationPartnerStatus] = mapped_column(
        SAEnum(IntegrationPartnerStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, server_default=IntegrationPartnerStatus.ACTIVE.value, index=True,
    )
    contact_email: Mapped[Optional[str]] = mapped_column(String(320))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(32))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    partner_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class PartnerApiKey(TimestampMixin, Base):
    """A tenant+partner-scoped API credential. Only the bcrypt hash is stored."""

    __tablename__ = "partner_api_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_prefix", name="uq_partner_api_keys_tenant_id_key_prefix"),
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ApiKeyStatus] = mapped_column(
        SAEnum(ApiKeyStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, server_default=ApiKeyStatus.ACTIVE.value, index=True,
    )
    scopes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    allowed_ips: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)


class WebhookSubscription(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "webhook_subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "partner_id", "name", name="uq_webhook_subscriptions_tenant_partner_name"),
        CheckConstraint("status IN ('active', 'inactive', 'suspended')", name="status"),
        CheckConstraint("max_retries >= 0", name="max_retries_non_negative"),
        CheckConstraint("timeout_seconds > 0", name="timeout_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # External event names this subscription receives (e.g. ["shipment.delivered"]).
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[WebhookSubscriptionStatus] = mapped_column(
        SAEnum(WebhookSubscriptionStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, server_default=WebhookSubscriptionStatus.ACTIVE.value, index=True,
    )
    # Encrypted signing secret (never returned by read APIs). Sprint 14: the encryption
    # provider + key id are recorded so a KMS migration / key rotation is auditable.
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_provider: Mapped[Optional[str]] = mapped_column(String(32))
    encryption_key_id: Mapped[Optional[str]] = mapped_column(String(64))
    signing_algorithm: Mapped[SigningAlgorithm] = mapped_column(
        SAEnum(SigningAlgorithm, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, server_default=SigningAlgorithm.HMAC_SHA256.value,
    )
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    subscription_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class WebhookDelivery(TimestampMixin, Base):
    """One sanitized, signed outbound webhook queued for a subscription.

    Idempotent per ``(tenant_id, subscription_id, source_event_id)`` so replayed source
    events never create duplicate deliveries.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "subscription_id", "source_event_id",
            name="uq_webhook_deliveries_tenant_subscription_source_event",
        ),
        CheckConstraint(
            "status IN ('pending', 'delivering', 'delivered', 'failed', 'cancelled', 'skipped')",
            name="status",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    external_event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    aggregate_type: Mapped[Optional[str]] = mapped_column(String(64))
    aggregate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        SAEnum(WebhookDeliveryStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, server_default=WebhookDeliveryStatus.PENDING.value, index=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(1024))


class WebhookDeliveryAttempt(TimestampMixin, Base):
    """Immutable record of a single delivery attempt (append-only)."""

    __tablename__ = "webhook_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("delivery_id", "attempt_number", name="uq_webhook_delivery_attempts_delivery_attempt"),
        CheckConstraint("status IN ('succeeded', 'failed', 'skipped')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[WebhookAttemptStatus] = mapped_column(
        SAEnum(WebhookAttemptStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
    )
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer)
    response_body: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(String(1024))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)


class InboundIntegrationEvent(TimestampMixin, Base):
    """An audited inbound event POSTed by a partner. Idempotent per api-key + key."""

    __tablename__ = "inbound_integration_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "api_key_id", "idempotency_key",
            name="uq_inbound_integration_events_tenant_apikey_idempotency",
        ),
        CheckConstraint(
            "status IN ('received', 'accepted', 'rejected', 'processed', 'failed')", name="status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_api_keys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[InboundEventStatus] = mapped_column(
        SAEnum(InboundEventStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, server_default=InboundEventStatus.RECEIVED.value, index=True,
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(512))


__all__ = [
    "IntegrationPartner",
    "PartnerApiKey",
    "WebhookSubscription",
    "WebhookDelivery",
    "WebhookDeliveryAttempt",
    "InboundIntegrationEvent",
]
