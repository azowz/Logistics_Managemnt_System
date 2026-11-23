# Logistic X · لوجستك إكس

منصة الخدمات اللوجستية متعددة المستأجرين، مع تطبيق سائق عربي RTL.
The backend and frontend are now independent applications; this root directory
provides optional development orchestration and architecture documentation.

[![CI](https://github.com/logistic-x/logistic-x/actions/workflows/ci.yml/badge.svg)](https://github.com/logistic-x/logistic-x/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Repositories

Each application also lives in its own repository under the [logistic-x](https://github.com/logistic-x) organization, with its own history, CI and releases:

| Repository | Purpose |
| --- | --- |
| [logistic-x/backend](https://github.com/logistic-x/backend) | Operations API (FastAPI, PostgreSQL, Celery) |
| [logistic-x/frontend](https://github.com/logistic-x/frontend) | Arabic RTL driver app (Expo / React Native) |
| [logistic-x/logistic-x](https://github.com/logistic-x/logistic-x) | This repository: docs, design system, contract and full-stack verification |

## Workspace layout

| Application | Technology | Instructions |
| --- | --- | --- |
| [logistic-x-backend](logistic-x-backend/) | FastAPI / SQLAlchemy / Alembic / PostgreSQL / Redis / Celery | [Backend README](logistic-x-backend/README.md) |
| [logistic-x-frontend](logistic-x-frontend/) | Existing Expo / React Native / TypeScript, with a standalone web build | [Frontend README](logistic-x-frontend/README.md) |

## Run independently

Backend: work in `logistic-x-backend`, install `requirements-dev.txt` into its own Python
3.11/3.12 environment, configure its `.env`, then run:

```bash
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

PostgreSQL and Redis are backend infrastructure. The backend directory also has a
backend-only Docker Compose file and exact worker, test, build and deployment commands.

Frontend (Node 22):

```bash
cd logistic-x-frontend
npm ci
# First setup only: copy .env.example to .env (PowerShell: Copy-Item .env.example .env)
npm run dev
```

The shell runs at `http://localhost:8081` even if the backend is unavailable. Live
API requests show connection errors. Configure `EXPO_PUBLIC_API_URL` before building;
`npm run build` creates a static website. Existing native targets remain available.
Demo fixtures require explicit development opt-in and are visibly labelled.

## Integrated Docker development

First setup only: copy `logistic-x-backend/.env.example` to `logistic-x-backend/.env` and set
a random `SECRET_KEY` of at least 32 characters. Preserve an existing environment.
From this root directory:

```bash
docker compose build api frontend
docker compose up -d --wait db redis
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose up -d api worker beat frontend
docker compose ps
docker compose logs -f api worker beat
docker compose down
```

API: `http://localhost:8000`; frontend: `http://localhost:8081`. Data stays in the
original named volumes. Database initialization keeps the non-superuser application
role for RLS. Existing data/role ownership instructions are in [operations](docs/operations.md).
The frontend service has no startup dependency on the API; either can be stopped or
restarted independently. Frontend variables are public, build-time configuration.
These Compose settings are local development examples, not production secrets.

## Contracts and verification

The exported [OpenAPI contract](contracts/openapi.json) is the release interface.
Existing business endpoints retain `/v1`; `/health/live`, `/health/ready`, `/docs`,
and `/openapi.json` remain backend-owned. The old YAML design is kept under
`logistic-x-backend/api/` and is not the live contract.

```bash
cd logistic-x-backend
python -m pytest -q
python -m scripts.check_contract
```

```bash
cd logistic-x-frontend
npm test
npm run typecheck
npm run api:check
npm run build
npm run test:e2e
```

PostgreSQL tests require a disposable database and non-superuser role; some recreate
tables. The frontend browser tests run without an API. Live integration tests use
real JWTs and a separate test stack. [Migration instructions](docs/separation-migration.md)
include its exact commands and rollback procedure.

## Structure and results

```text
logistic-x-backend/    app/, migrations/, tests/, api/, Dockerfile, Python dependencies
logistic-x-frontend/   app/, src/, assets/, tests/, api/, Dockerfile, npm dependencies
contracts/        released OpenAPI JSON (distribution artifact)
docs/             current references, ADRs, diagrams, historical archive
design-system/    design specifications (no runtime dependency)
ui/               screen specifications
docker-compose.yml optional root development orchestrator
```

See [SEPARATION_REPORT.md](SEPARATION_REPORT.md) for actual test results and limits,
[architecture inventory and diagrams](docs/separation-architecture.md), and
[migration/rollback notes](docs/separation-migration.md). Existing platform security
and product debts remain documented; this migration does not assert overall
production readiness or implement planned web dashboards, AI, or production OTP.

[Documentation index](docs/README.md) ? [Implementation status](docs/status.md) ? [MIT](LICENSE)

## License

Released under the [MIT License](LICENSE).
