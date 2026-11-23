# Contributing to Logistic X — Driver App

Thanks for helping improve Logistic X.

## Workflow

1. Create a branch from `main`: `feat/…`, `fix/…`, `chore/…` or `docs/…`.
2. Make focused changes with tests.
3. Run the local checks: `npm run api:check && npm run typecheck && npm test`.
4. Open a pull request using the template; CI must pass and a code owner must approve.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/), for example
`feat: add settlement export` or `fix: correct RTL padding on trip card`.

## API contract

The OpenAPI contract in `api/openapi.json` is shared between the backend and the
driver app. Any change to it must be made in the backend first, then copied to the
frontend and regenerated with `npm run api:generate`.
