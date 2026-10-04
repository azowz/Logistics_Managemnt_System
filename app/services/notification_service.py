"""Notification service — templates, notifications, delivery, and event
consumption (context #19, Sprint 10).

Two execution paths share one service class:

* **API path** (routes) — each public operation owns its Unit of Work and
  commits (``create_template``, ``send_notification``, ``mark_read`` …).
* **Consumer path** (``handle_domain_event``) — runs *inside the event
  dispatcher's transaction* (SAVEPOINT) and therefore **never commits**; the
  dispatcher commits the handler's writes together with the ``processed_events``
  idempotency record. Consumer helpers only ``flush`` + append to the outbox.

Notifications never mutate source aggregates. Recipient resolution is decoupled
from other domains (see ``resolve_recipients``).
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.notification_events import (
    NotificationCancelled,
    NotificationCreated,
    NotificationDeliveryAttemptCreated,
    NotificationFailed,
    NotificationQueued,
    NotificationRead,
    NotificationRetried,
    NotificationSent,
    NotificationTemplateActivated,
    NotificationTemplateCreated,
    NotificationTemplateDeactivated,
    NotificationTemplateUpdated,
)
from app.models.enums import (
    DeliveryAttemptStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from app.models.notification import Notification, NotificationDeliveryAttempt, NotificationTemplate
from app.notifications.providers import ProviderRegistry, get_provider_registry
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.notification_repository import (
    NotificationDeliveryAttemptRepository,
    NotificationRepository,
    NotificationTemplateRepository,
)
from app.repositories.user_repository import UserRepository
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.notification_policies import NotificationStateMachine, TemplateRenderer


class NotificationService:
    def __init__(
        self, session: Session, *, provider_registry: Optional[ProviderRegistry] = None
    ) -> None:
        self._session = session
        self._templates = NotificationTemplateRepository(session)
        self._notifications = NotificationRepository(session)
        self._attempts = NotificationDeliveryAttemptRepository(session)
        self._users = UserRepository(session)
        self._event_repo = EventStoreRepository(session)
        self._providers = provider_registry or get_provider_registry()

    # --- context helpers ---

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self):
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id, aggregate_type, tenant_id):
        nv = self._event_repo.next_aggregate_version(aggregate_id)
        env = EventEnvelope.create(
            event,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_version=nv,
            aggregate_type=aggregate_type,
            user_id=self._actor_id(),
        )
        self._event_repo.append(env)

    @staticmethod
    def _ev(value):
        return value.value if hasattr(value, "value") else value

    # ===================== Templates =====================

    def create_template(self, **data) -> NotificationTemplate:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        code = data.get("template_code")
        if code and self._templates.get_by_code(code, include_deleted=True):
            raise ConflictError(f"Template code '{code}' already exists in this tenant.")
        data.pop("active", None)
        template = self._templates.create(
            tenant_id=tenant_id,
            active=True,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()
        self._emit(
            NotificationTemplateCreated(
                template_id=template.id,
                tenant_id=tenant_id,
                template_code=template.template_code,
                channel=self._ev(template.channel),
            ),
            aggregate_id=template.id,
            aggregate_type="NotificationTemplate",
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(template)
        return template

    def get_template(self, template_id, *, include_deleted=False) -> NotificationTemplate:
        t = self._templates.get_by_id(template_id)
        if t is None or (t.is_deleted and not include_deleted):
            raise NotFoundError(f"Template {template_id} not found.")
        return t

    def update_template(self, template_id, **data) -> NotificationTemplate:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        t = self._templates.get_by_id_or_raise(template_id)
        if t.is_deleted:
            raise NotFoundError(f"Template {template_id} not found (deleted).")
        data["updated_by"] = actor_id
        self._templates.update(t, **data)
        self._session.flush()
        self._emit(
            NotificationTemplateUpdated(template_id=t.id, tenant_id=tenant_id),
            aggregate_id=t.id,
            aggregate_type="NotificationTemplate",
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(t)
        return t

    def _set_template_active(self, template_id, active: bool, event_cls):
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        t = self._templates.get_by_id_or_raise(template_id)
        if t.is_deleted:
            raise NotFoundError(f"Template {template_id} not found (deleted).")
        if t.active == active:
            return t
        t.active = active
        t.updated_by = actor_id
        self._session.flush()
        self._emit(
            event_cls(template_id=t.id, tenant_id=tenant_id),
            aggregate_id=t.id,
            aggregate_type="NotificationTemplate",
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(t)
        return t

    def activate_template(self, template_id):
        return self._set_template_active(template_id, True, NotificationTemplateActivated)

    def deactivate_template(self, template_id):
        return self._set_template_active(template_id, False, NotificationTemplateDeactivated)

    def delete_template(self, template_id) -> None:
        self._tenant_id()
        actor_id = self._actor_id()
        t = self._templates.get_by_id_or_raise(template_id)
        if t.is_deleted:
            raise NotFoundError(f"Template {template_id} is already deleted.")
        self._templates.soft_delete(t, deleted_by=actor_id)
        self._session.commit()

    def restore_template(self, template_id) -> NotificationTemplate:
        self._tenant_id()
        t = self._templates.get_by_id(template_id)
        if t is None:
            raise NotFoundError(f"Template {template_id} not found.")
        if not t.is_deleted:
            raise ValidationError(f"Template {template_id} is not deleted; nothing to restore.")
        self._templates.restore(t)
        self._session.commit()
        self._session.refresh(t)
        return t

    def list_templates(self, params) -> Page[NotificationTemplate]:
        items, total = self._templates.list_templates(
            q=params.q,
            channel=params.channel,
            event_type=params.event_type,
            active=params.active,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        return Page.create(
            items=items, total=total, params=PageParams(page=params.page, size=params.size)
        )

    search_templates = list_templates

    # ===================== Rendering / recipients / idempotency =====================

    def render_template(self, *, event_type, channel, variables, subject=None, body=None):
        """Resolve (subject, body, template_id) for a notification.

        If an active template exists for ``(event_type, channel)`` it is rendered
        (required variables validated). Otherwise an explicit subject/body is used,
        or a safe built-in default derived from the event type.
        """
        template = None
        if event_type is not None:
            template = self._templates.get_active_for_event(event_type, channel)
        if template is not None:
            TemplateRenderer.validate_variables(template.variables_schema, variables)
            rendered_subject = TemplateRenderer.render(template.subject_template, variables)
            rendered_body = TemplateRenderer.render(template.body_template, variables)
            return (rendered_subject or None), rendered_body, template.id
        if body:
            return subject, body, None
        # Built-in default — keeps event-driven triggers working without seeded templates.
        default_subject = subject or (event_type or "Notification")
        default_body = TemplateRenderer.render(
            "{event_type} for {aggregate_type} {aggregate_id}",
            {
                "event_type": event_type or "event",
                "aggregate_type": variables.get("aggregate_type", "") if variables else "",
                "aggregate_id": variables.get("aggregate_id", "") if variables else "",
            },
        )
        return default_subject, default_body, None

    @staticmethod
    def resolve_recipients(envelope: EventEnvelope) -> List[dict]:
        """Resolve recipient targets for an event-driven notification.

        Sprint 10 routes the event's **actor** (``envelope.user_id``) an in-app
        notice. Richer routing (notify the shipment's client / invoice's customer
        / assignee) is a documented follow-up. Returns ``[]`` when no recipient is
        resolvable so no target-less notification is created.
        """
        if envelope.user_id is not None:
            return [{"recipient_user_id": envelope.user_id}]
        return []

    @staticmethod
    def _idempotency_key(event_id, channel: NotificationChannel, recipient: dict) -> str:
        rkey = (
            str(recipient.get("recipient_user_id"))
            if recipient.get("recipient_user_id")
            else recipient.get("recipient_email") or recipient.get("recipient_phone") or "tenant"
        )
        return f"{event_id}:{channel.value}:{rkey}"

    def enforce_idempotency(self, idempotency_key: str) -> Optional[Notification]:
        return self._notifications.get_by_event_recipient_key(idempotency_key)

    # ===================== Notifications (API path) =====================

    def _validate_recipient(self, tenant_id, data) -> None:
        if data.get("recipient_user_id") is not None:
            user = self._users.get_by_id(data["recipient_user_id"])
            if user is None or getattr(user, "tenant_id", None) != tenant_id:
                raise ValidationError("recipient_user_id does not exist in this tenant.")
        if not any(
            data.get(k) for k in ("recipient_user_id", "recipient_email", "recipient_phone")
        ):
            raise ValidationError("A notification must have at least one recipient target.")

    def create_notification(self, **data) -> Notification:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        self._validate_recipient(tenant_id, data)
        channel = data.get("channel")
        variables = data.pop("variables", None) or {}
        subject, body, template_id = self.render_template(
            event_type=data.pop("event_type", None),
            channel=channel,
            variables=variables,
            subject=data.pop("subject", None),
            body=data.pop("body", None),
        )
        if not body:
            raise ValidationError(
                "A notification must have a body (provide body or a renderable template)."
            )
        key = data.pop("idempotency_key", None) or f"manual:{uuid.uuid4()}"
        if self.enforce_idempotency(key):
            raise ConflictError("A notification with this idempotency key already exists.")
        data.pop("status", None)
        notification = self._notifications.create(
            tenant_id=tenant_id,
            idempotency_key=key,
            subject=subject,
            body=body,
            template_id=template_id,
            status=NotificationStatus.PENDING,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()
        self._emit_created(notification, tenant_id)
        self._session.commit()
        self._session.refresh(notification)
        return notification

    def _emit_created(self, notification: Notification, tenant_id) -> None:
        self._emit(
            NotificationCreated(
                notification_id=notification.id,
                tenant_id=tenant_id,
                channel=self._ev(notification.channel),
                status=self._ev(notification.status),
                source_event_type=notification.event_type,
                recipient_user_id=notification.recipient_user_id,
                priority=self._ev(notification.priority),
            ),
            aggregate_id=notification.id,
            aggregate_type="Notification",
            tenant_id=tenant_id,
        )

    def get_notification(
        self, notification_id, *, include_deleted=False, viewer_user_id=None
    ) -> Notification:
        n = self._notifications.get_by_id(notification_id)
        if n is None or (n.is_deleted and not include_deleted):
            raise NotFoundError(f"Notification {notification_id} not found.")
        # Per-user ownership scoping for non-privileged viewers (defence-in-depth
        # beyond RLS, which only isolates tenants). A clean 404 avoids leaking the
        # existence of another user's notification.
        if viewer_user_id is not None and n.recipient_user_id != viewer_user_id:
            raise NotFoundError(f"Notification {notification_id} not found.")
        return n

    def queue_notification(self, notification_id) -> Notification:
        n = self._load_active(notification_id)
        previous = n.status
        NotificationStateMachine.validate_transition(previous, NotificationStatus.QUEUED)
        n.status = NotificationStatus.QUEUED
        n.queued_at = utcnow()
        n.updated_by = self._actor_id()
        self._session.flush()
        self._emit(
            NotificationQueued(
                notification_id=n.id, tenant_id=n.tenant_id, previous_status=previous.value
            ),
            aggregate_id=n.id,
            aggregate_type="Notification",
            tenant_id=n.tenant_id,
        )
        self._session.commit()
        self._session.refresh(n)
        return n

    def send_notification(self, notification_id) -> Notification:
        n = self._load_active(notification_id)
        if n.status in (NotificationStatus.SENT, NotificationStatus.READ):
            raise ValidationError(
                f"Notification {notification_id} was already sent (use retry for a failed one)."
            )
        if n.status == NotificationStatus.CANCELLED:
            raise ValidationError("Cannot send a cancelled notification.")
        if n.status == NotificationStatus.FAILED:
            raise ValidationError("Use retry to re-send a failed notification.")
        self._deliver(n)
        self._session.commit()
        self._session.refresh(n)
        return n

    def retry_notification(self, notification_id) -> Notification:
        n = self._load_active(notification_id)
        if n.status != NotificationStatus.FAILED:
            raise ValidationError("Only a failed notification can be retried.")
        NotificationStateMachine.validate_transition(n.status, NotificationStatus.QUEUED)
        n.status = NotificationStatus.QUEUED
        n.queued_at = utcnow()
        self._session.flush()
        self._emit(
            NotificationRetried(
                notification_id=n.id, tenant_id=n.tenant_id, retry_count=n.retry_count
            ),
            aggregate_id=n.id,
            aggregate_type="Notification",
            tenant_id=n.tenant_id,
        )
        self._deliver(n, is_retry=True)
        self._session.commit()
        self._session.refresh(n)
        return n

    def cancel_notification(self, notification_id, *, reason=None) -> Notification:
        n = self._load_active(notification_id)
        previous = n.status
        NotificationStateMachine.validate_transition(previous, NotificationStatus.CANCELLED)
        n.status = NotificationStatus.CANCELLED
        n.cancelled_at = utcnow()
        n.updated_by = self._actor_id()
        self._session.flush()
        self._emit(
            NotificationCancelled(
                notification_id=n.id,
                tenant_id=n.tenant_id,
                previous_status=previous.value,
                reason=reason,
            ),
            aggregate_id=n.id,
            aggregate_type="Notification",
            tenant_id=n.tenant_id,
        )
        self._session.commit()
        self._session.refresh(n)
        return n

    def mark_read(self, notification_id, *, viewer_user_id=None) -> Notification:
        n = self._load_active(notification_id)
        if viewer_user_id is not None and n.recipient_user_id != viewer_user_id:
            raise NotFoundError(f"Notification {notification_id} not found.")
        if n.read_at is not None or n.status == NotificationStatus.READ:
            return n  # idempotent: do not re-mark
        NotificationStateMachine.validate_transition(n.status, NotificationStatus.READ)
        n.status = NotificationStatus.READ
        n.read_at = utcnow()
        n.updated_by = self._actor_id()
        self._session.flush()
        self._emit(
            NotificationRead(
                notification_id=n.id,
                tenant_id=n.tenant_id,
                recipient_user_id=n.recipient_user_id,
                priority=self._ev(n.priority),
            ),
            aggregate_id=n.id,
            aggregate_type="Notification",
            tenant_id=n.tenant_id,
        )
        self._session.commit()
        self._session.refresh(n)
        return n

    def _load_active(self, notification_id) -> Notification:
        n = self._notifications.get_by_id_or_raise(notification_id)
        if n.is_deleted:
            raise NotFoundError(f"Notification {notification_id} not found (deleted).")
        return n

    def list_notifications(self, params) -> Page[Notification]:
        items, total = self._notifications.list_notifications(
            q=params.q,
            status=params.status,
            channel=params.channel,
            recipient_user_id=params.recipient_user_id,
            event_type=params.event_type,
            unread_only=params.unread_only,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        return Page.create(
            items=items, total=total, params=PageParams(page=params.page, size=params.size)
        )

    search_notifications = list_notifications

    def list_unread(self, user_id, *, page=1, size=50) -> Page[Notification]:
        items, total = self._notifications.list_unread_for_user(
            user_id, limit=size, offset=(page - 1) * size
        )
        return Page.create(items=items, total=total, params=PageParams(page=page, size=size))

    def list_delivery_attempts(self, notification_id) -> List[NotificationDeliveryAttempt]:
        self.get_notification(notification_id, include_deleted=True)
        return self._attempts.list_attempts_for_notification(notification_id)

    # ===================== Delivery (shared, no commit) =====================

    def _deliver(
        self, notification: Notification, *, is_retry: bool = False
    ) -> NotificationDeliveryAttempt:
        """Attempt delivery via the channel provider. Flushes + emits; never commits."""
        tenant_id = notification.tenant_id
        provider = self._providers.get(notification.channel)
        attempt_number = self._attempts.next_attempt_number(notification.id)
        requested = utcnow()
        if provider is None:
            result_status = DeliveryAttemptStatus.SKIPPED
            provider_name, msg_id, err_code, err_msg, payload = (
                None,
                None,
                "no_provider",
                f"No provider registered for channel '{notification.channel.value}'.",
                None,
            )
            succeeded = False
        else:
            result = provider.send(notification)
            result_status = result.status
            provider_name, msg_id = result.provider, result.provider_message_id
            err_code, err_msg, payload = (
                result.error_code,
                result.error_message,
                result.response_payload,
            )
            succeeded = result.succeeded
        attempt = self._attempts.create(
            tenant_id=tenant_id,
            notification_id=notification.id,
            channel=notification.channel,
            provider=provider_name,
            status=result_status,
            attempt_number=attempt_number,
            requested_at=requested,
            completed_at=utcnow(),
            provider_message_id=msg_id,
            error_code=err_code,
            error_message=err_msg,
            response_payload=payload,
        )
        self._session.flush()
        self._emit(
            NotificationDeliveryAttemptCreated(
                attempt_id=attempt.id,
                tenant_id=tenant_id,
                notification_id=notification.id,
                channel=self._ev(notification.channel),
                status=self._ev(result_status),
                attempt_number=attempt_number,
            ),
            aggregate_id=notification.id,
            aggregate_type="Notification",
            tenant_id=tenant_id,
        )
        previous = notification.status
        if succeeded:
            if NotificationStateMachine.can_transition(previous, NotificationStatus.SENT):
                notification.status = NotificationStatus.SENT
                notification.sent_at = utcnow()
            self._emit(
                NotificationSent(
                    notification_id=notification.id,
                    tenant_id=tenant_id,
                    channel=self._ev(notification.channel),
                    provider=provider_name,
                ),
                aggregate_id=notification.id,
                aggregate_type="Notification",
                tenant_id=tenant_id,
            )
        else:
            if NotificationStateMachine.can_transition(previous, NotificationStatus.FAILED):
                notification.status = NotificationStatus.FAILED
            notification.failed_at = utcnow()
            notification.retry_count = (notification.retry_count or 0) + 1
            notification.last_error = err_msg or "delivery failed"
            self._emit(
                NotificationFailed(
                    notification_id=notification.id,
                    tenant_id=tenant_id,
                    channel=self._ev(notification.channel),
                    reason=notification.last_error,
                ),
                aggregate_id=notification.id,
                aggregate_type="Notification",
                tenant_id=tenant_id,
            )
        self._session.flush()
        return attempt

    # ===================== Event consumer (no commit) =====================

    def create_notifications_from_event(
        self,
        event,
        envelope: EventEnvelope,
        *,
        channel: NotificationChannel,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        deliver: bool = True,
    ) -> List[Notification]:
        """Idempotently create (and optionally deliver) notifications for an event.

        Runs inside the dispatcher's transaction — **does not commit**. Idempotency
        is enforced both by the dispatcher (``processed_events``) and here via the
        per-recipient idempotency key + unique constraint.
        """
        tenant_id = envelope.tenant_id
        recipients = self.resolve_recipients(envelope)
        created: List[Notification] = []
        variables = dict(envelope.payload or {})
        variables.setdefault("aggregate_type", envelope.aggregate_type)
        variables.setdefault("aggregate_id", str(envelope.aggregate_id))
        for recipient in recipients:
            key = self._idempotency_key(envelope.event_id, channel, recipient)
            if self.enforce_idempotency(key):
                continue  # already created for this event/channel/recipient
            subject, body, template_id = self.render_template(
                event_type=envelope.event_type,
                channel=channel,
                variables=variables,
            )
            try:
                # SAVEPOINT so a lost idempotency-key race rolls back only this
                # insert (the unique constraint is the source of truth) without
                # poisoning the surrounding dispatcher transaction.
                with self._session.begin_nested():
                    notification = self._notifications.create(
                        tenant_id=tenant_id,
                        idempotency_key=key,
                        event_id=envelope.event_id,
                        event_type=envelope.event_type,
                        aggregate_type=envelope.aggregate_type,
                        aggregate_id=envelope.aggregate_id,
                        channel=channel,
                        subject=subject,
                        body=body,
                        template_id=template_id,
                        status=NotificationStatus.PENDING,
                        priority=priority,
                        created_by=envelope.user_id,
                        updated_by=envelope.user_id,
                        **recipient,
                    )
                    self._session.flush()
            except IntegrityError:
                # A concurrent consumer won the race for this idempotency key —
                # treat as an idempotent skip, not a failed event.
                continue
            self._emit_created(notification, tenant_id)
            if deliver:
                self._deliver(notification)
            created.append(notification)
        return created

    def handle_domain_event(
        self,
        event,
        envelope: EventEnvelope,
        *,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> List[Notification]:
        """Consumer entrypoint (no commit). Creates + delivers in-app notifications."""
        return self.create_notifications_from_event(
            event, envelope, channel=channel, priority=priority
        )
