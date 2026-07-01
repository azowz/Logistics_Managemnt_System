"""External Integrations & Webhooks service (context #21, Sprint 13).

Owns the Unit of Work for the integration surface. Two transaction disciplines:

* **API path** (partners, keys, subscriptions, delivery ops, inbound) — each method owns
  its UoW: mutate → ``flush()`` → emit domain event → ``commit()`` → ``refresh()``.
* **Consumer path** (``create_deliveries_from_event``) — runs inside the dispatcher
  SAVEPOINT and **never commits**; it only flushes and appends to the outbox.

Secrets never leave this layer in the clear except the one-time create/rotate return
values surfaced to the caller. Outbound payloads are sanitized (whitelist) and signed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.integration_events import (
    InboundIntegrationEventAccepted,
    InboundIntegrationEventReceived,
    InboundIntegrationEventRejected,
    IntegrationPartnerActivated,
    IntegrationPartnerCreated,
    IntegrationPartnerSuspended,
    IntegrationPartnerUpdated,
    PartnerApiKeyCreated,
    PartnerApiKeyRevoked,
    PartnerApiKeyRotated,
    WebhookDeliveryAttempted,
    WebhookDeliveryCreated,
    WebhookDeliveryFailed,
    WebhookDeliverySucceeded,
    WebhookSubscriptionActivated,
    WebhookSubscriptionCreated,
    WebhookSubscriptionDeactivated,
    WebhookSubscriptionUpdated,
)
from app.integrations import crypto
from app.integrations.delivery import get_webhook_provider
from app.integrations.event_mapping import external_name, sanitize_payload
from app.integrations.policies import validate_event_types, validate_target_url
from app.models.enums import (
    ApiKeyStatus,
    InboundEventStatus,
    IntegrationPartnerStatus,
    WebhookAttemptStatus,
    WebhookDeliveryStatus,
    WebhookSubscriptionStatus,
)
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.integration_repository import (
    InboundIntegrationEventRepository,
    IntegrationPartnerRepository,
    PartnerApiKeyRepository,
    WebhookDeliveryAttemptRepository,
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class ApiKeyAuthContext:
    """Result of authenticating a partner API key (returned to the auth dependency)."""

    api_key_id: "uuid.UUID"  # noqa: F821 - forward ref, real uuid.UUID at runtime
    partner_id: "uuid.UUID"  # noqa: F821
    tenant_id: "uuid.UUID"   # noqa: F821


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _canonical_body(payload: dict) -> str:
    """Deterministic JSON body used for hashing/signing (stable key order)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


class IntegrationService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._partners = IntegrationPartnerRepository(session)
        self._keys = PartnerApiKeyRepository(session)
        self._subs = WebhookSubscriptionRepository(session)
        self._deliveries = WebhookDeliveryRepository(session)
        self._attempts = WebhookDeliveryAttemptRepository(session)
        self._inbound = InboundIntegrationEventRepository(session)
        self._event_repo = EventStoreRepository(session)

    # --- context / emit ---

    def _tenant_id(self):
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self):
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id, aggregate_type, tenant_id) -> None:
        nv = self._event_repo.next_aggregate_version(aggregate_id)
        env = EventEnvelope.create(event, tenant_id=tenant_id, aggregate_id=aggregate_id,
                                   aggregate_version=nv, aggregate_type=aggregate_type, user_id=self._actor_id())
        self._event_repo.append(env)

    def _owned(self, obj, tenant_id, kind, obj_id):
        if obj is None or obj.tenant_id != tenant_id or getattr(obj, "is_deleted", False):
            raise NotFoundError(f"{kind} {obj_id} not found.")
        return obj

    # ===================== Partners =====================

    def create_partner(self, *, name, partner_type, contact_email=None, contact_phone=None,
                       notes=None, partner_metadata=None) -> "IntegrationPartner":  # noqa: F821
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        if self._partners.get_by_name(name) is not None:
            raise ConflictError(f"An integration partner named '{name}' already exists.")
        partner = self._partners.create(
            tenant_id=tenant_id, name=name, partner_type=partner_type,
            status=IntegrationPartnerStatus.ACTIVE, contact_email=contact_email,
            contact_phone=contact_phone, notes=notes, partner_metadata=partner_metadata,
            created_by=actor_id, updated_by=actor_id,
        )
        self._session.flush()
        self._emit(
            IntegrationPartnerCreated(partner_id=partner.id, tenant_id=tenant_id, name=partner.name,
                                      partner_type=self._ev(partner.partner_type), status=self._ev(partner.status)),
            aggregate_id=partner.id, aggregate_type="IntegrationPartner", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(partner)
        return partner

    def update_partner(self, partner_id, **data) -> "IntegrationPartner":  # noqa: F821
        tenant_id = self._tenant_id()
        partner = self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        mutable = {k: v for k, v in data.items()
                   if k in {"name", "contact_email", "contact_phone", "notes", "partner_metadata", "partner_type"}}
        if "name" in mutable and mutable["name"] and mutable["name"] != partner.name:
            existing = self._partners.get_by_name(mutable["name"])
            if existing is not None and existing.id != partner.id:
                raise ConflictError(f"An integration partner named '{mutable['name']}' already exists.")
        self._partners.update(partner, **mutable)
        partner.updated_by = self._actor_id()
        self._session.flush()
        self._emit(IntegrationPartnerUpdated(partner_id=partner.id, tenant_id=tenant_id),
                   aggregate_id=partner.id, aggregate_type="IntegrationPartner", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(partner)
        return partner

    def suspend_partner(self, partner_id) -> "IntegrationPartner":  # noqa: F821
        tenant_id = self._tenant_id()
        partner = self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        previous = partner.status
        if previous == IntegrationPartnerStatus.SUSPENDED:
            return partner
        partner.status = IntegrationPartnerStatus.SUSPENDED
        partner.updated_by = self._actor_id()
        self._session.flush()
        self._emit(IntegrationPartnerSuspended(partner_id=partner.id, tenant_id=tenant_id,
                                                previous_status=self._ev(previous)),
                   aggregate_id=partner.id, aggregate_type="IntegrationPartner", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(partner)
        return partner

    def activate_partner(self, partner_id) -> "IntegrationPartner":  # noqa: F821
        tenant_id = self._tenant_id()
        partner = self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        previous = partner.status
        if previous == IntegrationPartnerStatus.ACTIVE:
            return partner
        partner.status = IntegrationPartnerStatus.ACTIVE
        partner.updated_by = self._actor_id()
        self._session.flush()
        self._emit(IntegrationPartnerActivated(partner_id=partner.id, tenant_id=tenant_id,
                                               previous_status=self._ev(previous)),
                   aggregate_id=partner.id, aggregate_type="IntegrationPartner", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(partner)
        return partner

    def delete_partner(self, partner_id) -> None:
        tenant_id = self._tenant_id()
        partner = self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        self._partners.soft_delete(partner, deleted_by=self._actor_id())
        self._session.flush()
        self._emit(IntegrationPartnerUpdated(partner_id=partner.id, tenant_id=tenant_id),
                   aggregate_id=partner.id, aggregate_type="IntegrationPartner", tenant_id=tenant_id)
        self._session.commit()

    def get_partner(self, partner_id) -> "IntegrationPartner":  # noqa: F821
        tenant_id = self._tenant_id()
        return self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)

    def list_partners(self, **kw):
        self._tenant_id()
        return self._partners.list_partners(**kw)

    # ===================== API keys =====================

    def create_api_key(self, partner_id, *, name, scopes=None, allowed_ips=None, expires_at=None
                       ) -> Tuple["PartnerApiKey", str]:  # noqa: F821
        tenant_id = self._tenant_id()
        partner = self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        plaintext, key_prefix, key_hash = crypto.generate_api_key()
        key = self._keys.create(
            tenant_id=tenant_id, partner_id=partner.id, name=name, key_prefix=key_prefix,
            key_hash=key_hash, status=ApiKeyStatus.ACTIVE, scopes=scopes, allowed_ips=allowed_ips,
            expires_at=expires_at, created_by=self._actor_id(),
        )
        self._session.flush()
        self._emit(PartnerApiKeyCreated(api_key_id=key.id, tenant_id=tenant_id, partner_id=partner.id,
                                        key_prefix=key.key_prefix),
                   aggregate_id=key.id, aggregate_type="PartnerApiKey", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(key)
        return key, plaintext

    def revoke_api_key(self, api_key_id) -> "PartnerApiKey":  # noqa: F821
        tenant_id = self._tenant_id()
        key = self._keys.get_by_id(api_key_id)
        if key is None or key.tenant_id != tenant_id:
            raise NotFoundError(f"PartnerApiKey {api_key_id} not found.")
        if key.status == ApiKeyStatus.REVOKED:
            return key
        key.status = ApiKeyStatus.REVOKED
        key.revoked_at = utcnow()
        key.revoked_by = self._actor_id()
        self._session.flush()
        self._emit(PartnerApiKeyRevoked(api_key_id=key.id, tenant_id=tenant_id, partner_id=key.partner_id),
                   aggregate_id=key.id, aggregate_type="PartnerApiKey", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(key)
        return key

    def rotate_api_key(self, api_key_id) -> Tuple["PartnerApiKey", str]:  # noqa: F821
        """Revoke the old key and mint a fresh one for the same partner (one-time reveal)."""
        tenant_id = self._tenant_id()
        old = self._keys.get_by_id(api_key_id)
        if old is None or old.tenant_id != tenant_id:
            raise NotFoundError(f"PartnerApiKey {api_key_id} not found.")
        if old.status != ApiKeyStatus.REVOKED:
            old.status = ApiKeyStatus.REVOKED
            old.revoked_at = utcnow()
            old.revoked_by = self._actor_id()
        plaintext, key_prefix, key_hash = crypto.generate_api_key()
        new = self._keys.create(
            tenant_id=tenant_id, partner_id=old.partner_id, name=old.name, key_prefix=key_prefix,
            key_hash=key_hash, status=ApiKeyStatus.ACTIVE, scopes=old.scopes, allowed_ips=old.allowed_ips,
            expires_at=old.expires_at, created_by=self._actor_id(),
        )
        self._session.flush()
        self._emit(PartnerApiKeyRotated(api_key_id=new.id, tenant_id=tenant_id, partner_id=new.partner_id,
                                        new_key_prefix=new.key_prefix),
                   aggregate_id=new.id, aggregate_type="PartnerApiKey", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(new)
        return new, plaintext

    def list_api_keys(self, partner_id) -> List["PartnerApiKey"]:  # noqa: F821
        tenant_id = self._tenant_id()
        self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        return self._keys.list_for_partner(partner_id)

    def authenticate_api_key(self, plaintext: str) -> Optional[ApiKeyAuthContext]:
        """Verify a presented API key. Returns a context or ``None`` (never raises on bad key).

        Runs in whatever scope the caller established (the auth dependency uses platform
        scope so the prefix lookup can span tenants). On success, stamps ``last_used_at``
        and flushes; the caller commits.
        """
        prefix = crypto.extract_key_prefix(plaintext or "")
        if prefix is None:
            return None
        key = self._keys.get_by_prefix(prefix)
        if key is None or not crypto.verify_api_key(plaintext, key.key_hash):
            return None
        if key.status != ApiKeyStatus.ACTIVE:
            return None
        now = utcnow()
        if key.expires_at is not None and _aware(key.expires_at) < now:
            return None
        partner = self._partners.get_by_id(key.partner_id)
        if partner is None or partner.is_deleted or partner.status != IntegrationPartnerStatus.ACTIVE:
            return None
        key.last_used_at = now
        self._session.flush()
        return ApiKeyAuthContext(api_key_id=key.id, partner_id=key.partner_id, tenant_id=key.tenant_id)

    @staticmethod
    def _ev(value):
        return value.value if hasattr(value, "value") else value

    # ===================== Webhook subscriptions =====================

    def create_subscription(self, partner_id, *, name, target_url, event_types, max_retries=5,
                            timeout_seconds=10, subscription_metadata=None, allow_insecure_url=False
                            ) -> Tuple["WebhookSubscription", str]:  # noqa: F821
        tenant_id = self._tenant_id()
        partner = self._owned(self._partners.get_by_id(partner_id), tenant_id, "IntegrationPartner", partner_id)
        if partner.status != IntegrationPartnerStatus.ACTIVE:
            raise ValidationError("Subscriptions can only be created for an active partner.")
        target_url = validate_target_url(target_url, allow_insecure=allow_insecure_url)
        event_types = validate_event_types(event_types)
        secret = crypto.generate_webhook_secret()
        sub = self._subs.create(
            tenant_id=tenant_id, partner_id=partner.id, name=name, target_url=target_url,
            event_types=event_types, status=WebhookSubscriptionStatus.ACTIVE,
            encrypted_secret=crypto.encrypt_secret(secret), max_retries=max_retries,
            timeout_seconds=timeout_seconds, subscription_metadata=subscription_metadata,
            created_by=self._actor_id(), updated_by=self._actor_id(),
        )
        self._session.flush()
        self._emit(WebhookSubscriptionCreated(subscription_id=sub.id, tenant_id=tenant_id,
                                              partner_id=partner.id, status=self._ev(sub.status)),
                   aggregate_id=sub.id, aggregate_type="WebhookSubscription", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(sub)
        return sub, secret

    def update_subscription(self, subscription_id, *, allow_insecure_url=False, **data) -> "WebhookSubscription":  # noqa: F821
        tenant_id = self._tenant_id()
        sub = self._owned(self._subs.get_by_id(subscription_id), tenant_id, "WebhookSubscription", subscription_id)
        if "target_url" in data and data["target_url"]:
            data["target_url"] = validate_target_url(data["target_url"], allow_insecure=allow_insecure_url)
        if "event_types" in data and data["event_types"] is not None:
            data["event_types"] = validate_event_types(data["event_types"])
        mutable = {k: v for k, v in data.items()
                   if k in {"name", "target_url", "event_types", "max_retries", "timeout_seconds",
                            "subscription_metadata"}}
        self._subs.update(sub, **mutable)
        sub.updated_by = self._actor_id()
        self._session.flush()
        self._emit(WebhookSubscriptionUpdated(subscription_id=sub.id, tenant_id=tenant_id),
                   aggregate_id=sub.id, aggregate_type="WebhookSubscription", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(sub)
        return sub

    def activate_subscription(self, subscription_id) -> "WebhookSubscription":  # noqa: F821
        tenant_id = self._tenant_id()
        sub = self._owned(self._subs.get_by_id(subscription_id), tenant_id, "WebhookSubscription", subscription_id)
        previous = sub.status
        if previous == WebhookSubscriptionStatus.ACTIVE:
            return sub
        sub.status = WebhookSubscriptionStatus.ACTIVE
        sub.updated_by = self._actor_id()
        self._session.flush()
        self._emit(WebhookSubscriptionActivated(subscription_id=sub.id, tenant_id=tenant_id,
                                                previous_status=self._ev(previous)),
                   aggregate_id=sub.id, aggregate_type="WebhookSubscription", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(sub)
        return sub

    def deactivate_subscription(self, subscription_id) -> "WebhookSubscription":  # noqa: F821
        tenant_id = self._tenant_id()
        sub = self._owned(self._subs.get_by_id(subscription_id), tenant_id, "WebhookSubscription", subscription_id)
        previous = sub.status
        if previous == WebhookSubscriptionStatus.INACTIVE:
            return sub
        sub.status = WebhookSubscriptionStatus.INACTIVE
        sub.updated_by = self._actor_id()
        self._session.flush()
        self._emit(WebhookSubscriptionDeactivated(subscription_id=sub.id, tenant_id=tenant_id,
                                                  previous_status=self._ev(previous)),
                   aggregate_id=sub.id, aggregate_type="WebhookSubscription", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(sub)
        return sub

    def delete_subscription(self, subscription_id) -> None:
        tenant_id = self._tenant_id()
        sub = self._owned(self._subs.get_by_id(subscription_id), tenant_id, "WebhookSubscription", subscription_id)
        self._subs.soft_delete(sub, deleted_by=self._actor_id())
        self._session.flush()
        self._emit(WebhookSubscriptionUpdated(subscription_id=sub.id, tenant_id=tenant_id),
                   aggregate_id=sub.id, aggregate_type="WebhookSubscription", tenant_id=tenant_id)
        self._session.commit()

    def rotate_subscription_secret(self, subscription_id) -> Tuple["WebhookSubscription", str]:  # noqa: F821
        tenant_id = self._tenant_id()
        sub = self._owned(self._subs.get_by_id(subscription_id), tenant_id, "WebhookSubscription", subscription_id)
        secret = crypto.generate_webhook_secret()
        sub.encrypted_secret = crypto.encrypt_secret(secret)
        sub.updated_by = self._actor_id()
        self._session.flush()
        self._emit(WebhookSubscriptionUpdated(subscription_id=sub.id, tenant_id=tenant_id),
                   aggregate_id=sub.id, aggregate_type="WebhookSubscription", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(sub)
        return sub, secret

    def get_subscription(self, subscription_id) -> "WebhookSubscription":  # noqa: F821
        tenant_id = self._tenant_id()
        return self._owned(self._subs.get_by_id(subscription_id), tenant_id, "WebhookSubscription", subscription_id)

    def list_subscriptions(self, **kw):
        self._tenant_id()
        return self._subs.list_subscriptions(**kw)

    # ===================== Outbound deliveries =====================

    def create_deliveries_from_event(self, envelope: EventEnvelope) -> list:
        """Consumer path: fan an internal event out to matching subscriptions. NO commit.

        Idempotent per ``(subscription, source_event_id)`` via a unique constraint + a
        pre-check. Payloads are sanitized (whitelist) and signed with the subscription's
        (decrypted) secret. Unmapped internal events are ignored.
        """
        ext = external_name(envelope.event_type)
        if ext is None:
            return []
        created = []
        for sub in self._subs.list_active_for_event(ext):
            partner = self._partners.get_by_id(sub.partner_id)
            if partner is None or partner.is_deleted or partner.status != IntegrationPartnerStatus.ACTIVE:
                continue
            if self._deliveries.find_for_source(sub.id, envelope.event_id) is not None:
                continue  # idempotent skip
            data = sanitize_payload(envelope.payload)
            payload = {
                "event": ext,
                "event_id": str(envelope.event_id),
                "occurred_at": envelope.occurred_at.isoformat() if envelope.occurred_at else None,
                "aggregate_type": envelope.aggregate_type or None,
                "aggregate_id": str(envelope.aggregate_id) if envelope.aggregate_id else None,
                "data": data,
            }
            body = _canonical_body(payload)
            payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            secret = crypto.decrypt_secret(sub.encrypted_secret)
            if secret is None:
                # M1: never sign with an empty secret. Record an unsigned, failed delivery
                # + a skipped attempt so the integrity failure is observable and the payload
                # is not sent with a partner-unverifiable signature. No secret is exposed.
                delivery = self._deliveries.create(
                    tenant_id=sub.tenant_id, subscription_id=sub.id, partner_id=sub.partner_id,
                    source_event_id=envelope.event_id, source_event_type=envelope.event_type,
                    external_event_type=ext, aggregate_type=envelope.aggregate_type or None,
                    aggregate_id=envelope.aggregate_id, status=WebhookDeliveryStatus.FAILED,
                    payload=payload, payload_hash=payload_hash, signature="",
                    next_attempt_at=None, attempt_count=0, failed_at=utcnow(),
                    last_error="secret_undecryptable",
                )
                self._session.flush()
                self._attempts.create(
                    tenant_id=sub.tenant_id, delivery_id=delivery.id, attempt_number=1,
                    status=WebhookAttemptStatus.SKIPPED, requested_at=utcnow(), completed_at=utcnow(),
                    error_code="secret_undecryptable",
                    error_message="Subscription signing secret could not be decrypted; delivery not signed.",
                )
                self._session.flush()
                self._emit(
                    WebhookDeliveryCreated(delivery_id=delivery.id, tenant_id=sub.tenant_id,
                                           subscription_id=sub.id, source_event_id=envelope.event_id,
                                           external_event_type=ext),
                    aggregate_id=delivery.id, aggregate_type="WebhookDelivery", tenant_id=sub.tenant_id,
                )
                self._emit(
                    WebhookDeliveryFailed(delivery_id=delivery.id, tenant_id=sub.tenant_id,
                                          subscription_id=sub.id, reason="secret_undecryptable"),
                    aggregate_id=delivery.id, aggregate_type="WebhookDelivery", tenant_id=sub.tenant_id,
                )
                created.append(delivery)
                continue
            signature = crypto.compute_signature(secret, body)
            delivery = self._deliveries.create(
                tenant_id=sub.tenant_id, subscription_id=sub.id, partner_id=sub.partner_id,
                source_event_id=envelope.event_id, source_event_type=envelope.event_type,
                external_event_type=ext, aggregate_type=envelope.aggregate_type or None,
                aggregate_id=envelope.aggregate_id, status=WebhookDeliveryStatus.PENDING,
                payload=payload, payload_hash=payload_hash,
                signature=signature, next_attempt_at=utcnow(), attempt_count=0,
            )
            self._session.flush()
            self._emit(
                WebhookDeliveryCreated(delivery_id=delivery.id, tenant_id=sub.tenant_id,
                                       subscription_id=sub.id, source_event_id=envelope.event_id,
                                       external_event_type=ext),
                aggregate_id=delivery.id, aggregate_type="WebhookDelivery", tenant_id=sub.tenant_id,
            )
            created.append(delivery)
        return created

    def attempt_delivery(self, delivery_id, *, provider=None) -> "WebhookDelivery":  # noqa: F821
        """API/worker path: attempt one delivery via the provider port. Commits."""
        tenant_id = self._tenant_id()
        delivery = self._owned_delivery(delivery_id, tenant_id)
        if delivery.status in (WebhookDeliveryStatus.DELIVERED, WebhookDeliveryStatus.CANCELLED):
            raise ValidationError(f"Delivery in status '{self._ev(delivery.status)}' cannot be attempted.")
        sub = self._subs.get_by_id(delivery.subscription_id)
        if not delivery.signature:
            # M1: an unsigned delivery (secret was undecryptable at creation) must never be
            # sent. Try to (re)sign if the secret is now recoverable; otherwise record a
            # skipped attempt and leave it failed — no unsigned payload leaves the platform.
            secret = crypto.decrypt_secret(sub.encrypted_secret) if sub is not None else None
            if secret is None:
                self._attempts.create(
                    tenant_id=tenant_id, delivery_id=delivery.id,
                    attempt_number=self._attempts.next_attempt_number(delivery.id),
                    status=WebhookAttemptStatus.SKIPPED, requested_at=utcnow(), completed_at=utcnow(),
                    error_code="secret_undecryptable",
                    error_message="Subscription signing secret could not be decrypted; delivery not signed.",
                )
                delivery.status = WebhookDeliveryStatus.FAILED
                delivery.failed_at = utcnow()
                delivery.last_error = "secret_undecryptable"
                delivery.next_attempt_at = None
                self._session.flush()
                self._session.commit()
                self._session.refresh(delivery)
                return delivery
            # Secret recovered (e.g. secret was re-rotated): re-sign the stored payload.
            delivery.signature = crypto.compute_signature(secret, _canonical_body(delivery.payload))
            self._session.flush()
        provider = provider or get_webhook_provider()
        body = _canonical_body(delivery.payload)
        headers = {
            "Content-Type": "application/json",
            "X-Mesaar-Event": delivery.external_event_type,
            "X-Mesaar-Signature": delivery.signature,
            "X-Mesaar-Delivery": str(delivery.id),
        }
        timeout = sub.timeout_seconds if sub is not None else 10
        attempt_number = self._attempts.next_attempt_number(delivery.id)
        started = utcnow()
        delivery.status = WebhookDeliveryStatus.DELIVERING
        delivery.attempt_count = (delivery.attempt_count or 0) + 1
        delivery.last_attempt_at = started
        self._session.flush()

        result = provider.send(target_url=(sub.target_url if sub else ""), body=body,
                               headers=headers, timeout_seconds=timeout)

        attempt_status = (WebhookAttemptStatus.SUCCEEDED if result.succeeded
                          else (WebhookAttemptStatus.SKIPPED if result.error_code == "provider_not_configured"
                                else WebhookAttemptStatus.FAILED))
        self._attempts.create(
            tenant_id=tenant_id, delivery_id=delivery.id, attempt_number=attempt_number,
            status=attempt_status, requested_at=started, completed_at=utcnow(),
            http_status_code=result.http_status_code, response_body=result.response_body,
            error_code=result.error_code, error_message=result.error_message, duration_ms=result.duration_ms,
        )
        self._session.flush()
        self._emit(WebhookDeliveryAttempted(delivery_id=delivery.id, tenant_id=tenant_id,
                                            attempt_number=attempt_number, status=self._ev(attempt_status)),
                   aggregate_id=delivery.id, aggregate_type="WebhookDelivery", tenant_id=tenant_id)

        if result.succeeded:
            delivery.status = WebhookDeliveryStatus.DELIVERED
            delivery.delivered_at = utcnow()
            delivery.last_error = None
            delivery.next_attempt_at = None
            self._session.flush()
            self._emit(WebhookDeliverySucceeded(delivery_id=delivery.id, tenant_id=tenant_id,
                                                subscription_id=delivery.subscription_id),
                       aggregate_id=delivery.id, aggregate_type="WebhookDelivery", tenant_id=tenant_id)
        else:
            delivery.status = WebhookDeliveryStatus.FAILED
            delivery.failed_at = utcnow()
            delivery.last_error = (result.error_message or result.error_code or "delivery failed")[:1024]
            max_retries = sub.max_retries if sub is not None else 0
            delivery.next_attempt_at = utcnow() if delivery.attempt_count <= max_retries else None
            self._session.flush()
            self._emit(WebhookDeliveryFailed(delivery_id=delivery.id, tenant_id=tenant_id,
                                             subscription_id=delivery.subscription_id, reason=delivery.last_error),
                       aggregate_id=delivery.id, aggregate_type="WebhookDelivery", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(delivery)
        return delivery

    def retry_delivery(self, delivery_id, *, provider=None) -> "WebhookDelivery":  # noqa: F821
        tenant_id = self._tenant_id()
        delivery = self._owned_delivery(delivery_id, tenant_id)
        if delivery.status == WebhookDeliveryStatus.DELIVERED:
            raise ValidationError("A delivered webhook cannot be re-delivered.")
        if delivery.status == WebhookDeliveryStatus.CANCELLED:
            raise ValidationError("A cancelled webhook cannot be retried.")
        return self.attempt_delivery(delivery_id, provider=provider)

    def cancel_delivery(self, delivery_id) -> "WebhookDelivery":  # noqa: F821
        tenant_id = self._tenant_id()
        delivery = self._owned_delivery(delivery_id, tenant_id)
        if delivery.status == WebhookDeliveryStatus.DELIVERED:
            raise ValidationError("A delivered webhook cannot be cancelled.")
        if delivery.status == WebhookDeliveryStatus.CANCELLED:
            return delivery
        delivery.status = WebhookDeliveryStatus.CANCELLED
        delivery.next_attempt_at = None
        self._session.flush()
        self._session.commit()
        self._session.refresh(delivery)
        return delivery

    def _owned_delivery(self, delivery_id, tenant_id):
        delivery = self._deliveries.get_by_id(delivery_id)
        if delivery is None or delivery.tenant_id != tenant_id:
            raise NotFoundError(f"WebhookDelivery {delivery_id} not found.")
        return delivery

    def get_delivery(self, delivery_id) -> "WebhookDelivery":  # noqa: F821
        return self._owned_delivery(delivery_id, self._tenant_id())

    def list_deliveries(self, **kw):
        self._tenant_id()
        return self._deliveries.list_deliveries(**kw)

    def list_delivery_attempts(self, delivery_id):
        tenant_id = self._tenant_id()
        self._owned_delivery(delivery_id, tenant_id)
        return self._attempts.list_for_delivery(delivery_id)

    # ===================== Inbound events =====================

    def receive_inbound_event(self, *, partner_id, api_key_id, idempotency_key, event_type,
                              payload=None, signature_valid: bool) -> "InboundIntegrationEvent":  # noqa: F821
        """Persist + audit an authenticated inbound event. Idempotent per (api_key, key).

        A duplicate idempotency key returns the existing row (no double-process). An
        invalid signature is recorded as ``rejected``; a valid one as ``accepted``.
        """
        tenant_id = self._tenant_id()
        existing = self._inbound.find_by_idempotency(api_key_id, idempotency_key)
        if existing is not None:
            return existing
        now = utcnow()
        rejected = not signature_valid
        row = self._inbound.create(
            tenant_id=tenant_id, partner_id=partner_id, api_key_id=api_key_id,
            idempotency_key=idempotency_key, event_type=event_type, payload=payload,
            signature_valid=signature_valid,
            status=InboundEventStatus.REJECTED if rejected else InboundEventStatus.ACCEPTED,
            received_at=now, rejected_at=now if rejected else None,
            rejection_reason="invalid signature" if rejected else None,
        )
        self._session.flush()
        self._emit(InboundIntegrationEventReceived(inbound_event_id=row.id, tenant_id=tenant_id,
                                                   partner_id=partner_id, api_key_id=api_key_id,
                                                   inbound_type=event_type),
                   aggregate_id=row.id, aggregate_type="InboundIntegrationEvent", tenant_id=tenant_id)
        if rejected:
            self._emit(InboundIntegrationEventRejected(inbound_event_id=row.id, tenant_id=tenant_id,
                                                       partner_id=partner_id, reason="invalid signature"),
                       aggregate_id=row.id, aggregate_type="InboundIntegrationEvent", tenant_id=tenant_id)
        else:
            self._emit(InboundIntegrationEventAccepted(inbound_event_id=row.id, tenant_id=tenant_id,
                                                       partner_id=partner_id),
                       aggregate_id=row.id, aggregate_type="InboundIntegrationEvent", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(row)
        return row

    def process_inbound_event(self, inbound_event_id) -> "InboundIntegrationEvent":  # noqa: F821
        tenant_id = self._tenant_id()
        row = self._owned(self._inbound.get_by_id(inbound_event_id), tenant_id,
                          "InboundIntegrationEvent", inbound_event_id)
        if row.status not in (InboundEventStatus.ACCEPTED, InboundEventStatus.RECEIVED):
            raise ValidationError(f"Inbound event in status '{self._ev(row.status)}' cannot be processed.")
        row.status = InboundEventStatus.PROCESSED
        row.processed_at = utcnow()
        self._session.flush()
        self._session.commit()
        self._session.refresh(row)
        return row

    def reject_inbound_event(self, inbound_event_id, *, reason=None) -> "InboundIntegrationEvent":  # noqa: F821
        tenant_id = self._tenant_id()
        row = self._owned(self._inbound.get_by_id(inbound_event_id), tenant_id,
                          "InboundIntegrationEvent", inbound_event_id)
        row.status = InboundEventStatus.REJECTED
        row.rejected_at = utcnow()
        row.rejection_reason = (reason or "rejected")[:512]
        self._session.flush()
        self._emit(InboundIntegrationEventRejected(inbound_event_id=row.id, tenant_id=tenant_id,
                                                   partner_id=row.partner_id, reason=row.rejection_reason),
                   aggregate_id=row.id, aggregate_type="InboundIntegrationEvent", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(row)
        return row

    def list_inbound(self, **kw):
        self._tenant_id()
        return self._inbound.list_inbound(**kw)


__all__ = ["IntegrationService", "ApiKeyAuthContext"]
