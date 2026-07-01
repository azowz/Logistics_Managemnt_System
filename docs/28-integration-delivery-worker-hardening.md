# 28 — Integration Delivery Worker & Hardening (Sprint 14)

> Status: **IMPLEMENTED & VERIFIED**. Production-hardening for the External Integrations
> context (docs/27). It adds a real HTTP webhook provider, a scheduled delivery-retry
> sweep with exponential backoff, a KMS-ready secret-encryption boundary, and enforcement
> of the fields Sprint 13 only persisted (scopes, allowed-IPs) plus inbound replay-window
> validation and a Redis-backed rate-limit backend. Domain boundaries are unchanged: the
> context stays a consumer, never mutates source aggregates, and never exposes secrets or
> raw internal payloads.

---

## 1. Real HTTP webhook provider

`HttpWebhookProvider` (`app/integrations/delivery.py`, httpx) sits behind the existing
`WebhookDeliveryProvider` port. It POSTs the signed JSON body to the subscription's
`target_url` with headers `X-Mesaar-Event`, `X-Mesaar-Delivery-Id`, `X-Mesaar-Signature`,
`X-Mesaar-Idempotency-Key` (= source event id), and a configurable `User-Agent`. It maps
**2xx → success**, **4xx/5xx → failure**, **timeout → `timeout`**, **connection error →
`connection_error`**; response bodies are **truncated to 2 KB**; it performs **no internal
retry** (retry is the worker's job) and never logs or returns the signing secret. An httpx
client is injectable for tests (MockTransport → no network).

**Default provider stays `NoNetworkWebhookProvider`** (never sends, never fakes success).
A deployment activates real delivery by calling
`set_webhook_provider(HttpWebhookProvider())` at startup.

## 2. Delivery retry sweep

`app/integrations/sweep.py::run_webhook_delivery_sweep` + celery task
`mesaar.webhook_delivery_sweep` on celery-beat every **60 s** (`expires=55`, overlap-
guarded). It mirrors the relay/health sweeps: the tenant list is read under platform
scope, each delivery is attempted inside that tenant's own RLS-scoped transaction (short
transactions — no DB txn held across the HTTP call), and each delivery is isolated in its
own try/except so one bad row can't stall the sweep. It is **non-destructive** (never
replays/rebuilds the event store) and idempotent. `list_due` returns only
`pending`/`failed` deliveries with `next_attempt_at <= now`, so delivered/cancelled/skipped
and retry-exhausted rows (`next_attempt_at = NULL`) are excluded — no double-send.

## 3. Retry / backoff policy

On failure a delivery is scheduled with **bounded exponential backoff**
`next_attempt_at = now + min(3600, 30·2^(n-1))` while `attempt_count <= max_retries`, or
becomes terminal (`next_attempt_at = NULL`) once retries are exhausted. `max_retries` and
`timeout_seconds` come from the subscription. Delivered deliveries set `delivered_at`;
delivered/cancelled cannot be retried; an unsigned (`secret_undecryptable`) delivery is
never sent (Sprint 13 M1 — the guard re-signs only if the secret is recoverable).

## 4. Secret-encryption provider boundary (KMS-ready)

`app/integrations/encryption.py` introduces `SecretEncryptionProvider` (port) with
`encrypt` / `decrypt` + `provider_name` / `key_id`. The default `LocalFernetSecretProvider`
wraps the existing Fernet helper; the active provider + key fingerprint are persisted on
`webhook_subscriptions` (`encryption_provider`, `encryption_key_id`) so a key rotation /
KMS migration is auditable. Decrypt failures return `None` (fail-safe — a delivery is never
signed with an empty secret). **KMS is documented as the production hardening path**: a
`KmsSecretProvider` would implement the same port against the deployment's KMS and be
installed via `set_secret_provider(...)` — it is **not faked** here. Secrets/ciphertext are
never returned by read schemas.

## 5. API-key scope enforcement

Scopes (`integrations:inbound:write`, `:deliveries:read`, `:webhooks:read`,
`:webhooks:write`) are validated against the known set at key creation and enforced by
`require_api_key_scopes(...)`. The inbound endpoint requires `integrations:inbound:write`
(403 if absent). Revoked/expired/suspended keys are rejected (401) before scope checks.
Scopes never override tenant/RLS. Management endpoints stay on user JWT + ADMIN/MANAGER;
there are no partner-API-key read endpoints yet, so `:read`/`:webhooks:*` scopes are
defined and reserved for when partner-facing reads are exposed.

## 6. Allowed-IP enforcement

If a key's `allowed_ips` is set, the request source IP must match (exact IP or CIDR, via
`ipaddress`); empty/null allows any source. Enforced in the auth dependency using
`request.client.host` (**`X-Forwarded-For` is not trusted by default** — honour it only
behind a configured trusted proxy, a deployment concern). Invalid entries are rejected at
key creation; a mismatch returns **403** (the key is already authenticated — this is an
authorization decision, not existence disclosure).

## 7. Inbound replay-window enforcement

The inbound endpoint now **requires** `X-Mesaar-Timestamp` (integer Unix seconds), which is
bound into the HMAC signing input. Requests outside ±**300 s** are rejected (**401**);
missing/malformed timestamps are 4xx. The idempotency key still prevents duplicate
processing. This is a **behavior change** from Sprint 13 (timestamp was optional).

## 8. Redis-backed rate-limit backend

`RedisRateLimitBackend` (atomic `INCR` + `EXPIRE`) implements the existing pluggable
backend interface, scoped to `tenant:api_key`. **Fail-open (availability mode) by
default**: on a Redis error it logs and treats the request as under-limit so an outage
never blocks partner traffic; `fail_open=False` gives fail-closed. The in-memory backend
remains the tested default. **The default process limiter is still in-memory** — a
deployment enables distributed enforcement via
`set_inbound_rate_limiter(RateLimitPolicy(backend=RedisRateLimitBackend(...)))`.

## 9. Delivery observability

`GET /integrations/webhooks/deliveries/due` (ADMIN/MANAGER) surfaces deliveries currently
due for a (re)attempt. Delivery reads already expose `status`, `attempt_count`,
`next_attempt_at`, `last_error`, and per-attempt `http_status_code`; the existing list
endpoint filters by status / event-type / subscription. Subscription reads now show the
(non-secret) `encryption_provider` / `encryption_key_id`. No secret or raw internal payload
is exposed. A composite index `webhook_deliveries(status, next_attempt_at)` backs the sweep.

## 10. Migration

`0017_integration_delivery_worker_hardening` (down_revision `0016`) — **additive only**:
`webhook_subscriptions.encryption_provider` + `encryption_key_id`; the composite sweep
index. No source-domain table touched; reversible downgrade; SQLite-compatible. Single
linear head.

## 11. Operational runbook

- **Enable real delivery:** at worker/app startup call `set_webhook_provider(HttpWebhookProvider())`.
- **Enable distributed rate limiting:** `set_inbound_rate_limiter(RateLimitPolicy(limit=..., window_seconds=..., backend=RedisRateLimitBackend(window_seconds=...)))`.
- **KMS secrets:** implement `KmsSecretProvider(SecretEncryptionProvider)` and `set_secret_provider(...)`; rotate by re-issuing subscription secrets (rotate-secret) under the new provider.
- **Sweep:** celery-beat runs `mesaar.webhook_delivery_sweep` every 60 s; monitor its `{attempted, delivered, failed, errors}` summary and `GET .../deliveries/due`.
- **Stuck deliveries:** `secret_undecryptable` deliveries are `failed` with `next_attempt_at = NULL` — fix the key (rotate-secret) then manual `retry`.

## 12. Test summary

New suites: `test_webhook_http_provider.py` (2xx/4xx/5xx/timeout/connect-error/truncation/no-retry),
`test_webhook_delivery_sweep.py` (per-tenant delivery, failure+backoff, no-double-send,
per-delivery isolation), `test_secret_encryption.py` (boundary, decrypt-fail, rotation,
swappable provider, no leak), `test_integration_hardening.py` (scope/IP validation +
matching, backoff, Redis backend count/fail-open/fail-closed/get_redis). Route tests add
scope-missing 403, replay-window (missing/malformed/stale/future), and allowed-IP
enforcement. **Full suite: 1461 passed, 13 skipped**; OpenAPI 183 paths; alembic single
head `0017`. ~90% coverage of the integration modules.

## 13. Known risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Partner-controlled `target_url` enables SSRF (webhook posts to a partner-specified host). | MEDIUM | https-only validation (Sprint 13) limits scheme; private-IP/link-local blocking + egress allow-listing is the recommended follow-up (Sprint 15). |
| Real HTTP delivery + distributed rate limiting + KMS are **opt-in at deployment** (defaults stay no-network / in-memory / local-Fernet). | LOW | Intentional — no silent send, no unverified distributed claim; wiring is a documented startup step (runbook §11). |
| Fernet key still derived from `SECRET_KEY` in the default provider. | LOW | Boundary now allows a clean KMS swap; `encryption_key_id` makes rotation auditable. |
| Redis rate-limit backend fails **open** on outage. | LOW | Availability-mode by design (documented); `fail_open=False` available for high-security deployments. |
| `X-Forwarded-For` is not trusted (uses socket peer). | LOW | Correct default; trusted-proxy handling is a deployment/config follow-up. |
