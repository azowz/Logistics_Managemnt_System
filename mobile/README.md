# مسار · Mesaar — تطبيق السائق (Driver App)

A high-fidelity, **Arabic-first / RTL** mobile app for a land-freight logistics
platform, built for drivers. Dark "mission-control" design system, premium
cards, route-map visuals, and a mock API layer that is ready to swap for the
project's FastAPI backend (`../app`).

> React Native · Expo · Expo Router · TypeScript · RTL

---

## Screens (3 main paths)

| Route | الشاشة | Description |
| --- | --- | --- |
| `/auth/login` | تسجيل دخول السائق | Phone (+966) login, نفاذ SSO, Saudi-number validation |
| `/driver/home` | لوحة السائق | Online toggle, KPIs, nearby shipment requests, bottom nav |
| `/driver/orders/[id]` | عرض الشحنة | Full-screen route map, 15s countdown, accept/ignore sheet |

---

## Run the app

```bash
cd mobile
npm install
npm start            # then press i (iOS) / a (Android) / scan QR in Expo Go
```

- iOS simulator: `npm run ios` · Android emulator: `npm run android`
- Type-check only: `npm run typecheck`

### RTL note
The app forces RTL at startup (`I18nManager.forceRTL`). In **Expo Go / dev
client** it applies immediately. In a **bare/release build**, RTL fully applies
after the first reload (a known React Native constraint).

### Backend integration
The data layer is mock-first. To point at the live API:

```bash
EXPO_PUBLIC_USE_MOCK=false EXPO_PUBLIC_API_URL=https://your-host/v1 npm start
```

Each function in `src/api/driverApi.ts` documents the REST endpoint it maps to
(aligned with `app/api/routes/*` and `app/models/*` in the Python backend).

---

## Folder structure

```
mobile/
├── app/                          # Expo Router routes (file-based)
│   ├── _layout.tsx               # Root: RTL + fonts + providers + Stack
│   ├── index.tsx                 # Redirect → /auth/login
│   ├── auth/login.tsx            # Path 1
│   └── driver/
│       ├── home.tsx              # Path 2
│       └── orders/[id].tsx       # Path 3
├── assets/                       # Generated app icon + splash
└── src/
    ├── api/                      # API surface (mock-first, HTTP-ready)
    │   ├── client.ts             # fetch wrapper, auth token, USE_MOCK switch
    │   ├── driverApi.ts          # login / profile / stats / requests / order
    │   ├── types.ts              # Domain types mirroring the backend models
    │   └── index.ts
    ├── components/               # 15 reusable components (see below)
    ├── hooks/
    │   ├── useAppBootstrap.ts    # RTL + Tajawal font loading
    │   └── useCountdown.ts       # 15→0 offer timer
    ├── mock/                     # Driver, stats, requests, orders fixtures
    ├── store/session.tsx         # Auth + online/offline context
    ├── theme/                    # colors · spacing/radius/shadow · typography
    └── utils/                    # validation · format (Arabic numerals) · map projection
```

### Components
`AppLayout` · `AppText` · `Card` · `PrimaryButton` · `SecondaryButton` ·
`PhoneInput` · `Toggle` · `StatusCard` · `KPIBox` · `ShipmentRequestCard` ·
`MapPreview` · `RouteMap` · `BottomNav` · `CountdownBadge` · `OrderBottomSheet` ·
`DriverHeader`

---

## Design system

| Token | Value |
| --- | --- |
| Background | `#090D14` |
| Card | `#121821` |
| Border | `rgba(255,255,255,0.06)` |
| Primary (blue) | `#2F6BFF` |
| Success (green) | `#18C56E` |
| Text primary / secondary | `#F4F7FB` / `#7D8BA3` |
| Radius | 18–28px |
| Font | Tajawal (Arabic) with system fallback |

All tokens live in `src/theme/` and are the single source of truth.

---

## State logic implemented
- Saudi mobile validation (`05/5/+966/966`, Arabic digits) → E.164.
- Login → session context → `replace('/driver/home')`.
- Online/offline toggle (optimistic, reconciled via API).
- Tap a request → order details.
- Accept → `تم قبول الطلب` state + start-navigation CTA.
- Ignore / expired countdown → back to home.
- Countdown ring animates 15 → 0 (blue → orange → red).
