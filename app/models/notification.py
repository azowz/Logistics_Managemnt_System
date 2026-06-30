"""Notifications & Communications domain models (context #19, Sprint 10).

Turns operational domain events into tenant-aware, auditable communication:
notification templates, notifications, and per-channel delivery attempts.
Notifications **consume** events from other contexts; they never mutate source
aggregates. Recipient targets are referenced by id/contact only.

All tables are tenant-scoped (RLS), soft-deletable + auditable, optimistic-locked
(delivery attempts are immutable children — timestamped only).
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
    DeliveryAttemptStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)


def _enum_values(enum_cls) -> list[str]:
    return [member.value for member in enum_cls]


class NotificationTemplate(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_code", name="uq_notification_templates_tenant_id_template_code"),
        CheckConstraint(
            "channel IN ('in_app', 'email', 'sms', 'push', 'webhook')", name="channel"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    template_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, index=True,
    )
    subject_template: Mapped[Optional[str]] = mapped_column(String(512))
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    event_type: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    variables_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Notification(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # Domain-level idempotency: one notification per (tenant, event, channel, recipient).
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_notifications_tenant_id_idempotency_key"),
        CheckConstraint(
            "status IN ('pending', 'queued', 'sent', 'failed', 'cancelled', 'read')", name="status"
        ),
        CheckConstraint(
            "channel IN ('in_app', 'email', 'sms', 'push', 'webhook')", name="channel"
        ),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="priority"),
        CheckConstraint("retry_count >= 0", name="retry_count_non_negative"),
        CheckConstraint(
            "recipient_user_id IS NOT NULL OR recipient_email IS NOT NULL OR recipient_phone IS NOT NULL",
            name="recipient_target_present",
        ),
        CheckConstraint(
            "recipient_email IS NULL OR recipient_email ~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
            name="recipient_email_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_templates.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    aggregate_type: Mapped[Optional[str]] = mapped_column(String(64))
    aggregate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    recipient_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_email: Mapped[Optional[str]] = mapped_column(String(320))
    recipient_phone: Mapped[Optional[str]] = mapped_column(String(32))
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, index=True,
    )
    subject: Mapped[Optional[str]] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, default=NotificationStatus.PENDING, server_default="pending", index=True,
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        SAEnum(NotificationPriority, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False, default=NotificationPriority.NORMAL, server_default="normal",
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(String(1024))
    notification_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class NotificationDeliveryAttempt(TimestampMixin, Base):
    """Immutable record of one channel delivery attempt for a notification."""

    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('in_app', 'email', 'sms', 'push', 'webhook')", name="channel"
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'skipped', 'retrying')", name="status"
        ),
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, native_enum=False, length=16, values_callable=_enum_values), nullable=False
    )
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[DeliveryAttemptStatus] = mapped_column(
        SAEnum(DeliveryAttemptStatus, native_enum=False, length=16, values_callable=_enum_values), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255))
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(String(1024))
    response_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
