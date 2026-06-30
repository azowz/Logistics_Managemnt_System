"""Repositories for the Notifications & Communications domain (Sprint 10).

Constructor takes ``Session``; never commit/flush/rollback; no FastAPI; no events;
tenant-scoped reads via RLS; soft-delete aware.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import NotificationStatus
from app.models.notification import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationTemplate,
)
from app.repositories.errors import NotFoundError

# Statuses that a relay/worker can pick up for delivery.
_PENDING_STATES = (NotificationStatus.PENDING, NotificationStatus.QUEUED)


def _coerce_uuid(value: Union[str, uuid.UUID]) -> Optional[uuid.UUID]:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class _BaseRepo:
    model = None

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **data):
        obj = self.model(**data)
        self._session.add(obj)
        return obj

    def update(self, obj, **data):
        for field, value in data.items():
            if value is not None:
                setattr(obj, field, value)
        return obj

    def get_by_id(self, obj_id):
        oid = _coerce_uuid(obj_id)
        if oid is None:
            return None
        return self._session.get(self.model, oid)

    def get_by_id_or_raise(self, obj_id):
        obj = self.get_by_id(obj_id)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} {obj_id} not found.")
        return obj

    def soft_delete(self, obj, *, deleted_by=None):
        obj.soft_delete()
        obj.deleted_by = deleted_by
        return obj

    def restore(self, obj):
        obj.restore()
        obj.deleted_by = None
        return obj


class NotificationTemplateRepository(_BaseRepo):
    model = NotificationTemplate

    def get_by_code(self, template_code: str, *, include_deleted: bool = False) -> Optional[NotificationTemplate]:
        stmt = select(NotificationTemplate).where(NotificationTemplate.template_code == template_code)
        if not include_deleted:
            stmt = stmt.where(NotificationTemplate.deleted_at.is_(None))
        return self._session.scalars(stmt).first()

    def get_active_for_event(self, event_type: str, channel) -> Optional[NotificationTemplate]:
        """Return the active template for an (event_type, channel), if any."""
        stmt = select(NotificationTemplate).where(
            NotificationTemplate.event_type == event_type,
            NotificationTemplate.channel == channel,
            NotificationTemplate.active.is_(True),
            NotificationTemplate.deleted_at.is_(None),
        ).order_by(NotificationTemplate.created_at)
        return self._session.scalars(stmt).first()

    def list_templates(
        self, *, q=None, channel=None, event_type=None, active=None, include_deleted=False,
        sort_by="created_at", sort_dir="desc", limit=50, offset=0,
    ) -> Tuple[List[NotificationTemplate], int]:
        stmt = select(NotificationTemplate)
        if not include_deleted:
            stmt = stmt.where(NotificationTemplate.deleted_at.is_(None))
        if channel is not None:
            stmt = stmt.where(NotificationTemplate.channel == channel)
        if event_type is not None:
            stmt = stmt.where(NotificationTemplate.event_type == event_type)
        if active is not None:
            stmt = stmt.where(NotificationTemplate.active.is_(active))
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(or_(
                NotificationTemplate.template_code.ilike(pattern),
                NotificationTemplate.name.ilike(pattern),
            ))
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(NotificationTemplate, sort_by, NotificationTemplate.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class NotificationRepository(_BaseRepo):
    model = Notification

    def get_by_event_recipient_key(self, idempotency_key: str) -> Optional[Notification]:
        """Domain-level idempotency lookup (per tenant via RLS)."""
        stmt = select(Notification).where(Notification.idempotency_key == idempotency_key)
        return self._session.scalars(stmt).first()

    def list_unread_for_user(self, user_id: uuid.UUID, *, limit=50, offset=0) -> Tuple[List[Notification], int]:
        stmt = select(Notification).where(
            Notification.recipient_user_id == user_id,
            Notification.read_at.is_(None),
            Notification.status != NotificationStatus.CANCELLED,
            Notification.deleted_at.is_(None),
        )
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(desc(Notification.created_at)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total

    def list_pending(self, *, limit=100) -> List[Notification]:
        stmt = select(Notification).where(
            Notification.status.in_(_PENDING_STATES),
            Notification.deleted_at.is_(None),
        ).order_by(Notification.created_at).limit(limit)
        return list(self._session.scalars(stmt).all())

    def list_failed_retryable(self, *, max_retries: int = 5, limit: int = 100) -> List[Notification]:
        stmt = select(Notification).where(
            Notification.status == NotificationStatus.FAILED,
            Notification.retry_count < max_retries,
            Notification.deleted_at.is_(None),
        ).order_by(Notification.failed_at).limit(limit)
        return list(self._session.scalars(stmt).all())

    def list_notifications(
        self, *, q=None, status=None, channel=None, recipient_user_id=None, event_type=None,
        unread_only=False, include_deleted=False, sort_by="created_at", sort_dir="desc", limit=50, offset=0,
    ) -> Tuple[List[Notification], int]:
        stmt = select(Notification)
        if not include_deleted:
            stmt = stmt.where(Notification.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Notification.status == status)
        if channel is not None:
            stmt = stmt.where(Notification.channel == channel)
        if recipient_user_id is not None:
            stmt = stmt.where(Notification.recipient_user_id == recipient_user_id)
        if event_type is not None:
            stmt = stmt.where(Notification.event_type == event_type)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(or_(Notification.subject.ilike(pattern), Notification.body.ilike(pattern)))
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(Notification, sort_by, Notification.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class NotificationDeliveryAttemptRepository(_BaseRepo):
    model = NotificationDeliveryAttempt

    def list_attempts_for_notification(self, notification_id: uuid.UUID) -> List[NotificationDeliveryAttempt]:
        stmt = select(NotificationDeliveryAttempt).where(
            NotificationDeliveryAttempt.notification_id == notification_id
        ).order_by(NotificationDeliveryAttempt.attempt_number)
        return list(self._session.scalars(stmt).all())

    def next_attempt_number(self, notification_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.coalesce(func.max(NotificationDeliveryAttempt.attempt_number), 0)).where(
                NotificationDeliveryAttempt.notification_id == notification_id
            )
        )
        return int(current or 0) + 1
