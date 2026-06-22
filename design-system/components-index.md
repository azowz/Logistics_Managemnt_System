# Mesaar Component Library Index

50+ components for the design system. Tokens from [`tokens.json`](./tokens.json); states
defined in [`design-spec.md`](./design-spec.md) §7. **Reuse** marks components already
shipped in the driver app (`mobile/src/components`) that the web library inherits or ports.

Every interactive component supports: default · hover · focus-visible · active · disabled ·
loading · error. Every data surface supports: default · loading (skeleton) · empty · error ·
no-permission. All are RTL-mirrored via logical properties.

## App shell & layout (6)
| # | Component | Purpose | Key variants / props | Reuse |
|---|---|---|---|---|
| 1 | AppShell | Console frame (sidebar + topbar + content) | collapsed, density | — |
| 2 | AppLayout | Screen scaffold (canvas, glow, safe-area, scroll) | scroll, bleed, edges | ✅ mobile |
| 3 | Sidebar / NavRail | Primary role navigation | expanded/collapsed, sections | — |
| 4 | TopBar | Search, tenant switch, profile, notifications | — | — |
| 5 | PageHeader | Title, breadcrumb, actions, status | withTabs | — |
| 6 | Card | Rounded surface primitive | elevated, padded, muted | ✅ mobile |

## Navigation (7)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 7 | Breadcrumb | Path context | — | — |
| 8 | Tabs | Section switch | underline, pill | — |
| 9 | SegmentedControl | Compact mode switch (e.g. density) | 2–4 segments | — |
| 10 | BottomNav | Mobile tab bar | active blue state, badges | ✅ mobile |
| 11 | Pagination | Table paging | numbered, load-more | — |
| 12 | CommandPalette | ⌘K quick nav/actions | — | — |
| 13 | Stepper | Multi-step flows (booking, onboarding) | horizontal/vertical | — |

## Inputs & forms (12)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 14 | TextInput | Text entry | sizes, prefix/suffix, error | — |
| 15 | PhoneInput | Saudi +966 phone, LTR digits | error, showError | ✅ mobile |
| 16 | PasswordInput | Masked entry + reveal | — | — |
| 17 | Textarea | Multi-line | autosize | — |
| 18 | Select / Combobox | Single choice | searchable | — |
| 19 | MultiSelect | Multi choice + chips | — | — |
| 20 | Autocomplete | Async suggest (warehouse, client) | — | — |
| 21 | DatePicker / RangePicker | Dates (pickup, due, reports) | single, range | — |
| 22 | Checkbox / Radio | Boolean / single | group | — |
| 23 | Toggle | On/off switch (RTL-aware knob) | sizes, color | ✅ mobile |
| 24 | Slider | Range value (capacity filters) | single, dual | — |
| 25 | FileUpload | POD / document upload | drag, preview | — |

## Buttons & actions (4)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 26 | PrimaryButton | Main CTA | primary, success; icon, loading | ✅ mobile |
| 27 | SecondaryButton | Secondary action | outline, ghost; danger | ✅ mobile |
| 28 | IconButton | Icon-only action (+ optional badge) | sizes, badge | (refactor target) |
| 29 | SplitButton / Menu | Action + dropdown | — | — |

## Data display (12)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 30 | DataGrid | Dense sortable/filterable table | dense, sticky, selectable | — |
| 31 | Table | Standard table | — | — |
| 32 | FilterBar | Faceted filters + saved views | — | — |
| 33 | KPIBox | Metric tile | icon, unit, tint | ✅ mobile |
| 34 | StatCard / ChartCard | Metric + sparkline/chart | — | partial (KPIBox) |
| 35 | StatusPill | Shipment/vehicle status chip | per ShipmentStatus | (in cards) |
| 36 | Badge | Count/label badge (RTL `end` position) | notification, label | (refactor target) |
| 37 | Chip / Tag | Inline attribute | removable | (in ShipmentRequestCard) |
| 38 | Avatar | User/driver initials | sizes | (in DriverHeader) |
| 39 | Timeline | Tracking-event history | vertical | (OrderBottomSheet stops) |
| 40 | ActivityFeed | Audit/event stream | — | — |
| 41 | DescriptionList | Key/value detail blocks | — | (OrderBottomSheet metrics) |

## Feedback & overlays (8)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 42 | Toast | Transient notification | success/error/info | — |
| 43 | InlineAlert / Banner | Persistent message | tones | ✅ (login/home banners) |
| 44 | Modal / Dialog | Focused task / confirm | sizes | — |
| 45 | Drawer / BottomSheet | Side/bottom panel | side, bottom | ✅ (OrderBottomSheet) |
| 46 | Tooltip / Popover | Contextual help/menu | — | — |
| 47 | Skeleton | Loading placeholder | text, card, row | — |
| 48 | EmptyState | No-data illustration + CTA | — | ✅ (offline state) |
| 49 | ErrorBoundary | Contain runtime errors | — | ✅ mobile |
| 50 | ProgressBar / Ring | Determinate progress | bar, ring | ✅ (CountdownBadge ring) |

## Logistics-specific (10)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 51 | ShipmentRequestCard | Offer row (route, cargo, fare) | — | ✅ mobile |
| 52 | OrderBottomSheet | Offer summary + accept/ignore | accepted state | ✅ mobile |
| 53 | StatusCard | Online/offline hero + toggle | — | ✅ mobile |
| 54 | DriverHeader | Greeting + plate + bell | — | ✅ mobile |
| 55 | CountdownBadge | Offer-window ring | sizes | ✅ mobile |
| 56 | RouteStopCard | Pickup/dropoff stop detail | — | (in OrderBottomSheet) |
| 57 | DispatchCard | Assignment candidate (driver+vehicle) | — | — |
| 58 | VehicleChecklistCard | Pre-trip inspection | — | — |
| 59 | IncidentCard / ExceptionCard | SLA/exception item | severity | — |
| 60 | CompanyCard | Shipper org + rating | — | ✅ (in OrderBottomSheet) |

## Maps & charts (5)
| # | Component | Purpose | Variants | Reuse |
|---|---|---|---|---|
| 61 | RouteMap | Full route visual (SVG) | compact | ✅ mobile |
| 62 | MapPreview | Compact route card | — | ✅ mobile |
| 63 | LiveMapPanel | Control-tower fleet map | clusters, filters | — |
| 64 | Sparkline | Inline trend | — | — |
| 65 | Chart (line/bar/donut) | KPI/analytics | — | — |

**Totals:** 65 components specified; **18 already shipped** in the driver app (✅) and
3 flagged as refactor targets (Badge, IconButton, StatusPill — extracted from the audit's
reusability findings). Web build (Phase 4) ports the ✅ set and builds the rest on `tokens.json`.
