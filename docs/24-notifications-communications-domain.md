# 24 — Notifications & Communications Domain (Sprint 10)

> Status: **IMPLEMENTED & VERIFIED**. Implements bounded context **#19 —
> Notifications & Communications**. Turns operational domain events into
> tenant-aware, auditable communication: templates, notifications, and
> per-channel delivery attempts.

---

## 1. Domain purpose

Consumes operational events from every other context (Shipment, Compliance,
Insurance & Claims, Billing) and decides **who** to notify, **which channel** to
use, **which template** to render, **what** to send, **how delivery is tracked**,
and **how idempotency/retry** are enforced. Notifications never mutate source
aggregates; recipients and source events are referenced by id/contact only.

## 2. Aggregate ownership

| Concern | Owner |
| --- | --- |
| Templates | `NotificationTemplate` (`app/models/notification.py`) |
| Notifications | `Notification` + `NotificationStateMachine` (`app/services/notification_policies.py`) |
| Delivery attempts | `NotificationDeliveryAttempt` (immutable child) |
| Service | `NotificationService` (API path commits; consumer path never commits) |
| Repositories | `app/repositories/notification_repository.py` (3) |
| Events | `app/events/notification_events.py` (12) |
| Channel providers | `app/notifications/providers.py` |
| Event consumer | `app/notifications/handlers.py` (`NotificationEventHandler`) |
| API / Schemas | `app/api/routes/notifications.py`, `app/schemas/notification.py` |

## 3. Notification lifecycle

```
pending → queued → sent
{pending, queued} → cancelled
{queued, sent} → failed
sent → read
failed → queued        (retry)
```
Terminal: `cancelled`, `read`. Rules (`NotificationService`): a cancelled
notification cannot be sent; an already-sent/read notification cannot be re-sent
(use retry for a failed one); `mark_read` is idempotent (a read notification is
not re-marked); a failed notification can be retried (status → queued → delivery).

## 4. Template rendering

`TemplateRenderer` (dependency-free `str.format_map`) renders `{variable}`
placeholders. Required variables declared in a template's `variables_schema`
(`{"required": [...]}`) are validated before rendering, so a misconfigured
template fails loudly rather than emitting a half-rendered message. Unknown
placeholders are left intact; malformed format strings raise `ValidationError`.
When no active template exists for `(event_type, channel)`, a safe built-in
default is rendered so event-driven triggers fire out-of-the-box.

## 5. Event-driven triggers

`NotificationEventHandler` (consumer name `notifications`) subscribes to 22
operational events and creates one in-app notification per event:

- **Shipment**: Assigned, PickedUp, InTransit, Delayed, Delivered, Failed, Returned, Cancelled.
- **Compliance**: DispatchBlockedByCompliance, DispatchClearedByCompliance, PermitApproved, PermitRejected, PermitExpired.
- **Insurance & Claims**: ClaimCreated, ClaimApproved, ClaimRejected, ClaimSettled.
- **Billing**: InvoiceIssued, InvoicePaid, PaymentFailed, SettlementApproved, SettlementSettled.

The handler never re-notifies its own (`Notification*`) events. **Recipient
resolution (Sprint 10)** targets the event's actor (`envelope.user_id`); if no
actor is present the trigger is skipped (no target-less rows). Richer routing
(notify the shipment's client / invoice's customer / assignee) is a documented
follow-up.

## 6. Channel abstraction

Provider ports resolve per channel via `ProviderRegistry`:

- **In-app** (`InAppNotificationProvider`) — fully implemented; delivery is the
  persisted row + read-tracking, so a send succeeds synchronously.
- **Email / SMS / Push / Webhook** — null adapters: `is_configured()` is `False`
  and `send()` returns a `skipped` result with `provider_not_configured`. They
  **never** report success and make **no** network call; a real adapter is wired
  in later by registering it for the channel. No paid vendor SDK is imported.

A missing provider for a channel yields a `skipped`/`no_provider` attempt and
marks the notification **failed** — never a silent success.

## 7. Idempotency strategy

Two independent layers:

1. **Consumer-level** — the event `Dispatcher` records `(consumer="notifications",
   event_id)` in `processed_events` inside the handler's SAVEPOINT; a replayed
   envelope is skipped entirely (effectively-once).
2. **Domain-level** — each notification carries an `idempotency_key`
   (`{event_id}:{channel}:{recipient}`) with a unique constraint
   `(tenant_id, idempotency_key)`; `enforce_idempotency` checks it before insert.
   This prevents duplicates even if the consumer guard is bypassed (e.g. manual
   replay), and survives a fan-out of multiple recipients per event.

## 8. Delivery attempts

Every send (in-app, retry, or skipped/failed external channel) records a
`NotificationDeliveryAttempt` with channel, provider, status, attempt number,
provider message id, error code/message, and response payload — the durable
audit trail. `NotificationDeliveryAttemptCreated` is emitted per attempt.

## 9. Retry policy

A `failed` notification transitions `failed → queued` (emitting
`NotificationRetried`) and is re-delivered, incrementing `retry_count` and
recording a new attempt. `NotificationRepository.list_failed_retryable(max_retries)`
selects rows for a scheduled retry sweep (worker follow-up).

## 10. API contract

Templates: `POST/GET /notifications/templates`, `GET .../search`,
`GET/PATCH/DELETE .../{id}`, `restore/activate/deactivate`. Notifications:
`POST/GET /notifications`, `GET .../search`, `GET .../unread`, `GET .../{id}`,
`queue/send/retry/cancel/read`, `GET .../{id}/attempts`. Literal paths precede
`{id}`; routes are thin with RBAC.

## 11. Worker integration

The platform already runs the outbox relay (`run_outbox_relay`) which publishes
each stored event through `default_bus` to registered handlers; the `Dispatcher`
provides idempotency + SAVEPOINT isolation + retry + dead-lettering and commits
the handler's writes with the `processed_events` record. The notification
consumer is wired by calling `register_notification_handlers(default_bus)` at the
worker/relay bootstrap. The handler runs **inside the dispatcher's transaction
and never commits** — async processing is real, not faked.

## 12. Provider configuration

Channels map to providers in `default_provider_registry`. To enable a real
email/SMS/push/webhook integration, register an adapter implementing the
`NotificationProvider` port (`channel`, `name`, `is_configured()`, `send()`) for
that channel; until then the null adapter records a clear `skipped` attempt.

## 13. Security model & tenant isolation

`tenant_id` from context only (never client-supplied); RLS on all 3 tables;
recipient `user_id` validated tenant-owned; per-tenant unique template codes and
idempotency keys; write = ADMIN/MANAGER, read + mark-read add CLIENT/DRIVER,
delete/restore = ADMIN; recipient email/phone format validated; optimistic
locking via `version`.

## 14. Migration summary

`0013_notifications_communications_domain` (down_revision `0012`, single head) —
additive: creates `notification_templates`, `notifications`,
`notification_delivery_attempts` with named PK/FK/unique/check constraints,
soft-delete + audit + `version`, JSONB (`variables_schema`, `metadata`,
`response_payload`), indexes, the `(tenant_id, idempotency_key)` idempotency
unique, and RLS. The regex email CHECK and RLS are PG-only (`_is_postgres()`);
reversible (3 create / 3 drop). No existing table is modified.

## 15. Test summary

Nine suites (`test_notifications_{model,events,repository,service,routes}.py`,
`test_notification_{template_rendering,event_handlers,delivery,idempotency}.py`),
**96% coverage** of the notification modules (events/model/policies/handlers
100%, providers 98%, repository 96%, service 96%, routes 94%, schemas 93%).
Idempotency is proven at both the domain level and via the real `Dispatcher`.
Full regression: **1278 passed, 13 skipped**.

## 16. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Recipient routing targets the event actor only (not the shipment client / invoice customer / assignee). | MEDIUM | `resolve_recipients` is the single seam; richer per-event routing is a follow-up. |
| Email/SMS/Push/Webhook are null adapters (no real delivery). | MEDIUM | Provider ports + registry are in place; register a real adapter per channel to enable. |
| `register_notification_handlers` must be called at worker/relay bootstrap to activate event-driven notifications. | LOW | Documented; the API path and handler are fully tested independently. |
| Scheduled retry/overdue sweep not wired (manual retry only). | LOW | `list_failed_retryable` exists; a celery-beat sweep (ADR-003) is a follow-up. |
| Template rendering is `str.format`-based (no logic/loops/i18n catalogs). | LOW | Sufficient for transactional messages; a richer engine can replace `TemplateRenderer`. |
