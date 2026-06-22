# Mesaar Screen Map

Role-based screens and the states each must implement. Built on
[`../design-system/components-index.md`](../design-system/components-index.md).
RBAC roles map to the backend `UserRole` enum (admin / manager / driver / client);
Operations + Dispatcher are both `manager` scoped by permission.

**Required states key:** D=default · L=loading(skeleton) · E=empty · X=error ·
P=no-permission · DN=dense-data · M=mobile-constrained. Every data screen must ship D/L/E/X/P.

## Driver (mobile — `driver`) — **largely shipped**
| Screen | Route | States | Status |
|---|---|---|---|
| Sign in | `/auth/login` | D, X | ✅ shipped (phone +966, نفاذ, validation, error) |
| Dashboard / task queue | `/driver/home` | D, L, E, X, M | ✅ shipped (online toggle, KPIs, offers, error/retry) |
| Offer / order detail | `/driver/orders/[id]` | D, L, X, M | ✅ shipped (map, countdown, accept→تم قبول, ignore) |
| Shift start | `/driver/shift` | D, X | ⏳ Phase 4 |
| Route map (active trip) | `/driver/navigation` | D, L, X, M | ⏳ |
| Stop detail + Pickup/POD | `/driver/stop/[id]` | D, L, X | ⏳ (POD upload, evidence_url) |
| Issue reporting | `/driver/issue` | D, X | ⏳ (exception event) |
| Vehicle inspection | `/driver/inspection` | D, X | ⏳ (checklist) |
| Chat | `/driver/messages` | D, L, E, X | ⏳ |
| Earnings / history | `/driver/performance` | D, L, E, X | ⏳ (driver_daily_stats) |
| Documents | `/driver/documents` | D, L, E, X | ⏳ |

## Operations / Control Tower (`manager`)
| Screen | States | Notes |
|---|---|---|
| Control tower (overview) | D, L, E, X, P | KPI band + live map + exception summary |
| Live map | D, L, X, DN | `proj_active_shipments` + driver locations |
| Shipment board | D, L, E, X, DN | columns by `ShipmentStatus`; drag = status transition (guarded) |
| Exception center | D, L, E, X, DN | `exception`/`failed` events; SLA-risk triage |
| ETA / SLA risk monitor | D, L, E, X | `proj_sla_risk` vs `delivery_due_at` |
| Capacity overview | D, L, X | `proj_warehouse_load` vs capacity |
| Claims / incidents | D, L, E, X | incident cards |
| AI copilot panel | D, L, X | side panel over any ops screen |

## Dispatcher (`manager`, dispatch-scoped)
| Screen | States | Notes |
|---|---|---|
| Planning board | D, L, E, X, DN | unassigned `ready` shipments |
| Load builder | D, L, E, X | group shipments → trip |
| Route planning | D, L, X | sequence stops, maps |
| Assignment queue | D, L, E, X | DispatchCard: driver+vehicle eligibility (exclusivity/capacity rules from `shipment_service`) |
| Dock scheduling | D, L, E, X, DN | warehouse slots |
| Carrier / driver pool | D, L, E, X, DN | availability via `proj_driver_status` |
| Comms center | D, L, E, X | broadcast/assignments |
| Settlement review | D, L, E, X, DN | delivered → settlement |

## Admin (`admin`)
| Screen | States | Notes |
|---|---|---|
| Org dashboard | D, L, X, P | tenant health |
| Users | D, L, E, X, P, DN | `/users` CRUD |
| Roles / RBAC | D, L, X, P | role→permission matrix |
| Tenant settings | D, X, P | shared-multitenant config (ADR-001) |
| Integrations | D, L, E, X | maps, نفاذ, SMS, ERP |
| Audit logs | D, L, E, X, DN | append-only audit stream |
| Policy center | D, X | SLA/retention policies |
| Feature flags | D, L, X | per-tenant toggles |
| Data retention | D, X | retention windows |
| Billing / config | D, L, X | plan config |

## Customer / Shipper (`client`, responsive web)
| Screen | States | Notes |
|---|---|---|
| Dashboard | D, L, E, X, P | shipment summary |
| Quote / book shipment | D, L, X | Stepper → `POST /shipments` |
| Track shipment | D, L, E, X, M | live map + Timeline of tracking events |
| Order detail | D, L, X | `ShipmentWithEvents` |
| Documents | D, L, E, X | POD, invoices |
| Notifications | D, L, E, X | — |
| Invoices | D, L, E, X, DN | settlement |
| Claims / support | D, L, E, X | — |
| Address book | D, L, E, X | warehouses/locations |
| Analytics | D, L, E, X | volume/spend |

## Coverage summary
| Role | Screens | Shipped | Remaining |
|---|---|---|---|
| Driver | 11 | 3 core | 8 (Phase 4) |
| Operations | 8 | 0 | 8 |
| Dispatcher | 8 | 0 | 8 |
| Admin | 10 | 0 | 10 (CRUD APIs exist) |
| Customer | 10 | 0 | 10 |
| **Total** | **47** | **3** | **44** |

Each remaining screen has a concrete API mapping (existing route or the planned
endpoints in [`../docs/api-gap-analysis.md`](../docs/api-gap-analysis.md)).
