# Migration and rollback

No database schema or business-rule migration is part of this change. The 19 existing
Alembic revisions remain byte-identical; deployment still applies them independently.

## Path mapping

| Previous path | Authoritative new path |
| --- | --- |
| `app/` | `mesaar-backend/app/` (same Python import package) |
| `migrations/`, `alembic.ini` | `mesaar-backend/migrations/`, `mesaar-backend/alembic.ini` |
| `tests/`, `pytest.ini` | `mesaar-backend/tests/`, `mesaar-backend/pytest.ini` |
| Python manifests, backend Dockerfile | `mesaar-backend/` |
| `docker/postgres/` | `mesaar-backend/docker/postgres/` |
| `api/openapi.yaml` | `mesaar-backend/api/openapi.yaml` (historical) |
| `mobile/` source, assets and manifests | `mesaar-frontend/` |
| Root `.env` | Kept untouched; privately copied to `mesaar-backend/.env` for local continuity |
| Root Compose/Makefile/CI | Updated optional orchestration/independent application jobs |
| Docs/design system/screen specifications | Remain at root; current source links updated |

Before source changes, a source-only snapshot (excluding dependencies, caches, and
real environment files) was saved outside the repository. The migration copied source
first, tested the new applications, and verified every original source file had its
replacement before retiring the old locations. Existing uncommitted changes were
preserved in the copies. There is no Git reset, clean, commit, or history rewrite.

## Upgrade an existing checkout/deployment

1. Preserve the existing database volumes, JWT signing secret, database role, and
   private environment values. Do not overwrite an existing `.env` with examples.
2. Set backend configuration in `mesaar-backend/.env`; root `.env` is now only for
   Compose interpolation. Ensure the backend application role cannot bypass RLS.
3. Change IDE/terminal working directories and deployment build contexts to the
   respective application directory. Recreate Python virtual environments after
   relocation rather than moving a virtual environment with embedded absolute paths.
4. Set frontend public API URL and deployment environment **before** building. Add
   its exact origin to backend CORS. Build/release the frontend independently.
5. Build the backend independently. Run migrations once from its release directory
   and switch API/worker traffic after readiness succeeds. Existing `/v1` clients
   retain their contract.
6. Retain PostgreSQL/Redis volumes and use normal `docker compose down` to stop;
   there is no reason to remove volumes. The development Compose project remains
   named `mesaar` to retain original named volume identities.

## Reproducible disposable integration stack

Compose 2.24.4+ is required for the verification override's port replacement syntax.
The explicit project name separates containers, images and volumes from development.

```bash
docker compose -p mesaar-separation-verify -f docker-compose.yml -f compose.verify.yml build api frontend
docker compose -p mesaar-separation-verify -f docker-compose.yml -f compose.verify.yml up -d --wait db redis
docker compose -p mesaar-separation-verify -f docker-compose.yml -f compose.verify.yml run --rm --no-deps api python -m alembic upgrade head
docker compose -p mesaar-separation-verify -f docker-compose.yml -f compose.verify.yml up -d --no-build api worker beat frontend
```

Test frontend: `http://127.0.0.1:18081`; API: `http://127.0.0.1:18000`.
Run the frontend integration command with the environment values in its README.
Stop only this stack by adding the same project/file arguments to `down`.
The test stack's public secret/credentials are restricted to disposable testing.

## Rollback

Redeploy the previous backend image with the same secrets/volumes, or restore the
previous directory layout from the source snapshot/release. Redeploy the previous
frontend static image independently. The v1 API remains unchanged and there is no
schema downgrade to run. Keep workers and API on the matching release when rolling
back backend code. Avoid `git reset --hard`: this working tree includes earlier
uncommitted work that is unrelated to separation.

For local recovery, the exact original tree and pre-separation OpenAPI were saved at
`C:/Users/abdul/AppData/Local/Temp/mesaar-separation-praqicln/` for this execution.
Private `.env` files remain in the working directory and are excluded from that ZIP.
