"""Pydantic schemas for the Notifications & Communications domain (Sprint 10)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    DeliveryAttemptStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from app.schemas.common import IdModel, TimestampMixin

_TEMPLATE_SORT = frozenset({"template_code", "name", "channel", "language", "created_at", "updated_at"})
_NOTIFICATION_SORT = frozenset({"status", "channel", "priority", "scheduled_at", "created_at", "updated_at"})

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s()]{4,30}$")
_LANG_RE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")


def _email(v: Optional[str]) -> Optional[str]:
    if v is not None and not _EMAIL_RE.match(v):
        raise ValueError("recipient_email is not a valid email address.")
    return v


def _phone(v: Optional[str]) -> Optional[str]:
    if v is not None and not _PHONE_RE.match(v):
        raise ValueError("recipient_phone is not a valid phone number.")
    return v


def _lang(v: Optional[str]) -> Optional[str]:
    if v is not None and not _LANG_RE.match(v):
        raise ValueError("language must be an ISO-639 code (e.g. 'en' or 'en-US').")
    return v


# --- Template --------------------------------------------------------------


class NotificationTemplateCreate(BaseModel):
    template_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    channel: NotificationChannel
    subject_template: Optional[str] = Field(default=None, max_length=512)
    body_template: str = Field(min_length=1)
    language: str = Field(default="en", max_length=8)
    event_type: Optional[str] = Field(default=None, max_length=128)
    variables_schema: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("language")
    @classmethod
    def lang(cls, v):
        return _lang(v)


class NotificationTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    subject_template: Optional[str] = Field(default=None, max_length=512)
    body_template: Optional[str] = Field(default=None, min_length=1)
    language: Optional[str] = Field(default=None, max_length=8)
    event_type: Optional[str] = Field(default=None, max_length=128)
    variables_schema: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("language")
    @classmethod
    def lang(cls, v):
        return _lang(v)

    @model_validator(mode="after")
    def at_least_one(self) -> "NotificationTemplateUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class NotificationTemplateRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    template_code: str
    name: str
    channel: NotificationChannel
    subject_template: Optional[str] = None
    body_template: str
    language: str
    active: bool
    event_type: Optional[str] = None
    variables_schema: Optional[dict] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class NotificationTemplateListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    channel: Optional[NotificationChannel] = None
    event_type: Optional[str] = Field(default=None, max_length=128)
    active: Optional[bool] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _TEMPLATE_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_TEMPLATE_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


# --- Notification ----------------------------------------------------------


class NotificationCreate(BaseModel):
    channel: NotificationChannel
    recipient_user_id: Optional[uuid.UUID] = None
    recipient_email: Optional[str] = Field(default=None, max_length=320)
    recipient_phone: Optional[str] = Field(default=None, max_length=32)
    subject: Optional[str] = Field(default=None, max_length=512)
    body: Optional[str] = None
    event_type: Optional[str] = Field(default=None, max_length=128)
    priority: NotificationPriority = NotificationPriority.NORMAL
    scheduled_at: Optional[datetime] = None
    variables: Optional[dict] = None
    notification_metadata: Optional[dict] = Field(default=None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("recipient_email")
    @classmethod
    def email(cls, v):
        return _email(v)

    @field_validator("recipient_phone")
    @classmethod
    def phone(cls, v):
        return _phone(v)

    @field_validator("scheduled_at")
    @classmethod
    def tz(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware (UTC).")
        return v

    @model_validator(mode="after")
    def recipient_and_body(self) -> "NotificationCreate":
        if not (self.recipient_user_id or self.recipient_email or self.recipient_phone):
            raise ValueError("At least one recipient target (user_id, email, or phone) is required.")
        if not self.body and not self.event_type:
            raise ValueError("Provide a body, or an event_type that resolves to a template.")
        return self


class NotificationRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    template_id: Optional[uuid.UUID] = None
    idempotency_key: str
    event_id: Optional[uuid.UUID] = None
    event_type: Optional[str] = None
    aggregate_type: Optional[str] = None
    aggregate_id: Optional[uuid.UUID] = None
    recipient_user_id: Optional[uuid.UUID] = None
    recipient_email: Optional[str] = None
    recipient_phone: Optional[str] = None
    channel: NotificationChannel
    subject: Optional[str] = None
    body: str
    status: NotificationStatus
    priority: NotificationPriority
    scheduled_at: Optional[datetime] = None
    queued_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    retry_count: int
    last_error: Optional[str] = None
    notification_metadata: Optional[dict] = Field(default=None, serialization_alias="metadata")
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NotificationListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[NotificationStatus] = None
    channel: Optional[NotificationChannel] = None
    recipient_user_id: Optional[uuid.UUID] = None
    event_type: Optional[str] = Field(default=None, max_length=128)
    unread_only: bool = False
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _NOTIFICATION_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_NOTIFICATION_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class NotificationCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


class NotificationDeliveryAttemptRead(IdModel):
    tenant_id: uuid.UUID
    notification_id: uuid.UUID
    channel: NotificationChannel
    provider: Optional[str] = None
    status: DeliveryAttemptStatus
    attempt_number: int
    requested_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    response_payload: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)
