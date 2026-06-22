# Domain Glossary (Ubiquitous Language)

Grounded in `app/models/*` and `app/services/*`. Use these terms consistently across
code, API, UI (Arabic labels in parentheses where the driver app uses them).

| Term | Definition | Source |
|---|---|---|
| **User** | Authenticated account with exactly one `role`. | `models/user.py` |
| **Role** | `admin`, `manager`, `driver`, `client`. RBAC enforced via `require_roles`. | `enums.py`, `core/security.py` |
| **Driver** (السائق) | Operational profile for a `driver`-role user; has `license_*`, `is_available`, `home_warehouse`. | `models/driver.py` |
| **Vehicle** (شاحنة) | Transport asset with `plate_number`, capacity, `status`. Only `active` is assignable. | `models/vehicle.py` |
| **Warehouse** (مستودع) | Physical node with geolocation + weight/volume capacity + `max_daily_shipments`. | `models/warehouse.py` |
| **Shipment** (شحنة) | Aggregate root: goods moving origin→destination, with lifecycle `status`. | `models/shipment.py` |
| **Reference code** | Human-readable unique shipment id (no whitespace, 3–64 chars). | `schemas/shipment.py` |
| **Assignment** | Binding a `driver` + `vehicle` to a shipment; sets `assigned_at`, status→`assigned`. Exclusive over active shipments. | `services/shipment_service.py` |
| **Active shipment** | status ∈ {created, ready, assigned, in_transit}. Counts toward warehouse load + driver/vehicle exclusivity. | `ACTIVE_STATUSES` |
| **Tracking event** | Immutable, time-ordered record on a shipment (`status_update`, `location_update`, `proof_of_delivery`, `exception`). | `models/shipment_tracking_event.py` |
| **POD** (إثبات التسليم) | Proof of delivery: a tracking event with `evidence_url`. | `enums.py` |
| **Capacity** | Warehouse/vehicle weight (kg) + volume (m³) limits; validated before create/assign. | `services/shipment_service.py` |
| **Transition** | Allowed status change per the lifecycle map; illegal ones raise `StatusTransitionError`. | `_is_transition_allowed` |
| **Projection** (read model) | Denormalized table serving console reads, built from events. | ADR-006 |
| **Tenant** | Isolation boundary (`tenant_id`), planned per ADR-001. | ADR-001 |
| **Offer** (عرض شحنة) | Driver-app surface for a `ready` shipment presented for acceptance (15s window). | driver app + planned `/shipments/nearby` |
