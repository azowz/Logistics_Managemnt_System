# Logistic X — Driver App

[![CI](https://github.com/logistic-x/frontend/actions/workflows/ci.yml/badge.svg)](https://github.com/logistic-x/frontend/actions/workflows/ci.yml) ![Expo](https://img.shields.io/badge/Expo-000020?logo=expo) ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Arabic-first, RTL driver app for the Logistic X logistics platform: sign-in, availability, shipment offers and trips.

## Features

- Arabic RTL interface with Tajawal typography
- Saudi mobile-number sign-in
- Driver dashboard: availability, daily KPIs, shipment offers
- Shipment offer details with accept / decline
- Typed API client generated from the backend OpenAPI contract
- Web build served by an unprivileged nginx container

## Tech stack

TypeScript · Expo · React Native · Expo Router · React Native Web · Playwright

## Quick start

```bash
cp .env.example .env
npm ci
npm run dev                   # http://localhost:8081
```

## Related repositories

| Repository | Purpose |
| --- | --- |
| [logistic-x/backend](https://github.com/logistic-x/backend) | Operations API |
| [logistic-x/logistic-x](https://github.com/logistic-x/logistic-x) | Product and architecture docs, design system, end-to-end stack |

---

## Developer guide

Standalone Arabic RTL Expo/React Native/TypeScript application with Expo Router.
The existing login, dashboard, offer details, styling, native targets, and SVG map
components are retained. The same app now builds as an independently hosted website.
Copy/deploy this directory alone; Python and a running API are unnecessary for
installation, development startup, tests, or build.

### Development and build

Requires Node.js 22 and npm:

```bash
npm ci
cp .env.example .env
npm run dev
```

PowerShell: use `Copy-Item .env.example .env` for first setup. The dev server runs
at `http://localhost:8081`. Native development remains `npm start`, `npm run android`,
and `npm run ios` (iOS requires macOS/Xcode). Expo SDK 51 is preserved.

```bash
npm run typecheck
npm test
npm run api:check
npm run build
npm run preview
```

`dist/` is a static SPA. Preview runs at `http://127.0.0.1:8081`; deploy it with SPA
fallback for `/auth/login`, `/driver/home`, and `/driver/orders/:id`.

```bash
npx playwright install chromium
npm run test:e2e
```

These browser tests block API calls and verify shell startup, RTL, responsive widths,
route protection, and offline error behavior. A backend is not required.

### API configuration

| Variable | Local default | Staging / production |
| --- | --- | --- |
| `EXPO_PUBLIC_API_URL` | `http://localhost:8000/v1` | Public HTTPS API URL ending in `/v1` |
| `EXPO_PUBLIC_APP_ENV` | `development` | `staging` or `production` |
| `EXPO_PUBLIC_USE_MOCK` | `false` | `false`; production always disables demo mode |

Expo embeds public variables at **build time**. Rebuild when the API URL/environment
changes; container runtime variables do not rewrite existing JavaScript. Never place
database credentials, JWT signing secrets, Redis URLs, or private API keys here.
For physical devices use a reachable network address instead of `localhost`.

Live requests use one client in `src/api/client.ts`. Endpoint methods, bodies, and
responses use types generated from `api/openapi.json`. View adapters map snake_case
to UI models. Unavailable coordinates/company ratings/offer deadlines remain absent;
they are not replaced with invented values. Decimal strings are converted for display;
the backend still owns calculations, state changes, validation, and authorization.

JWT email/password login supports `tenant_slug`. The optional phone login preserves
the backend's development-only contract; production OTP remains unimplemented.
The app validates protected requests with the server, signs out on 401, displays 403,
domain/validation errors and network failures, and handles no-content 204 responses.
Access/refresh tokens use the existing AsyncStorage session mechanism, now namespaced
by API URL and demo/live mode. They are cleared/revoked on logout. Automatic refresh
is not implemented; expired sessions require login. Cached profile data supports an
offline shell and does not authorize API access. AsyncStorage/native secure storage
hardening remains a separate production concern.

Development demo mode is explicitly opt-in (`EXPO_PUBLIC_USE_MOCK=true`) and shows
an Arabic banner indicating fictional data. It cannot be activated in production.
Unimplemented Nafath, registration, and some navigation destinations remain pre-existing
product gaps; the separation does not invent those services.

### Contract updates

Receive the backend's released `openapi.json` and replace this project's
`api/openapi.json`, then run:

```bash
npm run api:generate
npm run api:check
npm run typecheck
npm test
```

The checked-in schema and generated types make builds independent of both the API
process and the parent repository. Existing pagination/filter/sort parameters and
UTC ISO-8601 timestamps remain defined by the API; the current offer feed is a list.

### Docker deployment

```bash
docker build --build-arg EXPO_PUBLIC_API_URL=https://api.example.com/v1 --build-arg EXPO_PUBLIC_APP_ENV=production -t logistic_x/frontend .
docker run --rm -p 8081:8081 logistic_x/frontend
```

The runtime is unprivileged nginx serving only static assets, with SPA fallback and
`/health`. No backend, PostgreSQL, or Redis runtime dependency exists. Add the public
frontend origin to backend `CORS_ORIGINS`. Deploy TLS at your ingress/CDN.

For actual integration tests, start a backend with a **disposable database**. They
create a uniquely named tenant, users, warehouses and a shipment through real APIs:

```powershell
$env:FRONTEND_TEST_URL = "http://127.0.0.1:18081"
$env:LOGISTIC_X_TEST_API_URL = "http://127.0.0.1:18000/v1"
npm run test:integration
```

The frontend under test must have been built with the matching API URL. No backend
authentication or tenancy dependencies are overridden by these tests.

If the shell renders but requests fail, check the public API URL, API availability,
and CORS origin. A stale build needs rebuilding after environment changes. Use the
response request ID for support. Rollback by redeploying the previous static image;
no database migration or backend rollback is required for this application.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please report security issues privately as described in [SECURITY.md](SECURITY.md).

## License

Released under the [MIT License](LICENSE).
