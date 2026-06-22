# API Gap Analysis — Driver App ↔ FastAPI Backend

Compares endpoints the **delivered driver app** (`mobile/src/api/driverApi.ts`)
expects against what the **backend** (`app/api/routes/*`) exposes today. This is the
concrete Phase 4 backend backlog to make the driver slice live (`USE_MOCK=false`).

Legend: ✅ exists & compatible · ⚠️ exists but mismatched · ❌ missing

| App call | Backend today | Status | Required change |
|---|---|---|---|
| `POST /auth/login` (phone) → `{token, driver}` | `POST /auth/login` (email+password) → `TokenResponse{access_token, user}` | ⚠️ | Add **phone+OTP** identity flow; return driver profile or add follow-up `GET /drivers/me`; align `token`↔`access_token`. |
| `GET /drivers/me` | only `/drivers`, `/drivers/{id}` (admin/manager) | ❌ | Add **self** endpoint resolving driver from JWT `sub`. |
| `GET /drivers/me/stats` | — | ❌ | Add KPI endpoint backed by `proj_driver_daily_stats` (ADR-006). |
| `PATCH /drivers/me {is_available}` | `PATCH /drivers/{id}` (admin/manager only) | ⚠️ | Allow **driver self** to toggle availability; emit `DriverWentOnline/Offline`. |
| `GET /shipments/nearby` | — | ❌ | Add geo/eligibility query over `ready` shipments near `home_warehouse`; project price/cargo/city/distance. |
| `GET /shipments/{id}` | exists, **admin/manager only** | ⚠️ | Extend RBAC so the **assigned driver** can read their shipment; enrich response (see fields below). |
| `POST /shipments/{id}/accept` | `POST /shipments/{id}/assign` (admin/manager, needs driver_id+vehicle_id) | ⚠️/❌ | Add **driver self-accept** that assigns the calling driver + their default vehicle, with the same exclusivity/capacity guards. |
| `POST /shipments/{id}/decline` | — | ❌ | Add decline (records offer rejection; re-queues offer). |

## Field/shape gaps (domain enrichment)
The driver UI needs commercial fields the core `Shipment` model does **not** store:

| App field | Backend equivalent | Action |
|---|---|---|
| `priceSar` (fare) | — | Add pricing (quote/rate context — new Billing context). |
| `cargoType` (مواد غذائية) | — | Add `cargo_type` to shipment or a goods sub-entity. |
| `originCity` / `destinationCity` | warehouse `city` (via join) | Project from `warehouses`. |
| `distanceKm`, `durationMinutes` | — | Compute via routing provider (ADR: maps integration). |
| `company` (shipper) | `client` (User) | Expose client org as a company profile. |
| `requiredVehicleLabel` | vehicle type (none on shipment) | Add `required_vehicle_type`. |

## Why this is healthy
The app was deliberately built **mock-first** with a typed `types.ts` mirroring the
models and a `USE_MOCK` switch — so these gaps are **additive** (new endpoints +
fields), not rewrites. Each maps to a Phase 4 task and a domain event (event-catalog).
