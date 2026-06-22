# WCAG 2.2 AA Conformance Checklist — Mesaar Consoles

Target: **WCAG 2.2 Level AA** (all A + AA criteria) for the web consoles; the driver app
follows platform (iOS/Android) accessibility equivalents. This is a **Phase 4 build gate**
(automated axe scan + manual audit in CI). Status legend: ✅ designed-in · ⚙️ build task · 🔎 manual-audit.

## Perceivable
| SC | Lvl | Requirement | Mesaar approach | Status |
|---|---|---|---|---|
| 1.1.1 | A | Non-text alternatives | Every icon/map/chart has `aria-label`/alt; status never icon-only | ⚙️ |
| 1.3.1 | A | Info & relationships | Semantic landmarks, `<th scope>`, fieldset/legend on forms | ⚙️ |
| 1.3.4 | AA | Orientation | No orientation lock; reflow both ways | ✅ |
| 1.3.5 | AA | Identify input purpose | `autocomplete` on phone/email/name (driver login already sets `tel`) | ✅ |
| 1.4.3 | AA | Contrast ≥ 4.5:1 | `text.primary/secondary` pass on all surfaces; `text.muted` = large/decorative only | ✅ tokens |
| 1.4.10 | AA | Reflow (320px) | Fluid layout; tables → stacked/scroll; no 2-D scroll for content | ⚙️ |
| 1.4.11 | AA | Non-text contrast ≥ 3:1 | Borders `borderStrong`, focus ring `#5C8DFF`, status fills meet 3:1 | ✅ tokens |
| 1.4.12 | AA | Text spacing | Layouts tolerate user spacing overrides (no clipping) | 🔎 |
| 1.4.13 | AA | Content on hover/focus | Tooltips/popovers dismissible, hoverable, persistent | ⚙️ |

## Operable
| SC | Lvl | Requirement | Mesaar approach | Status |
|---|---|---|---|---|
| 2.1.1 | A | Keyboard | All actions keyboard-reachable; DataGrid arrow-key nav; CommandPalette ⌘K | ⚙️ |
| 2.1.2 | A | No keyboard trap | Modals/drawers trap then restore focus on close | ⚙️ |
| 2.4.3 | A | Focus order | Logical, RTL-aware tab order | ⚙️ |
| 2.4.7 | AA | Focus visible | 2px `brand.focusRing` outline on every interactive (`:focus-visible`) | ✅ tokens |
| **2.4.11** | AA | **Focus not obscured (min)** *(2.2)* | Sticky topbar/sheets never fully cover the focused element; scroll-padding set | ⚙️ |
| 2.5.3 | A | Label in name | Visible label text included in accessible name | ⚙️ |
| **2.5.7** | AA | **Dragging movements** *(2.2)* | Board drag-to-transition + map pan have non-drag alternatives (menu/buttons) | ⚙️ |
| **2.5.8** | AA | **Target size ≥ 24×24** *(2.2)* | `size.minTarget = 24`; controls 36/44/56; icon buttons padded | ✅ tokens |
| 2.3.1 | A | Three flashes | No flashing; pulse animation is slow + opacity-only | ✅ |
| — | — | Reduced motion | `prefers-reduced-motion` disables pulse/ring/slide | ✅ |

## Understandable
| SC | Lvl | Requirement | Mesaar approach | Status |
|---|---|---|---|---|
| 3.1.1 / 3.1.2 | A | Language of page/parts | `lang="ar" dir="rtl"`; English fragments marked `lang="en"` | ⚙️ |
| 3.2.3 / 3.2.4 | AA | Consistent nav & identification | Shared AppShell/Sidebar; components named consistently | ✅ |
| **3.2.6** | A | **Consistent help** *(2.2)* | Support/help entry in a consistent topbar location across screens | ⚙️ |
| 3.3.1 / 3.3.3 | A/AA | Error identification + suggestion | Inline field errors with fix suggestions (driver phone errors already do this) | ✅ pattern |
| **3.3.7** | A | **Redundant entry** *(2.2)* | Multi-step flows (booking) don't re-ask known data; autofill prior steps | ⚙️ |
| **3.3.8** | AA | **Accessible authentication (min)** *(2.2)* | Phone+OTP / نفاذ SSO — no cognitive-test/puzzle; OTP paste allowed | ✅ design |

## Robust
| SC | Lvl | Requirement | Mesaar approach | Status |
|---|---|---|---|---|
| 4.1.2 | A | Name/role/value | Components expose proper ARIA roles/states (switch, tab, dialog) | ⚙️ |
| 4.1.3 | AA | Status messages | Toasts/async results via `aria-live`; projection "as of" announced | ⚙️ |

## RTL-specific audit (beyond WCAG, required for Arabic)
- Layout mirrors via logical properties; maps/charts/logos do **not** flip.
- Directional icons mirror; object/status icons don't.
- Arabic-Indic numerals in Arabic locale; LTR isolation for phone/codes/IDs.
- Screen-reader pronunciation tested with Arabic TalkBack/VoiceOver.

## Gate
CI runs `axe-core` on every console route (fail on violations) + a manual audit of the 🔎/⚙️
rows per release (WCAG 2.2 AA sign-off in `qa/final-acceptance-test-plan.md`, Phase 5).
