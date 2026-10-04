"""Repositories for the External Integrations & Webhooks domain (Sprint 13).

Constructor takes ``Session``; never commit/flush/rollback; no FastAPI; no events;
tenant-scoped reads via RLS; soft-delete aware. ``get_or_create``-style idempotent
lookups back the webhook consumer and inbound de-duplication.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import ApiKeyStatus, WebhookDeliveryStatus
from app.models.integration import (
    InboundIntegrationEvent,
    IntegrationPartner,
    PartnerApiKey,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from app.repositories.errors import NotFoundError


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


class _SoftDeleteRepo(_BaseRepo):
    def soft_delete(self, obj, *, deleted_by=None):
        obj.soft_delete()
        obj.deleted_by = deleted_by
        return obj

    def restore(self, obj):
        obj.restore()
        obj.deleted_by = None
        return obj


class IntegrationPartnerRepository(_SoftDeleteRepo):
    model = IntegrationPartner

    def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[IntegrationPartner]:
        stmt = select(IntegrationPartner).where(IntegrationPartner.name == name)
        if not include_deleted:
            stmt = stmt.where(IntegrationPartner.deleted_at.is_(None))
        return self._session.scalars(stmt).first()

    def list_partners(
        self,
        *,
        q=None,
        partner_type=None,
        status=None,
        include_deleted=False,
        sort_by="created_at",
        sort_dir="desc",
        limit=50,
        offset=0,
    ) -> Tuple[List[IntegrationPartner], int]:
        stmt = select(IntegrationPartner)
        if not include_deleted:
            stmt = stmt.where(IntegrationPartner.deleted_at.is_(None))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    IntegrationPartner.name.ilike(like),
                    IntegrationPartner.contact_email.ilike(like),
                )
            )
        if partner_type is not None:
            stmt = stmt.where(IntegrationPartner.partner_type == partner_type)
        if status is not None:
            stmt = stmt.where(IntegrationPartner.status == status)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(IntegrationPartner, sort_by, IntegrationPartner.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class PartnerApiKeyRepository(_BaseRepo):
    model = PartnerApiKey

    def get_by_prefix(self, key_prefix: str) -> Optional[PartnerApiKey]:
        """Lookup an active-or-not key by its public prefix (unique per tenant)."""
        stmt = select(PartnerApiKey).where(PartnerApiKey.key_prefix == key_prefix)
        return self._session.scalars(stmt).first()

    def find_active_by_prefix(self, key_prefix: str) -> Optional[PartnerApiKey]:
        stmt = select(PartnerApiKey).where(
            PartnerApiKey.key_prefix == key_prefix,
            PartnerApiKey.status == ApiKeyStatus.ACTIVE,
        )
        return self._session.scalars(stmt).first()

    def list_for_partner(self, partner_id) -> List[PartnerApiKey]:
        stmt = (
            select(PartnerApiKey)
            .where(PartnerApiKey.partner_id == partner_id)
            .order_by(desc(PartnerApiKey.created_at))
        )
        return list(self._session.scalars(stmt).all())


class WebhookSubscriptionRepository(_SoftDeleteRepo):
    model = WebhookSubscription

    def list_active_for_event(self, external_event_type: str) -> List[WebhookSubscription]:
        """Active, non-deleted subscriptions whose event_types include the external name.

        The JSONB ``event_types`` membership test is done in Python for cross-dialect
        portability (the candidate set per tenant is small).
        """
        stmt = select(WebhookSubscription).where(
            WebhookSubscription.deleted_at.is_(None),
            WebhookSubscription.status == "active",
        )
        rows = self._session.scalars(stmt).all()
        return [s for s in rows if external_event_type in (s.event_types or [])]

    def list_subscriptions(
        self,
        *,
        q=None,
        partner_id=None,
        status=None,
        include_deleted=False,
        sort_by="created_at",
        sort_dir="desc",
        limit=50,
        offset=0,
    ) -> Tuple[List[WebhookSubscription], int]:
        stmt = select(WebhookSubscription)
        if not include_deleted:
            stmt = stmt.where(WebhookSubscription.deleted_at.is_(None))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    WebhookSubscription.name.ilike(like), WebhookSubscription.target_url.ilike(like)
                )
            )
        if partner_id is not None:
            stmt = stmt.where(WebhookSubscription.partner_id == partner_id)
        if status is not None:
            stmt = stmt.where(WebhookSubscription.status == status)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(WebhookSubscription, sort_by, WebhookSubscription.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


class WebhookDeliveryRepository(_BaseRepo):
    model = WebhookDelivery

    def find_for_source(self, subscription_id, source_event_id) -> Optional[WebhookDelivery]:
        """Idempotency lookup: an existing delivery for a (subscription, source event)."""
        stmt = select(WebhookDelivery).where(
            WebhookDelivery.subscription_id == subscription_id,
            WebhookDelivery.source_event_id == source_event_id,
        )
        return self._session.scalars(stmt).first()

    def list_deliveries(
        self,
        *,
        subscription_id=None,
        partner_id=None,
        status=None,
        external_event_type=None,
        sort_by="created_at",
        sort_dir="desc",
        limit=50,
        offset=0,
    ) -> Tuple[List[WebhookDelivery], int]:
        stmt = select(WebhookDelivery)
        if subscription_id is not None:
            stmt = stmt.where(WebhookDelivery.subscription_id == subscription_id)
        if partner_id is not None:
            stmt = stmt.where(WebhookDelivery.partner_id == partner_id)
        if status is not None:
            stmt = stmt.where(WebhookDelivery.status == status)
        if external_event_type is not None:
            stmt = stmt.where(WebhookDelivery.external_event_type == external_event_type)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(WebhookDelivery, sort_by, WebhookDelivery.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total

    def list_due(self, *, now=None, limit: int = 100) -> List[WebhookDelivery]:
        """Pending/failed deliveries whose ``next_attempt_at`` is due, oldest first.

        Exhausted deliveries have ``next_attempt_at = NULL`` and are excluded, so this
        never returns a terminally-failed (or delivered/cancelled/skipped) row.
        """
        from app.common.datetime import utcnow

        cutoff = now or utcnow()
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(
                    (WebhookDeliveryStatus.PENDING, WebhookDeliveryStatus.FAILED)
                ),
                WebhookDelivery.next_attempt_at.isnot(None),
                WebhookDelivery.next_attempt_at <= cutoff,
            )
            .order_by(asc(WebhookDelivery.next_attempt_at))
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())


class WebhookDeliveryAttemptRepository(_BaseRepo):
    model = WebhookDeliveryAttempt

    def next_attempt_number(self, delivery_id) -> int:
        current = self._session.scalar(
            select(func.max(WebhookDeliveryAttempt.attempt_number)).where(
                WebhookDeliveryAttempt.delivery_id == delivery_id
            )
        )
        return int(current or 0) + 1

    def list_for_delivery(self, delivery_id) -> List[WebhookDeliveryAttempt]:
        stmt = (
            select(WebhookDeliveryAttempt)
            .where(WebhookDeliveryAttempt.delivery_id == delivery_id)
            .order_by(asc(WebhookDeliveryAttempt.attempt_number))
        )
        return list(self._session.scalars(stmt).all())


class InboundIntegrationEventRepository(_BaseRepo):
    model = InboundIntegrationEvent

    def find_by_idempotency(
        self, api_key_id, idempotency_key: str
    ) -> Optional[InboundIntegrationEvent]:
        stmt = select(InboundIntegrationEvent).where(
            InboundIntegrationEvent.api_key_id == api_key_id,
            InboundIntegrationEvent.idempotency_key == idempotency_key,
        )
        return self._session.scalars(stmt).first()

    def list_inbound(
        self,
        *,
        partner_id=None,
        status=None,
        event_type=None,
        sort_by="created_at",
        sort_dir="desc",
        limit=50,
        offset=0,
    ) -> Tuple[List[InboundIntegrationEvent], int]:
        stmt = select(InboundIntegrationEvent)
        if partner_id is not None:
            stmt = stmt.where(InboundIntegrationEvent.partner_id == partner_id)
        if status is not None:
            stmt = stmt.where(InboundIntegrationEvent.status == status)
        if event_type is not None:
            stmt = stmt.where(InboundIntegrationEvent.event_type == event_type)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = getattr(InboundIntegrationEvent, sort_by, InboundIntegrationEvent.created_at)
        stmt = stmt.order_by((asc if sort_dir == "asc" else desc)(col)).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all()), total


__all__ = [
    "IntegrationPartnerRepository",
    "PartnerApiKeyRepository",
    "WebhookSubscriptionRepository",
    "WebhookDeliveryRepository",
    "WebhookDeliveryAttemptRepository",
    "InboundIntegrationEventRepository",
]
