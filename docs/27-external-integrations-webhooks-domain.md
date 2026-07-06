# 27 — External Integrations & Partner API / Webhooks (Sprint 13)

> Status: **IMPLEMENTED & VERIFIED**. Implements bounded context **#21 — External
> Integrations & Webhooks**. It lets external systems authenticate with tenant-scoped
> API keys, subscribe to selected (externally-named, sanitized) domain events, receive
> signed outbound webhooks, and POST audited inbound events. It is a **consumer**: it
> never mutates source aggregates and holds no integration logic inside Shipment,
> Billing, Claims, Notifications, or Analytics.

---

## 1. Domain purpose

Other domains emit events. Integrations *consumes* them and decides: which partner
subscriptions match, what sanitized payload to send, how it is signed, when delivery is
attempted, how retries are tracked, and how inbound payloads are authenticated and
audited. Partner-facing traffic is isolated behind its own API-key auth scheme —
separate from user JWT auth.

## 2. Data model

Six tenant-scoped tables (all RLS-guarded), migration `0016`:

| Table | Purpose | Lifecycle columns |
| --- | --- | --- |
| `integration_partners` | external partner | audit + soft-delete + version |
| `partner_api_keys` | tenant+partner API credential (bcrypt hash only) | created_by, revoked_at/by, last_used_at |
| `webhook_subscriptions` | event subscription + encrypted signing secret | audit + soft-delete + version |
| `webhook_deliveries` | one sanitized, signed outbound delivery | status machine + attempt bookkeeping |
| `webhook_delivery_attempts` | append-only attempt record | — |
| `inbound_integration_events` | audited inbound event | status machine |

Enums: `IntegrationPartnerType` (customer/carrier/vendor/government/internal/other),
`IntegrationPartnerStatus`, `ApiKeyStatus`, `WebhookSubscriptionStatus`,
`WebhookDeliveryStatus`, `WebhookAttemptStatus`, `InboundEventStatus`, `SigningAlgorithm`.

## 3. Partner + API-key model

- API key format `mesaar_<prefix>_<secret>`; only a **bcrypt hash** is stored, plus the
  non-secret `key_prefix` for display + O(1) lookup. Plaintext is returned **once**
  (create/rotate). `key_hash` is never returned by any read API.
- Authentication (`get_current_api_key_partner`): reads `Authorization: Bearer`, resolves
  the key under **platform scope** (the caller's tenant is unknown until the key
  resolves), verifies the hash (constant-time), rejects revoked/expired keys and
  suspended/inactive partners, stamps `last_used_at`, and binds the partner's tenant to
  the request context. Never replaces user JWT auth — used only on inbound endpoints.
- Rotation revokes the old key and mints a new one (new prefix + secret).
- `scopes` / `allowed_ips` are persisted for forward use; scope + IP **enforcement** is
  reserved (see Known risks).

## 4. Webhook subscription lifecycle

`create → active ⇄ inactive`, soft-delete. Rules: `target_url` must be `https` (http
allowed only under an explicit dev/test flag); `event_types` non-empty and validated
against the external allow-list; inactive subscriptions and suspended-partner
subscriptions receive nothing; the signing secret is never returned by reads and is
rotatable (one-time reveal on create/rotate).

## 5. Outbound webhook flow

1. Notifications + analytics consumers keep working (independent idempotency keys).
2. The `webhooks` consumer (`BaseEventHandler`, runs in the dispatcher SAVEPOINT, **no
   commit**) receives a mapped internal event.
3. It maps internal → external name (`ShipmentDelivered → shipment.delivered`).
4. It finds active subscriptions for `(tenant, external_type)` whose partner is active.
5. It **sanitizes** the payload (whitelist, deny-by-default — internal `tenant_id`,
   free-text `reason`/`notes`, etc. are dropped).
6. It creates `webhook_deliveries` **idempotently** (unique
   `(tenant_id, subscription_id, source_event_id)` + pre-check) — one delivery per
   subscription per source event, even under replay.
7. It signs the canonical JSON body with the subscription's decrypted secret and marks
   the delivery `pending`. Source-domain commits are never blocked.
8. `attempt_delivery` (API/worker path) sends via a **provider port**. The default
   `NoNetworkWebhookProvider` performs **no network call and never fakes success** — it
   records a `skipped` attempt with `provider_not_configured`. A real HTTP provider is
   registered via `set_webhook_provider`; it is timeout-bounded and fully mockable.

Delivery status machine: `pending → delivering → {delivered, failed}`;
`pending/failed → cancelled`. **Delivered** deliveries cannot be re-delivered;
**cancelled** cannot be retried; **failed** can be retried. Each attempt is an
append-only `webhook_delivery_attempts` row.

## 6. Inbound integration flow

`POST /integrations/inbound/events` (API-key auth). The partner sends
`Authorization: Bearer <api_key>`, `X-Mesaar-Signature`, optional `X-Mesaar-Timestamp`,
and a JSON body with `idempotency_key`, `event_type`, `payload`. The service:
authenticates the key, verifies the signature (see §7), and persists an
`inbound_integration_events` row — `accepted` for a valid signature, `rejected` for an
invalid one (still audited). Idempotency is enforced by unique
`(tenant_id, api_key_id, idempotency_key)`; a duplicate returns the existing row and
does **not** double-process. `process_inbound_event` / `reject_inbound_event` advance the
lifecycle.

## 7. HMAC signing

`app/integrations/crypto.py`. Algorithm **HMAC-SHA256**. `compute_signature` →
`sha256=<hex>` over `[timestamp.]body`; `verify_signature` uses `hmac.compare_digest`
(constant-time). Headers: `X-Mesaar-Signature`, `X-Mesaar-Timestamp` (binds send time so
a replay window can be enforced by the receiver).

- **Outbound** payloads are signed with the per-subscription secret, stored **encrypted
  at rest** (Fernet, key derived from `SECRET_KEY`) because signing needs the value; the
  secret is decrypted only to sign and is never returned by reads.
- **Inbound** signatures are verified using the *presented plaintext API key* as the
  shared HMAC secret — available in-request, so at-rest storage stays hash-only (no
  second secret store).

## 8. Rate-limit policy

`RateLimitPolicy` — a fixed-window limiter scoped to `tenant:api_key`, with a pluggable
backend. It **is enforced on the inbound endpoint** (`POST /integrations/inbound/events`):
the limit is applied *after* successful API-key authentication, using tenant + api_key
from the authenticated key context (never the client), and an exceeded key receives a
clean `429` with a `Retry-After` header. Another API key has its own bucket and is
unaffected.

The default `InMemoryRateLimitBackend` is **process-local** (single-process) and
deterministic (injectable clock; test-covered). **Distributed** enforcement across worker
processes requires a Redis-backed backend with the same interface (Redis is already wired
via `get_redis`) — that is the documented production path, **deferred to Sprint 14**. The
limiter is overridable via `set_inbound_rate_limiter` for deployment tuning/tests.

## 9. Idempotency strategy

- **Outbound**: unique `(tenant_id, subscription_id, source_event_id)` + a pre-check in
  the consumer; the dispatcher's own `processed_events` (`name="webhooks"`) guarantees
  each source event is consumed once. A replayed source event creates zero new deliveries.
- **Inbound**: unique `(tenant_id, api_key_id, idempotency_key)`; duplicates are no-ops.

## 10. Retry strategy

Each subscription carries `max_retries` + `timeout_seconds`. On failure the delivery is
`failed` with `next_attempt_at` set while attempts remain (retry-eligible), or terminal
once exhausted. `retry_delivery` re-attempts a failed delivery; a repository `list_due`
surfaces pending/failed deliveries for a future scheduled sweep worker.

## 11. Security model & tenant isolation

- `tenant_id` is never accepted from the client; it comes from the JWT (management) or
  the API key (inbound).
- All six tables enforce PostgreSQL RLS (`_enable_rls`, guarded by `_is_postgres`).
- Read schemas never expose `key_hash` or webhook secrets; plaintext key / secret appear
  only in one-time create/rotate responses.
- Management endpoints: ADMIN/MANAGER; secret **revoke/rotate**: ADMIN only.
- Outbound payloads are whitelist-sanitized; no raw internal payload or notification body
  is ever exposed.

## 12. API contract

Router `/integrations` (20 paths). Partners (CRUD + activate/suspend + search),
API keys (create/list/revoke/rotate), webhook subscriptions (CRUD + activate/deactivate +
rotate-secret + search), deliveries (list/get/retry/cancel/attempts), and the single
inbound endpoint. Literal paths precede dynamic ones; routes are thin.

## 13. Externally-publishable events

The internal→external map (`app/integrations/event_mapping.py`) is the single source of
truth for what may leave the platform:

| Internal | External |
| --- | --- |
| Shipment{Created,Assigned,InTransit,Delayed,Delivered,Failed,Cancelled} | `shipment.*` |
| DispatchBlockedByCompliance / DispatchClearedByCompliance | `compliance.dispatch_{blocked,cleared}` |
| Permit{Approved,Rejected,Expired} | `permit.{approved,rejected,expired}` |
| Claim{Created,Approved,Rejected,Settled} | `claim.*` |
| InvoiceIssued / InvoicePaid / PaymentFailed / Settlement{Approved,Settled} | `invoice.*`, `payment.failed`, `settlement.*` |
| NotificationFailed | `notification.failed` |

Any internal event not in this map is ignored by the consumer. `projection.health_stale`
was intentionally **not** exposed (no corresponding internal domain event exists to key
it safely).

## 14. Migration summary

`0016_external_integrations_webhooks_domain` (down_revision `0015`): additive only;
named PK/FK/unique/check constraints; indexes on FK/status/lookup columns; JSONB fields;
RLS guarded by `_is_postgres()`; reversible downgrade. No source-domain table modified.
Single linear head.

## 15. Test summary

11 suites (model, events, repository, service, routes, security, signing, handlers,
delivery, inbound, idempotency) — **70 tests**, ~92% coverage of the new modules.
Security assertions: no `key_hash`/secret leakage, plaintext only on create/rotate,
revoked/expired/suspended cannot authenticate, invalid inbound signature rejected,
duplicate idempotency key does not double-process, cross-tenant partner/subscription
reads raise NotFound. Full suite: **1432 passed, 13 skipped**; OpenAPI builds (182 paths);
alembic single head `0016`.

## 16. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Webhook secret encrypted at rest with a key **derived from `SECRET_KEY`** (not a dedicated KMS key). | MEDIUM | Reversible encryption is required to sign; a KMS/envelope-encryption key is the recommended hardening follow-up. Secret is never returned by reads. **If a secret becomes undecryptable (e.g. key rotation), the consumer never signs with an empty secret** — it records a `FAILED`, unsigned delivery + a `skipped` attempt (`secret_undecryptable`), and a manual retry re-signs only if the secret is recoverable, otherwise stays failed. |
| `scopes` and `allowed_ips` are persisted but **not yet enforced** (enforcement deferred to Sprint 14). | LOW | Reserved for a follow-up; documented here and in the schema. |
| Inbound **replay-window** enforcement (rejecting stale `X-Mesaar-Timestamp`) is **deferred to Sprint 14**. | LOW | The timestamp is bound into the signature today; time-based rejection is the follow-up. |
| Rate limiting is **enforced on inbound** with a **process-local** default backend. | LOW | Correct for single-process/tests; distributed enforcement (Redis backend, same interface) is deferred to Sprint 14. |
| `list_active_for_event` loads active subs per tenant and filters JSONB membership in Python. | LOW | Fine at current scale; a JSONB containment index / GIN query is the follow-up for very large subscription sets. |
| API-key prefix lookup takes the first match (per-tenant unique; ~2^48 cross-tenant collision). | LOW | On the astronomically-unlikely collision the hash simply fails to verify → key rejected; no cross-tenant leak. |
| Real outbound HTTP delivery is behind a port with a **no-network default**. | LOW | By design — no silent success; a real provider is registered per deployment and is timeout-bounded. |

---

## Sprint 14 — delivery worker & hardening

The deferred production-hardening items in this doc's known-risks are addressed in Sprint 14 (docs/28): a real `HttpWebhookProvider` behind the delivery port, a celery-beat delivery-retry **sweep** with bounded exponential backoff, a KMS-ready `SecretEncryptionProvider` boundary (default `LocalFernetSecretProvider`), enforced API-key **scopes** + **allowed_ips**, inbound **replay-window** validation (mandatory `X-Mesaar-Timestamp`, ±300 s), and a `RedisRateLimitBackend`. Real HTTP delivery, distributed rate limiting, and KMS remain opt-in at deployment (defaults stay no-network / in-memory / local-Fernet) — see docs/28 runbook.
