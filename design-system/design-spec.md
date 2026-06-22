# Mesaar Design System — Specification

**Status:** Phase 3 draft for gate review. **Mode:** dark-first. **Direction:** RTL-first.
**Single source of truth:** [`tokens.json`](./tokens.json), already realized in the
shipped mobile theme (`mobile/src/theme/*`). The web consoles consume the same
tokens (compiled to CSS variables), so mobile and web never drift.

## 1. Principles
1. **Mission-control calm** — deep navy-black canvas, restrained accents, data-forward.
2. **One token source** — no hard-coded colors/spacing in components; tokens only.
3. **RTL-first, locale-mirrored** — author in CSS logical properties; LTR is free.
4. **Density is a mode, not a redesign** — comfortable (default) and dense (ops grids).
5. **Accessible by construction** — WCAG 2.2 AA is a build gate, not a review note.

## 2. Color
Full palette in `tokens.json → color`. Roles:

| Role | Token | Value |
|---|---|---|
| Canvas | `core.background` | `#090D14` |
| Surface / card | `core.surface` | `#121821` |
| Elevated surface | `core.surfaceElevated` | `#161D29` |
| Hairline / strong border | `core.border` / `core.borderStrong` | `rgba(255,255,255,.06)` / `.12` |
| Primary action | `brand.primary` | `#2F6BFF` |
| Focus ring | `brand.focusRing` | `#5C8DFF` |
| Success / Warning / Danger / Info | `status.*` | `#18C56E` / `#FFB020` / `#FF5A5F` / `#3BA0FF` |
| Text primary / secondary / muted | `text.*` | `#F4F7FB` / `#7D8BA3` / `#5A6678` |

**Shipment-status colors** (`color.shipmentStatus.*`) map 1:1 to the backend
`ShipmentStatus` enum so a status pill is consistent everywhere (board, timeline, map).

**Contrast (WCAG 1.4.3):** `text.primary` and `text.secondary` pass AA (≥4.5:1) on all
surfaces. `text.muted` is **AA-large / decorative only** — never use for body text.
Status colors are paired with a soft background + icon/label (never color-only).

## 3. Typography
`tokens.json → font`. Arabic = **Tajawal**; Latin/numeric = **Inter**; code = JetBrains Mono.
Scale: `display, h1, h2, h3, bodyStrong, body, caption, micro, numeric`. Numerals render
Arabic-Indic in Arabic locale (see `mobile/src/utils/format.ts`), Western in Latin.

## 4. Spacing, radius, sizing
4-pt spacing scale (`space`), radius 10–28 (`radius`, cards land 18–24), control heights
36/44/56 with a **24×24 minimum hit target** (WCAG 2.5.8). Sidebar 264 / 72 collapsed.

## 5. Density modes
- **Comfortable** (default): row height 52, `space.lg` paddings — dashboards, detail.
- **Dense**: row height 40, tighter paddings — data grids, shipment board, exception center.
Toggle is a single data attribute (`data-density`) reading `size.rowHeight*` tokens.

## 6. Elevation & motion
3 shadow levels (`shadow.card|floating|popover`); z-index ladder in `z.*`. Motion uses
`motion.easing` with fast/base/slow durations; respect `prefers-reduced-motion`
(disable non-essential transitions — pulse, ring, slide).

## 7. Component states (mandatory per component)
Every interactive component must define: **default, hover, focus-visible, active/pressed,
disabled, loading, error, selected** — and every data surface: **default, loading
(skeleton), empty, error, no-permission**. These are enumerated per screen in
[`../ui/screen-map.md`](../ui/screen-map.md).

## 8. RTL rules
- Use logical properties (`margin-inline-start`, `inset-inline-end`, `text-align: start`).
- Mirror layout, **not** content: maps, media, numeric charts, and brand logos do **not** flip.
- Directional icons (chevrons, back) mirror; status/object icons do not. (The driver app's
  arrows already follow this — see the audit note on `arrow-back/forward`.)

## 9. Platform realization
| Platform | Consumes tokens via | Status |
|---|---|---|
| Driver mobile (Expo) | `mobile/src/theme/*` (TS) | **Shipped** |
| Web consoles | `tokens.json` → CSS custom properties (Style Dictionary) | Phase 4 build |
| Figma library | optional push via Figma MCP (`/figma-generate-library`) | On request |

## 10. Inventory
Component library: [`components-index.md`](./components-index.md) (50+ components).
Screens per role with states: [`../ui/screen-map.md`](../ui/screen-map.md).
Accessibility gate: [`../docs/wcag-2.2-aa-checklist.md`](../docs/wcag-2.2-aa-checklist.md).
