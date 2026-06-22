# ADR-005 — API versioning & contract

- **Status:** Accepted (default)
- **Date:** 2026-06-20

## Context
Routes today are mounted **without a version prefix** (`/auth`, `/shipments`, …).
Two clients already consume the API (web consoles + the delivered driver app), so
breaking changes must be controlled.

## Decision
Introduce a **URI version prefix `/v1`** on a root `APIRouter`, keep FastAPI's
auto-generated OpenAPI as the contract, and add **contract tests** that fail CI on
incompatible changes. A typed, hand-curated spec lives at `api/openapi.yaml` and is
diffed against the runtime schema.

## Consequences
- (+) Clear deprecation path; `/v2` can coexist.
- (+) OpenAPI drives client SDK generation (driver app + consoles).
- (−) One-time route remount + client base-URL change (driver app already points at
  `/v1` via `EXPO_PUBLIC_API_URL`).

## Rules
- Additive changes (new optional fields/endpoints) stay in `/v1`.
- Breaking changes (removed/renamed fields, changed types) require `/v2`.
- Every endpoint declares `tags`, `summary`, response models, and error schema.
