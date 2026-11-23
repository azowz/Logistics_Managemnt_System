# Contributing to Mesaar

## Repository layout

| Path | What lives there |
| --- | --- |
| `mesaar-backend` | FastAPI API, Celery workers, Alembic migrations, tests |
| `mesaar-frontend` | Arabic-first RTL driver app (Expo / React Native) |
| `contracts` | Published API contract (`openapi.json`) shared by both apps |
| `design-system`, `ui` | Design tokens, component catalog and screen map |
| `docs` | Product, architecture and domain specifications, ADRs, diagrams |

Each application is independently buildable; neither imports code from the other.
See [SEPARATION_REPORT.md](SEPARATION_REPORT.md) for details.

## Workflow

1. Branch from `main` using a prefix: `feat/`, `fix/`, `chore/`, `docs/`.
2. Keep each pull request focused on one area where possible.
3. Open a pull request against `main`; CI must pass before merging.
4. A code owner reviews and merges.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) with the area as
scope, for example `feat(backend): add settlement export` or
`fix(frontend): correct RTL padding on trip card`.
