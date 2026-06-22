# Domain Event Catalog

Events are emitted on state transitions (ADR-004). Each is **immutable**, carries an
**idempotency key** (`event_id`), a `tenant_id` (ADR-001), an `occurred_at`, and a
`version`. Persisted to `shipment_tracking_events` where a tracking row applies;
published to the in-process bus → Celery workers + projection builders (ADR-003/006).

## Naming
`<Aggregate><PastTenseVerb>` — e.g. `ShipmentAssigned`. Integration events (crossing
a context boundary, e.g. to ERP/notifications) are suffixed `*IntegrationEvent`.

## Shipment context
| Event | Trigger (code) | Payload (key fields) | Consumers |
|---|---|---|---|
| `ShipmentCreated` | `create_shipment()` | shipment_id, ref, client_id, origin/dest wh, weight, volume | warehouse_load proj, notify client |
| `ShipmentMarkedReady` | transition → `ready` | shipment_id | dispatch queue |
| `ShipmentAssigned` | `assign_driver_and_vehicle()` | shipment_id, driver_id, vehicle_id, assigned_at | driver push, active proj, driver_status proj |
| `ShipmentPickedUp` | transition → `in_transit` | shipment_id, event_time | ETA worker, client track |
| `ShipmentLocationReported` | event_type=`location_update` | shipment_id, lat, lng, event_time | live map proj, ETA |
| `ShipmentDelivered` | status → `delivered` (+POD) | shipment_id, delivered_at, evidence_url | settlement, daily_stats, notify |
| `ShipmentFailed` | transition → `failed` | shipment_id, failure_reason | exception center |
| `ShipmentReturned` | transition → `returned` | shipment_id | exception center, settlement |
| `ShipmentCancelled` | status → `cancelled` | shipment_id, cancelled_at | warehouse_load proj, notify |
| `ProofOfDeliveryCaptured` | event_type=`proof_of_delivery` | shipment_id, evidence_url, recorded_by | documents, settlement |
| `ShipmentExceptionRaised` | event_type=`exception` | shipment_id, notes | exception center, SLA |

## Fleet / Identity context
| Event | Trigger | Consumers |
|---|---|---|
| `DriverWentOnline` / `DriverWentOffline` | `PATCH /drivers/me {is_available}` (planned) | driver_status proj, dispatch |
| `VehicleStatusChanged` | vehicle status update | capacity, eligibility |
| `UserDeactivated` | `is_active=false` | session revocation |

## Integration events (cross-boundary)
| Event | To | Notes |
|---|---|---|
| `SettlementRequestedIntegrationEvent` | ERP/Billing | on `ShipmentDelivered` |
| `NotificationRequestedIntegrationEvent` | SMS/Push | assignment, delivery, exception |

## Guarantees
- **Ordering:** per-shipment, enforced by monotonic `event_time` in service.
- **Idempotency:** consumers dedupe on `event_id`.
- **Compensation:** reversals are *new* events; history is never mutated/deleted
  (cascade delete only when the parent shipment is hard-deleted).
