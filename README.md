# Mesaar (مسار) — Logistics Management System

Mesaar is a multi-tenant logistics platform for road freight, heavy equipment,
and specialized cargo operations in Saudi Arabia and the GCC. This repository
(`Logistics_Managemnt_System`) contains a FastAPI backend, an Arabic-first RTL
driver app, database migrations, background workers, and product and architecture
specifications.

The platform covers customer and order management, shipment execution, fleet and
warehouse capacity, equipment, permits and compliance, insurance and claims,
billing, notifications, analytics, and partner integrations.

## Contents

- [Project requirements and components](#project-requirements-and-components)
- [Architecture](#architecture)
- [Technology and prerequisites](#technology-and-prerequisites)
- [Backend setup](#backend-setup)
- [Configuration](#configuration)
- [API and authentication](#api-and-authentication)
- [Driver mobile app](#driver-mobile-app)
- [Development and testing](#development-and-testing)
- [Repository structure](#repository-structure)
- [Current limitations](#current-limitations)
- [Documentation](#documentation)
- [License](#license)

## Project requirements and components

### Business scope

Mesaar supports shippers, industrial operators, heavy-haul carriers, and equipment
companies that need to plan, dispatch, track, and account for cargo movements.
The product vision also includes future control-tower interfaces, equipment rental,
contract-based pricing, and predictive operations. See the
[project vision](docs/01-project-vision.md) for the full scope and business targets.

Backend roles are `admin`, `manager`, `driver`, and `client`. Operations and
dispatch users share the `manager` role; individual endpoints enforce their own
role and ownership restrictions.

### Backend components

The following modules and contracts are present in the repository. All business
paths below use the default `/v1` prefix.

| Component | Responsibilities | API surface |
| --- | --- | --- |
| Identity and tenancy | Organization registration, user accounts, tenant provisioning, JWT access tokens, refresh rotation, logout, and role checks | `/auth`, `/users` |
| Customers | Customer profiles, contacts, classification, search, and lifecycle management | `/customers` |
| Orders | Cargo requests, pickup/delivery details, scheduling, dispatcher assignment, guarded lifecycle, soft delete, and restore | `/orders` |
| Shipments and tracking | Warehouse-to-warehouse movements, driver/vehicle assignment, pickup, transit, delay, delivery, cancellation, failure, return, and tracking evidence | `/shipments` |
| Drivers | Profiles, availability, self-service stats, shipment offers, acceptance, and decline | `/drivers`, `/drivers/me`, `/auth/driver/login` |
| Fleet and warehouses | Vehicles, operational status, weight/volume limits, warehouse locations, and capacity | `/vehicles`, `/warehouses` |
| Equipment and assets | Categories, models, specifications, dimensions, ownership, reservation, availability, maintenance, and decommissioning | `/equipment` |
| Compliance and permits | Permit lifecycle, escorts, route restrictions, axle-weight profiles, compliance checks, operator certifications, and dispatch gating | `/compliance` |
| Insurance and claims | Insurance policies, coverage rules, claim review/approval/settlement, damage reports, and liability records | `/insurance`, `/claims` |
| Billing and settlements | Quotes, invoices and invoice lines, payments, penalties, claim adjustments, settlements, and payout records | `/billing` |
| Notifications | Templates, event-triggered in-app messages, read tracking, delivery attempts, and retry actions | `/notifications` |
| Reporting and analytics | Shipment, financial, receivables-aging, claims, compliance, notification, and operations projections; health and tenant-scoped rebuilds | `/analytics` |
| Partner integrations | Partners, scoped API keys, subscriptions, signed webhooks, delivery attempts/retries, and authenticated inbound events | `/integrations` |

Equipment is the physical asset being moved; a vehicle is the transport asset
performing the haul. Their lifecycles are owned by separate modules.

### Core engineering requirements

- **Tenant isolation:** tenant-scoped records and references, PostgreSQL Row-Level
  Security (RLS), and transaction-local tenant/user context. Authenticated tenant
  scope is derived from the JWT or partner API key.
- **Guarded workflows:** lifecycle state machines, validation of assignments and
  capacity, and optimistic locking on versioned aggregates.
- **Compliance before dispatch:** shipment assignment, pickup, and transit consult
  a compliance gate for required permits, escorts, and blocking checks. Some
  certification and spatial-rule enforcement remains follow-up work.
- **Traceability:** actor attribution, lifecycle timestamps, soft deletion where
  supported, append-only domain events, and audit records. Domain state changes
  and their outbox events share a database transaction.
- **Reliable event processing:** consumer idempotency, retry/dead-letter handling,
  and rebuildable tenant-scoped read models. Analytics is eventually consistent.
- **Financial consistency:** explicit currencies, invoice totals and balances,
  confirmed-payment handling, and validation of claim-backed settlements.
- **Partner security:** hashed API keys, encrypted webhook signing secrets,
  sanitized outbound payloads, HMAC signatures, scopes, source-IP restrictions,
  replay-window checks, and inbound idempotency.
- **Operations and usability:** request correlation, structured logs, readiness
  probes, metrics, Arabic RTL layouts, reusable design tokens, and defined
  loading/empty/error states. WCAG 2.2 AA is a design/build target for future web
  consoles, not a completed accessibility certification.

## Architecture

The backend is a modular monolith with domain-oriented modules, layered
application code, and CQRS-lite. Relational aggregates hold current business
state; the unified event store records domain facts and feeds read projections
and integration consumers.

```mermaid
flowchart LR
    Client[API clients] --> API[FastAPI routes and schemas]
    API --> Services[Application services and policies]
    Services --> Repos[Repositories and models]
    Repos --> DB[(PostgreSQL)]
    Services --> Events[Event store / transactional outbox]
    Events --> DB
    Beat[Celery beat] --> Worker[Celery worker]
    Redis[(Redis)] <--> Worker
    Worker --> Relay[Outbox relay and dispatcher]
    DB --> Relay
    Relay --> Consumers[Notifications / analytics / webhooks]
    Consumers --> DB
```

HTTP handlers validate contracts and authorization. Services own business rules
and transactions; repositories provide persistence operations. Notification,
analytics, and webhook consumers process source events without owning the source
domain's lifecycle.

The configured periodic jobs in [celery_app.py](app/workers/celery_app.py) are:

| Task | Interval | Purpose |
| --- | --- | --- |
| `mesaar.relay_outbox` | 30 seconds | Publish pending domain events to registered consumers |
| `mesaar.webhook_delivery_sweep` | 60 seconds | Attempt due webhook deliveries with bounded backoff |
| `mesaar.projection_health_check` | 5 minutes | Classify projection health/staleness without rebuilding |

The API, worker, and scheduler are separate processes. Run both worker and beat
to enable scheduled event processing. Redis provides the cache and Celery
broker/result backend, along with token storage and revocation support.

## Technology and prerequisites

| Area | Dependencies / requirements |
| --- | --- |
| Backend runtime | Python 3.11 is used by Docker and CI; the manifest specifies Python 3.11+ |
| HTTP and validation | FastAPI 0.111.0, Uvicorn 0.30.1, Pydantic 2.8.2, pydantic-settings 2.3.4 |
| Persistence | PostgreSQL 16, SQLAlchemy 2.0.31, Alembic 1.13.2, psycopg2-binary 2.9.9 |
| Background infrastructure | Redis 7, Celery 5.4.0, redis-py 5.0.7 |
| Authentication | python-jose, Passlib, bcrypt, and cryptography support |
| Operations | Gunicorn, Loguru, Prometheus client, Docker, Docker Compose v2 |
| Backend tests | pytest 8.2.2 and HTTPX 0.27.0; SQLite for most tests, PostgreSQL for isolation/backbone tests |
| Mobile | Node.js and npm compatible with Expo SDK 51; React 18.2, React Native 0.74.5, Expo Router 3.5, TypeScript 5.3 |
| Mobile preview | A compatible Expo Go/development client or Android emulator; macOS/Xcode for an iOS simulator |

Exact Python pins are in [requirements.txt](requirements.txt); mobile dependency
ranges and resolved versions are in [package.json](mobile/package.json) and
[package-lock.json](mobile/package-lock.json). Python 3.11 is the safest starting
point for the pinned backend dependencies. GNU Make and Bash are optional; direct
commands are provided below.

## Backend setup

Run commands from the repository root.

### 1. Create the environment file

PowerShell:

```powershell
Copy-Item .env.example .env
```

Bash:

```bash
cp .env.example .env
```

Edit `.env` before starting the application:

- Set `SECRET_KEY` to a generated secret of at least 32 characters.
- Use the database and Redis URLs appropriate to your environment.
- Set `CORS_ORIGINS` to a JSON array or a comma-separated list of origins. A bare
  `*` is also supported for local development. The example uses
  `CORS_ORIGINS=["*"]`; for explicit origins, use:

```dotenv
CORS_ORIGINS=["http://localhost:8081","http://localhost:19006"]
```

The application loads `.env` from the working directory. Real `.env` files are
ignored by Git and excluded from the Docker build context.

### 2A. Start with Docker Compose

```bash
docker compose build api
docker compose up -d --wait db redis
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose up -d api worker beat
docker compose ps
```

Compose provides five services: `api`, `worker`, `beat`, `db`, and `redis`.
Database migrations are a separate step; neither API startup nor `make up`
automatically applies them. The container configuration overrides host URLs with
the `db` and `redis` service names.

| Service | Local address |
| --- | --- |
| API | `http://localhost:8000` |
| PostgreSQL | `localhost:5432`, database/user/password: `mesaar` |
| Redis | `localhost:6379` |

Inspect logs or stop the stack:

```bash
docker compose logs -f api worker beat
docker compose down
```

PostgreSQL and Redis data are stored in named volumes. Compose credentials are
development defaults. Its `mesaar` PostgreSQL role is a superuser and bypasses RLS;
use a non-superuser role without `BYPASSRLS` for meaningful isolation testing and
production application connections.

### 2B. Run Python processes locally

Create and activate a virtual environment using Python 3.11.

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Bash:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Install the backend requirements, start PostgreSQL/Redis, migrate, and run the API:

```bash
python -m pip install -r requirements.txt
docker compose up -d --wait db redis
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You may use existing PostgreSQL/Redis installations instead of the Compose
services. The example `.env` URLs point to `localhost` for this setup.

Start the worker and beat in two additional terminals with the same environment:

```bash
python -m celery -A app.workers.celery_app worker --loglevel=info
python -m celery -A app.workers.celery_app beat --loglevel=info
```

On Windows, use the solo worker pool for local development:

```powershell
python -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

Use the Linux containers for the full worker deployment.

## Configuration

[.env.example](.env.example) contains the settings template; the schema and
validation rules live in [config.py](app/core/config.py). Values below refer to
the example environment file.

| Settings | Purpose / example values |
| --- | --- |
| `DATABASE_URL`, `SECRET_KEY` | PostgreSQL connection string and JWT/local webhook-encryption secret |
| `ENVIRONMENT`, `DEBUG` | `development`, `staging`, `production`, or `test`; debug defaults to `false` |
| `APP_NAME`, `APP_VERSION`, `API_V1_PREFIX` | Service metadata and default `/v1` business prefix |
| `CORS_ORIGINS` | Allowed origins as a JSON array, comma-separated URLs, or a local-development wildcard |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_MINUTES` | Example: 30 minutes and 20,160 minutes (14 days) |
| `TOKEN_ALGORITHM`, `BCRYPT_WORK_FACTOR`, `JWT_ISSUER`, `JWT_AUDIENCE` | `HS256`, 12, `mesaar`, `mesaar-clients` |
| `REDIS_URL`, `CACHE_TTL_SECONDS` | Cache/token Redis database 0; example cache TTL 300 seconds |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis databases 1 and 2 |
| `CELERY_TASK_MAX_RETRIES`, `CELERY_TASK_DEFAULT_RETRY_DELAY` | Example task defaults: 3 retries and 5 seconds; domain delivery policies may differ |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE_SECONDS`, `DB_ECHO` | Connection pool sizing, timeout/recycle, and SQL logging |
| `LOG_LEVEL`, `LOG_JSON`, `REQUEST_ID_HEADER`, `TENANT_HEADER` | Logging and request context; default headers `X-Request-ID`, `X-Tenant-ID` |
| `PROMETHEUS_ENABLED` | Enable HTTP metrics and the `/metrics` endpoint |

Real outbound webhooks, distributed inbound rate limiting, and KMS encryption
require provider wiring in application/worker startup code. They are not enabled
by the `.env` template. See the
[integration runbook](docs/28-integration-delivery-worker-hardening.md) for the
`set_webhook_provider`, `set_inbound_rate_limiter`, and `set_secret_provider` hooks.

## API and authentication

Once the backend runs, use these entry points:

| Endpoint | Purpose |
| --- | --- |
| [Swagger UI](http://localhost:8000/docs) | Interactive generated API documentation |
| [ReDoc](http://localhost:8000/redoc) | Generated API reference |
| [OpenAPI JSON](http://localhost:8000/openapi.json) | Current schema generated from mounted routes |
| `/health` | Overall snapshot; HTTP 200 with dependency status in the body |
| `/health/live` | Process liveness without dependency checks |
| `/health/ready` | PostgreSQL/Redis readiness; HTTP 503 when dependencies fail |
| `/metrics` | Prometheus metrics when enabled |

Health and metrics paths are unversioned. Business routes default to `/v1`.
[api/openapi.yaml](api/openapi.yaml) is an older hand-maintained draft; use the
generated schema for the current route contracts.

### Register a tenant and obtain credentials

There is no documented seeded administrator account. Self-service registration
creates an organization and its administrator. Example in PowerShell:

```powershell
$mesaarRegistration = @{
    email = "admin@example.com"
    password = "local-development-password"
    full_name = "Local Administrator"
    organization_name = "Example Logistics"
    tenant_slug = "example-logistics"
} | ConvertTo-Json

$mesaarSession = Invoke-RestMethod -Method Post `
    -Uri "http://localhost:8000/v1/auth/register" `
    -ContentType "application/json" -Body $mesaarRegistration

$mesaarHeaders = @{ Authorization = "Bearer $($mesaarSession.access_token)" }
Invoke-RestMethod -Uri "http://localhost:8000/v1/auth/me" -Headers $mesaarHeaders
```

Existing users authenticate with JSON `email` and `password` at
`POST /v1/auth/login`; include `tenant_slug` when needed to scope the lookup.
Registration/login return `access_token`, `token_type`, `expires_in`,
`refresh_token`, and `user`.

Protected user requests use `Authorization: Bearer <access_token>`.
`POST /v1/auth/refresh` rotates a submitted refresh token;
`POST /v1/auth/logout` revokes the current access token and optionally a refresh
token. Use an available Redis instance for token lifecycle operations.

Partner inbound requests use a partner API key as the bearer credential and
require `integrations:inbound:write`, an idempotency key, an HMAC signature, and
`X-Mesaar-Timestamp` within the permitted 300-second replay window. User JWTs
remain the authentication method for integration management routes.

## Driver mobile app

The driver app is an Expo/React Native prototype with Arabic RTL layout, Tajawal
fonts, Saudi mobile-number validation, persisted sessions, and mock data enabled
by default. Backend services are not required for the mock demo.

```bash
cd mobile
npm ci
npm start
```

Available scripts: `npm run android`, `npm run ios`, `npm run web`,
`npm run typecheck`, and `npm run lint`. Simulator and browser previews require
their corresponding platform dependencies.

| Screen | Route | Features |
| --- | --- | --- |
| Login | `/auth/login` | Saudi phone normalization/validation and mock sign-in |
| Driver dashboard | `/driver/home` | Availability toggle, daily KPI cards, shipment offers, and loading/error states |
| Shipment offer | `/driver/orders/[id]` | Route-map visual, offer countdown, accept/ignore sheet, and accepted state |

Reusable UI includes `AppLayout`, `AppText`, `Card`, `ErrorBoundary`,
`PrimaryButton`, `SecondaryButton`, `PhoneInput`, `Toggle`, `StatusCard`, `KPIBox`,
`ShipmentRequestCard`, `MapPreview`, `RouteMap`, `BottomNav`, `CountdownBadge`,
`OrderBottomSheet`, and `DriverHeader`. Mobile tokens live in
[mobile/src/theme](mobile/src/theme); shared specifications are in
[design-system](design-system).

### Live API integration status

| Variable | Behavior |
| --- | --- |
| `EXPO_PUBLIC_USE_MOCK` | Mock mode unless the value is exactly `false` |
| `EXPO_PUBLIC_API_URL` | API base URL including `/v1`; code default is `https://api.mesaar.sa/v1` |

These variables select the HTTP adapter; changing them alone does not complete
the integration. [driverApi.ts](mobile/src/api/driverApi.ts) currently raises
`ApiError(501, 'Live login not wired yet')` for live login. Other HTTP branches
also need contract adapters: mobile types use camelCase/enriched objects, while
backend responses use snake_case and different shapes; decline returns HTTP 204.

The backend phone-login route is `POST /v1/auth/driver/login`, and its OTP
verification is a stub. The Nafath button is a UI placeholder. Maps are SVG
route visuals, and the backend offer distance is a straight-line calculation;
turn-by-turn routing and live map-provider integration are not supplied.

After implementing the adapters, set the API URL to a host reachable from the
device/emulator. A physical phone's `localhost` refers to the phone itself.
See [mobile/README.md](mobile/README.md) for app-specific details and the
[screen map](ui/screen-map.md) for planned screens.

## Development and testing

### Backend tests

After installing requirements:

```bash
python -m pytest -q
```

Most tests use isolated SQLite databases and mocked providers. The shared
fixtures set test defaults before application imports, so PostgreSQL and Redis
are not required for the default unit suite. PostgreSQL-only tests are skipped
unless their database environment variables are supplied.

To exercise tenant-isolation and event-backbone tests, point **both**
`DATABASE_URL` and `TEST_DATABASE_URL` at a disposable PostgreSQL test database
owned by an application role with `NOSUPERUSER NOBYPASSRLS`. These fixtures
create and drop tables; do not use the development or production database.

Example for an already-created test database, in PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://mesaar_test_app:mesaar_test_app@localhost:5432/mesaar_test"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
python -m pytest -q
Remove-Item Env:DATABASE_URL
Remove-Item Env:TEST_DATABASE_URL
```

[CI](.github/workflows/ci.yml) uses Python 3.11, PostgreSQL 16, Redis 7, and a
non-superuser application role. It runs Ruff, Black, advisory Mypy, and pytest.
Historical test totals in domain documents describe earlier snapshots.

### Linting, formatting, and migrations

The optional tooling is installed separately from `requirements.txt`, matching CI:

```bash
python -m pip install ruff==0.5.5 black==24.4.2 mypy==1.10.1
python -m ruff check app
python -m black --check -l 100 app
python -m mypy app
```

Migration commands:

```bash
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
python -m alembic revision --autogenerate -m "describe change"
```

Review generated migrations before applying them. Alembic's revision hook uses
Black, so install it before generating a revision. The repository contains
migrations `0001` through `0018`; `0018` hardens RLS policies to deny access on an
empty tenant setting.

### Makefile shortcuts

The [Makefile](Makefile) requires GNU Make and Bash (for example, Linux, macOS,
or a suitable Windows Bash environment).

| Command | Action |
| --- | --- |
| `make help` | List available targets |
| `make run` | API with reload; accepts `HOST`, `PORT`, and `APP` overrides |
| `make worker`, `make beat` | Worker or periodic scheduler |
| `make migrate` | Apply migrations |
| `make revision MSG="describe change"` | Generate a migration |
| `make test` | Run pytest |
| `make lint`, `make fmt` | Check or fix formatting/lint |
| `make up`, `make down`, `make logs` | Start, stop, or inspect Compose services |

## Repository structure

```text
app/
  main.py                 FastAPI application factory and composition root
  api/                    Routes, dependencies, middleware, health, /v1 assembly
  schemas/                Pydantic request/response contracts
  services/               Business workflows, policies, and transaction ownership
  repositories/           Database queries and persistence boundaries
  models/                 SQLAlchemy entities and enums
  db/                     Sessions, tenant context, mixins, and UUID utilities
  core/                   Settings, security, Redis, tokens, and error handling
  auth/                   Authentication/authorization helpers
  events/                 Event definitions, registry, bus, dispatcher, and relay
  projections/            Projection rebuilding infrastructure
  analytics/              Analytics event consumer and health sweep
  notifications/          Notification event consumer and provider ports
  integrations/           Signing, encryption, auth, delivery, and retry sweep
  observability/          Logging, metrics, and dependency health
  common/                 Pagination, timestamps, and shared responses
  workers/                Celery configuration and task wrappers
migrations/               Alembic environment and versioned schema changes
tests/                    Unit, route, domain integration, and PostgreSQL tests
mobile/
  app/                    Expo Router screens
  src/                    API adapter, components, hooks, mock data, state, theme
  assets/                 App icons and splash assets
api/openapi.yaml          Historical API contract draft
docs/                     Vision, domain designs, implementation reports, ADRs
design-system/            Shared tokens, component catalog, and design requirements
ui/screen-map.md          Role-based screen inventory
.github/workflows/ci.yml  Backend CI workflow
```

## Current limitations

### Partial and planned functionality

- **Mobile integration and identity:** live mobile login and response adaptation
  are unfinished; backend OTP verification and Nafath integration are placeholders.
  Mobile session tokens currently use AsyncStorage.
- **Driver operations:** `online_hours` and `distance_km` in driver daily stats
  return zero; declining an offer currently validates existence without recording
  a persistent decline.
- **Communications:** in-app delivery is implemented; email, SMS, push, and the
  notification channel's webhook provider are unconfigured adapters.
- **Partner webhooks:** a real HTTP provider and Redis rate limiter exist but
  require explicit startup registration. Defaults are no-network delivery,
  process-local limiting, and local Fernet encryption derived from `SECRET_KEY`.
  KMS and webhook egress/SSRF hardening remain deployment follow-ups.
- **Compliance:** spatial/geofencing checks, assignment-time operator-certification
  enforcement, and automatic permit/certification expiry sweeps remain incomplete.
- **Commercial automation:** financial records and workflows do not constitute a
  payment gateway, bank payout integration, or ERP export. Automatic order-to-shipment
  fan-out and richer contracts/rental/SLA workflows remain planned.
- **Interfaces and intelligence:** operations, dispatcher, admin, and customer web
  consoles are specified rather than shipped. AI dispatch, predictive ETA, route
  optimization, and the broader control-tower experience remain roadmap work.

Earlier architecture/audit documents capture the state at the time they were
written. Later domain reports describe subsequent additions; neither historical
readiness scores nor historical test counts certify the current checkout.

## Documentation

| Topic | References |
| --- | --- |
| Vision and scope | [Project vision](docs/01-project-vision.md), [architecture overview](docs/02-architecture.md) |
| Database and domain design | [Database architecture](docs/03-database-architecture.md), [events and state machines](docs/04-event-storming-and-state-machines.md), [consolidated domain model](docs/09-final-domain-model.md), [ERD review](docs/10-final-erd-review.md) |
| Backend design | [Layering and ownership](docs/05-backend-architecture.md), [implementation blueprint](docs/11-backend-architecture.md) |
| Planning and reviews | [Architecture audit](docs/06-architecture-audit-and-readiness.md), [execution plan](docs/07-phase-5-execution-plan.md), [reconciliation](docs/09a-reconciliation-and-closure.md), [implementation plan](docs/12-implementation-plan.md), [code audit](docs/15-enterprise-code-audit.md), [readiness report](docs/16-implementation-readiness.md), [roadmap](docs/17-execution-roadmap.md) |
| Event infrastructure | [M2 readiness](docs/13-m2-readiness-report.md), [event backbone](docs/14-m2-event-backbone.md) |
| Orders and shipments | [Order domain](docs/18-order-domain.md), [shipment domain](docs/19-shipment-domain.md) |
| Heavy equipment and risk | [Heavy-equipment design](docs/08-heavy-equipment-domain-design.md), [equipment](docs/20-equipment-domain.md), [compliance](docs/21-compliance-permits-domain.md), [insurance and claims](docs/22-insurance-claims-domain.md) |
| Finance and communications | [Billing and settlements](docs/23-billing-settlements-domain.md), [notifications](docs/24-notifications-communications-domain.md) |
| Analytics | [Reporting projections](docs/25-reporting-analytics-projections-domain.md), [event enrichment and analytics hardening](docs/26-event-enrichment-analytics-hardening.md) |
| Integrations | [Partner API and webhooks](docs/27-external-integrations-webhooks-domain.md), [delivery hardening and runbook](docs/28-integration-delivery-worker-hardening.md) |
| Decisions and diagrams | [Architecture decision records](docs/adr), [Mermaid diagrams](docs/diagrams) |
| UI and mobile | [Driver app](mobile/README.md), [screen map](ui/screen-map.md), [design specification](design-system/design-spec.md), [component catalog](design-system/components-index.md), [design tokens](design-system/tokens.json), [accessibility checklist](docs/wcag-2.2-aa-checklist.md) |
| Historical reference slices | [Domain glossary](docs/domain-glossary.md), [superseded event catalog](docs/event-catalog.md), [earlier mobile API gap analysis](docs/api-gap-analysis.md) |

## License

This project is licensed under the [MIT License](LICENSE).
