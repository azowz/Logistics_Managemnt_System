# Mesaar frontend/backend separation report

Completed and verified: **2026-11-11** (Asia/Riyadh).

The repository now contains independently runnable, buildable and deployable
`mesaar-backend/` and `mesaar-frontend/` applications. The existing backend and Expo
frontend were preserved. No business rule, database schema, historical migration,
or existing HTTP API contract was changed to accomplish the separation.

**Verdict:** separation is implemented and verified, with no known critical
separation-related regression. This is **not** a declaration of enterprise production
readiness: pre-existing security/product debts and unverified native releases remain.

## Original architecture and audit

- Root FastAPI modular monolith: 168 Python modules, SQLAlchemy/PostgreSQL, 19 Alembic
  revisions, Redis, Celery/Beat, domain services/policies, repositories, schemas,
  transactional outbox/audit, consumers, analytics projections, and webhooks.
- `mobile/`: Expo 51 / React Native 0.74 / React 18 / TypeScript / Expo Router with
  React Context and AsyncStorage. Three Arabic RTL screens and existing UI components.
- No implemented separate operations web dashboard, React web framework, or
  backend-served frontend assets were present. Documented planned components were
  not assumed to exist.
- Runtime imports were already separate; root deployment/configuration and the
  incomplete client adapters prevented the requested independent application layout.
- Live frontend login threw 501; snake_case backend data was consumed as camelCase;
  a 204 decline response was parsed as JSON; protected deep links invented a mock
  driver; a local 15-second timer could dismiss live/loading offer screens.
- Existing uncommitted work was present before this task. It was preserved in a
  source snapshot and in the migrated application files. No reset, clean, staging,
  commit, or deployment to a remote service was performed.
- Requested numbered documents were inspected at their existing archived locations.
  Current architecture/database/API/status/readiness references and actual source
  were used to distinguish implemented behavior from older design milestones.

The full [architecture inventory and diagrams](docs/separation-architecture.md)
cover domain/services/workers/integrations and original/final dependency maps.

## Final architecture and deliverables

| Deliverable | Location / behavior |
| --- | --- |
| Backend application | [mesaar-backend](mesaar-backend/): same `app` package, migrations, tests, requirements, pyproject, Dockerfile, own Compose and environment |
| Frontend application | [mesaar-frontend](mesaar-frontend/): existing Expo routes/components, own package/lock/environment/tests/Dockerfile/static server |
| Backend startup/tests/build/deployment | [Backend README](mesaar-backend/README.md) |
| Frontend startup/tests/build/deployment | [Frontend README](mesaar-frontend/README.md) |
| Workspace orchestration | [docker-compose.yml](docker-compose.yml), independent service startup; frontend has no API `depends_on` |
| Disposable verification orchestration | [compose.verify.yml](compose.verify.yml), explicit separate project, images, ports, and volumes |
| API release artifact | [contracts/openapi.json](contracts/openapi.json); backend export and frontend-owned vendored copy |
| Generated frontend API types/client | [generated.ts](mesaar-frontend/src/api/generated.ts), [client.ts](mesaar-frontend/src/api/client.ts), [driverApi.ts](mesaar-frontend/src/api/driverApi.ts) |
| Contract gate | Backend snapshot/baseline compatibility tests and command; frontend generated-type check; CI distribution comparison |
| Independent CI jobs | Backend, frontend, contract distribution and disposable live integration in [.github/workflows/ci.yml](.github/workflows/ci.yml) |
| Migration and rollback | [Instructions](docs/separation-migration.md) |
| Detailed moved/changed file manifest | [separation-file-map.json](docs/separation-file-map.json): old/new paths and SHA-256 hashes |

Neither application imports runtime code from its sibling or parent. Frontend builds
use a local contract artifact and never fetch the backend schema during installation
or build. Backend's image contains neither Node.js nor frontend assets. Frontend's
runtime is an unprivileged static nginx server. Each application can be copied out
and built with its own directory as Docker context, as actually exercised here.

## Files moved or modified

**369 original source/configuration/assets files** were mapped to replacement paths
and verified before retiring their old locations. **25 replacement files** differ
from their original bytes; all others are preserved. All **19 migration revisions**
remain byte-identical. The manifest lists every original/replacement hash.

- Root `app`, `migrations`, `tests`, `api`, `docker`, Python manifests, Alembic/pytest
  configuration, Dockerfile and dockerignore → backend.
- `mobile` routes/source/assets/configuration/package/lock → frontend.
- Backend runtime changes are limited to explicit local CORS defaults, middleware
  ordering, and exposing the existing request-ID header to browser clients.
- Backend adds package build metadata, contract export/check commands and three
  regression tests. Requirements explicitly pin the existing local Kombu version.
- Frontend adds web dependencies/build/server/container support, generated API types,
  typed endpoint methods/bodies/responses, live adapters, error/204 handling, route
  protection, visible demo mode, JWT password login using the existing endpoint,
  session handling, and offline/loading/empty states. Existing styles/screens remain.
- Root Compose, README, Makefile, environment example, CI, current documentation links,
  and screen/status references were updated. Root configuration is optional tooling.
- Root's private `.env` was left untouched and privately copied to backend `.env`;
  no secret was printed, committed, or copied into frontend configuration/images.

Original source, including the old mobile dependency/cache directory, is retained
outside the checkout at
`C:/Users/abdul/AppData/Local/Temp/mesaar-separation-praqicln/legacy/`.
The pre-change source ZIP and OpenAPI are in that same backup directory. This keeps
one authoritative source tree per application while retaining local rollback material.

## Dependencies removed or constrained

No existing runtime technology or business library was removed. Python dependencies
belong to backend; npm dependencies belong to frontend. The frontend adds SDK51-compatible
`react-dom` and `react-native-web`, plus local contract/test tooling.

The first fresh container installation exposed a previously unbounded transitive
dependency: Kombu 5.7.0 rejected pinned Redis client 5.0.7 and restarted workers/Beat.
`kombu==5.6.2` now preserves the locally installed baseline version. Rebuilt containers
successfully start and process tasks. No Redis/Celery major-version migration was made.

## API compatibility and communication

- Pre-separation and final OpenAPI: **183 paths, 204 schemas**, with unchanged
  existing operations, request/response schemas, methods, JWT security definitions,
  and `/v1` paths. Exported backend, root distribution, and frontend copies match.
- `python -m scripts.check_contract` and regression tests passed. The conservative
  gate allows new endpoints/components but rejects modifications/removals of existing
  ones, including some additive changes that require review. CI also detects stale
  generated frontend types and divergent distributed schemas.
- Requests retain JWT bearer headers and request IDs. Browser code can read the
  response request ID. Backend remains authoritative for tenant context/RBAC.
- Client supports FastAPI detail errors, validation details, domain error envelopes,
  network failures/timeouts, 401/403 and empty 204 responses. No automatic mutation
  retry can duplicate business actions.
- Existing pagination, filters, sorting, UUIDs, decimal representations, and date
  schemas remain defined by OpenAPI. The current driver offer endpoint returns a list.
- Missing live API fields (coordinates, company ratings, offer deadline/duration)
  are displayed as unavailable or omitted. No fabricated production values fill them.

## Security validation and authentication review

| Control | Evidence / outcome |
| --- | --- |
| RLS and transaction tenant context | Existing PostgreSQL isolation/GUC tests pass; test role verified `NOSUPERUSER NOBYPASSRLS` |
| Docker application role | Actual PostgreSQL16 role query: `mesaar_app`, `rolsuper=false`, `rolbypassrls=false` |
| Auth/RBAC/tenant claims | Existing full backend auth/context/security tests pass; live browser uses issued JWTs, with no dependency overrides |
| API authentication compatibility | Existing email/password/tenant_slug, refresh and logout backend contracts unchanged; frontend uses these contracts |
| Phone login | Production 501 gate preserved; OTP was not bypassed or replaced |
| Unauthenticated frontend navigation | Protected driver routes redirect to login; no mock profile fallback |
| Demo data | Explicit development-only opt-in with Arabic banner; production disables it; storage separated by API URL/demo mode |
| Browser CORS | Allowed preflight succeeds; unauthorized origins rejected; auth errors include CORS and expose request ID |
| Domain/security invariants | Existing state-machine, compliance dispatch, concurrency, tenant, event/audit/outbox suites pass |
| Secrets and boundaries | Frontend public configuration contains no DB/Redis/server credentials; backend image verified without Node or frontend assets |

Backend token creation/validation semantics and authorization were not changed.
Frontend session storage retains the pre-existing AsyncStorage approach, now scoped
by API URL/mode and cleared on expiry/logout; standard login also retains its refresh
token for server logout. The client does not automatically rotate refresh tokens;
expired sessions reauthenticate. Browser XSS/native token-storage hardening remains
production work; this review does not claim AsyncStorage is hardened secret storage.

## Executed validation results

Host: Windows, Python **3.12.10**, Node **22.17.0**. Container backend: Python **3.11**;
container frontend build: Node22. Tests used a newly initialized temporary PostgreSQL17
cluster on port55439 and a separate Docker PostgreSQL16/Redis7 verification stack.
Existing application database contents were not used for destructive tests.

| Check | Actual result |
| --- | --- |
| Baseline backend before moves | **1541 passed, 21 skipped** (PG not enabled) |
| Baseline frontend | TypeScript and direct dependency validation passed; no pre-existing web build/test command |
| Separated SQLite backend | **1544 passed, 21 skipped** |
| Separated full PostgreSQL backend | **1565 passed**, zero skipped; includes 3 new separation regression tests |
| Alembic upgrade / model drift | Upgrade to `0019` and `alembic check` pass on temporary PG17 and Docker PG16 |
| Python lint/format/types | Ruff passes; Black passes for app/scripts; Mypy passes for all 168 app files |
| Python dependencies / package build | `pip check` passes; backend wheel successfully built |
| OpenAPI compatibility | Snapshot + immutable pre-separation baseline gate passed; all distributed copies agree |
| Frontend clean install | `npm ci` succeeds in fresh Docker build contexts |
| Frontend type/contract checks | TypeScript and `npm run api:check` pass |
| Frontend unit/API tests | **10 passed**, no failures |
| Standalone production build | `npm run build` passes with no backend requirement |
| Standalone browser tests | **2 passed** against production preview and **2 passed** against actual Expo dev server; API calls blocked |
| UI behavior | Arabic/RTL document and protected routing verified; widths320/390/1280 checked without horizontal overflow; mobile screenshot visually inspected |
| Independent Docker builds | Backend and frontend images built successfully using their separate contexts |
| Integrated Docker runtime | All six services healthy: API, frontend, worker, Beat, PostgreSQL, Redis |
| Health endpoints | API liveness/readiness succeed with DB/Redis; frontend health succeeds |
| Live browser integration | **1 passed**, repeated successfully after dependency fix: real registration/JWT login, tenant_slug, CORS, offers, detail, decline204, accept/server state, logout |
| Offer timer | Live detail remains open beyond16 seconds; no invented live expiry |
| Worker execution | Queued `mesaar.ping` returns `pong`; relay task completes; first workflow's **8/8 events published**, consumer processing records present |
| Lifecycle independence | Browser remains usable while API is stopped and recovers after restart; frontend stop/start leaves API healthy with unchanged process start time |

One intermediate backend run failed `test_default_log_level_is_info` because the
verification shell set `LOG_LEVEL=ERROR`. The override was removed and the complete
suite passed; application code/tests were not weakened. The final runs retain one
pre-existing Starlette `python_multipart` pending-deprecation warning.

The first container worker failure and the initial frontend typecheck finding were
corrected and reverified. No test success is inferred from documentation or a prior
session. CI workflow definitions were updated; a hosted GitHub Actions run was not
triggered from this local session.

## Remaining blockers and deployment readiness

There are no known critical separation-related failures in the exercised workflows.
The following pre-existing platform gaps remain outside a safe layout migration:

1. Production phone OTP/Nafath and several navigation destinations are unimplemented.
   Native device execution and Android/iOS release builds were not performed.
2. The driver API does not expose all fields required for the original illustrative
   maps/company cards/deadlines. The UI states that data is unavailable. Decline has
   the backend's original non-persistent behavior; several KPIs are placeholder zeroes
   returned by the backend, as already documented.
3. Existing resource-ownership gaps inside a tenant, platform-scope defaults,
   fail-open Redis denylist behavior and other JWT policy debts remain. RLS passing
   does not prove those separate policies complete.
4. Existing outbox/webhook overlap, projection rebuild accounting/concurrency, and
   dispatch/tracking policy debts remain documented in [status](docs/status.md) and
   the previous readiness review. This task did not redesign domain behavior.
5. A comprehensive dependency vulnerability audit, native secure-storage migration,
   production TLS/backup/ingress setup, load testing and full accessibility audit
   were not performed. Expo51 and the established Python stack were preserved.

The applications can now be independently developed, tested, packaged and deployed.
Use the READMEs for exact commands and the migration notes for existing-volume
upgrades and rollback. Resolve the above enterprise-readiness debts before treating
the overall platform as production-ready.

Implementation references: [Expo web workflow](https://docs.expo.dev/workflow/web/),
[Expo SPA publishing](https://docs.expo.dev/guides/publishing-websites/),
[OpenAPI TypeScript CLI](https://openapi-ts.dev/cli), and
[Kombu Redis transport source](https://github.com/celery/kombu/blob/main/kombu/transport/redis.py).
