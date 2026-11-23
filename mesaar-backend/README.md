# Mesaar backend

Independent FastAPI/Python application. Copy or deploy this directory by itself.
No Node.js, frontend files, or parent-directory configuration is required.
The `app` package and `/v1` API retain their existing names and behavior.

## Local startup

Requires Python 3.11 or 3.12, PostgreSQL 16+, and Redis 7. From this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env # first setup only; preserve an existing .env
# Set SECRET_KEY to a random value of at least 32 characters in .env.
# Set DATABASE_URL and Redis/Celery URLs for your own services.
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000
```

Linux/macOS: `python3.11 -m venv .venv`, `source .venv/bin/activate`, then use
`python` for the same pip, Alembic, and Uvicorn commands. Dependencies for runtime
alone: `python -m pip install -r requirements.txt`.

Run workers separately in activated environments:

```bash
python -m celery -A app.workers.celery_app worker --loglevel=info
python -m celery -A app.workers.celery_app beat --loglevel=info
```

On Windows add `--pool=solo` to the worker. Run one Beat scheduler. Never run
migrations automatically in API startup or in every worker.

## Backend-only Docker

```bash
docker compose build api
docker compose up -d --wait db redis
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose up -d api worker beat
docker compose logs -f api worker beat
docker compose down
```

This backend-owned Compose file has no frontend service. Database volumes retain
their original names under project `mesaar`. Existing volumes need the application
role/ownership setup in `docker/postgres/init-app-role.sql`; init scripts run only
on new volumes. Preserve data and the same JWT secret when upgrading.

## Tests and build

```bash
python -m pytest -q
python -m ruff check .
python -m black --check app scripts
python -m mypy app
python -m pip check
python -m pip wheel --no-deps --wheel-dir dist .
docker build -t mesaar/backend .
```

The unit suite uses SQLite without frontend tooling. For PostgreSQL gates, use a
**disposable database**, with its own `NOSUPERUSER NOBYPASSRLS` role. The PG tests
drop/recreate tables. Never point them at development or production data:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://test_app:password@localhost:55432/mesaar_test"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
python -m alembic upgrade head
python -m alembic check
python -m pytest -q
```

## API and environments

- `GET /health/live`: process liveness, no dependency I/O.
- `GET /health/ready`: PostgreSQL and Redis; 503 on dependency failure.
- `/docs`, `/redoc`, `/openapi.json`: actual API documentation/schema.
- Business endpoints retain `/v1`. Driver self routes stay before generic routes.
- Configure `CORS_ORIGINS` with exact frontend origins, e.g.
  `["https://drivers.example.com"]` in production; no `/v1` suffix on origins.
- Environment variables override this application's `.env`. Staging/production
  need private service URLs and a shared secret for API/worker/Beat. The frontend
  receives none of these. Set `ENVIRONMENT=production` and `DEBUG=false` in production.

Authentication stays bearer JWT (`Authorization: Bearer ...`). Email login takes
`email`, `password`, and optional `tenant_slug`. Login/register return access and
refresh tokens; refresh rotates via `/v1/auth/refresh`, logout revokes via
`/v1/auth/logout`. Phone login remains unavailable in production until OTP exists.
Tenant scope is authenticated by the backend; a client header does not grant access.

```bash
python -m scripts.export_openapi
python -m scripts.check_contract
```

`api/openapi.json` is the exported interface. `api/openapi.v1.baseline.json` records
the exact pre-separation contract. The conservative gate allows new endpoints and
components, and rejects alterations/removals of existing ones for review. Do not
overwrite the baseline to conceal incompatible changes. `api/openapi.yaml` remains
a labelled historical design draft and is not consumed by clients.

Release a compatible contract with the backend. Frontend maintainers can receive
that JSON as an artifact and generate types without running this application.

## Deployment and troubleshooting

Build with this directory as the Docker context; the image runs as user `mesaar`.
Keep migrations alongside the image/release; apply `alembic upgrade head` once using
the deployment's environment before switching traffic. Probe readiness before routing
requests. Scale API/workers independently, and keep one Beat.

A 503 readiness response identifies unavailable PostgreSQL/Redis. A 401 means the
token/session needs authentication; a 403 is authorization, which must not be fixed
by removing backend checks. Browser CORS failures require the exact frontend origin
in backend configuration. If imports fail, install all pinned requirements into the
same Python interpreter used to start the server. On PowerShell use the interpreter
path directly if activation is restricted.

Rollback: redeploy the prior backend image with the same environment and database;
this separation changes no schema. No downgrade or volume deletion is necessary.
