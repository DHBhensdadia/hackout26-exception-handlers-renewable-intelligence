# Implementation Plan — Renewable Energy Intelligence Platform (Frontend)

Project folder: `C:\Users\NISHIL DAVE\Desktop\HackOut\re-forecast`
Status: **DRAFT — awaiting approval**

---

## 1. Project identity

| Item | Decision |
|---|---|
| Working name | **Re-forecast** — Renewable Energy Intelligence & Decision Support Platform |
| Stack | Vite + React 19 + TypeScript + Tailwind CSS v4 (+ Vite router) |
| Charting | Lightweight custom SVG chart primitives (no heavy chart dep) |
| Theme | Ported from the Vunai reference — near-black canvas `#08090a`, elevated cards `#0f1011`, hairline borders, one indigo accent `#5e6ad2`, monochrome chrome |
| Fonts | Self-hosted: SUSE (body) · Josefin Sans (display) · Satoshi (headings) · Quicksand (nav) · IBM Plex Mono (labels/code) + Google Fonts fallback |
| Layout | Landing page (**/**) → CTA → Dashboard (**/dashboard**) with internal tabs |

Stack choice follows the backend spec's frontend guidance (React + TypeScript + Vite + Tailwind). We do NOT copy Vunai's Next.js app wholesale (carries Prisma + auth + admin + blog we don't need); we port its visual design system so the product looks like it belongs to the same "lab" family — professional, not AI-generated.

---

## 2. Outsourced requirements → decisions

| Source requirement | What the frontend shows |
|---|---|
| **Landing page** (from project spec) | Full product story: hero + "predict → optimize → understand → invest" flow, the 7 modules, planning horizons, MVP phases, tech stack, target users |
| **Dashboard** (from `input_output (1).md`) | Real ML contract surfaced 1:1: `POST /forecast` inputs (site_id / lat-lon cold start, tech, capacity_mw, horizon_h, tilt, azimuth, hub_height), the 6-model structure (2 techs × p10/p50/p90), and the response envelope (`issue_time_utc`, `model_version`, `weather_source`, per-hour `p10/p50/p90_mw`, `clearsky_mw`, `physics_mw`) |
| **Graphs** — "only when it fits" | Yes, where a visual earns its place: p10/p50/p90 band chart, clearsky-overlay chart, surplus/shortage bars, energy mix pie, forecast-vs-demand bars, site capacity bars. Fields like model metadata stay as tables/monospace, not forced into charts |
| **Not AI-generated look** | Strict recurring system: tokens, hairlines, tabs, panels, mono labels, mac-framed app window hero — copied from the lab's own design language |

---

## 3. Source-of-truth files

1. `renewable_energy_intelligence_platform_project_spec.md` — product context for the landing page.
2. `input_output (1).md` — the exact Model I/O contract (`xgb-q-0.1.0`, quantile regression, 6 models) the dashboard renders.
3. `Vunai/` — the reference design system: `public/css/style.css` (tokens/type/nav/buttons/cards), `public/css/devices.css` (`.appwin` mac window, `.cockpit`, `.metric`, `.chart-bars`, `.itable`, `.pill`, `.chip`, `.tabs`, `.panel2`), `public/fonts/*` (self-hosted woff2/ttf), `/js/gsap.min.js`, and the `site-chrome.tsx` nav/footer/navpill pattern.

---

## 4. Design & architecture (ported from Vunai)

### 4.1 Tokens & theme (`src/styles/`)
```
--bg:#08090a  --bg-elevated:#0f1011  --surface:#0f1011  --surface-2:#1c1c1f
--hairline:#23252a  --hairline-strong:#34343a
--text:#f7f8f8  --text-secondary:#d0d6e0  --text-muted:#8a8f98
--accent:#5e6ad2  --accent-2:#6e79e0           (single UI color)
--c-green:#4cb782  --c-blue:#4ea7fc  --c-purple:#828fff   (chart/status only)
--font-heading/nav/display/body/mono ; --r-sm/md/lg/pill ; --shadow-* ; --ease ; --t-fast/base
```

### 4.2 Component inventory
| Component | Reused from Vunai | Rebuilt |
|---|---|---|
| Navbar + mobile toggle | `.nav` / `.nav__inner` / `.nav__cta` / `.brand` | React-driven active links |
| Floating pill nav on scroll | `.navpill` + main.js scroll logic | React hook |
| Footer | `.footer` / `.footer__top` / social / `.footer__bottom` | React |
| CTA band | `.cta-band` + `.btn-hud` pill | React |
| Mac app window | `.appwin` / `.macbar` | Hero product mockup |
| Cockpit / metric / panel2 / tiles | `.cockpit` / `.metric` / `.panel2` / `.tile` | Dashboard stat row |
| Status pills & chips | `.pill--ok/warn/bad` / `.chip` | Forecast statuses |
| Tables | `.itable` | Per-hour forecast table, site registry |
| Tabs & steppers | `.tabs` / `.stepper` | Dashboard tabs, module steppers |
| Buttons | `.btn` / `.btn--ghost` / `.btn-arrow` / `.btn-hud` | CTAs |
| Charts | custom SVG primitives (band/area/bar/donut) styled on the tokens | New |

### 4.3 Data flow (dashboard)
- `src/api/client.ts` — `forecastSite()`, `forecastColdStart()`, `listSites()`; base URL from `import.meta.env`.
- `src/api/mock.ts` — deterministic mock generators producing **exact** `input_output.md` schema (per-hour `p10/p50/p90/clearsky/physics_mw`, guaranteed `p10≤p50≤p90`, solar 0 at night, values clamped to `[0,capacity_mw]`). Different seed per run → feels live.
- `src/config.ts` — `USE_MOCK` flag + `API_BASE_URL`. Flip to `USE_MOCK:false` → real parallel backend works immediately.
- `src/types.ts` — `ForecastRequest`, `ForecastResponse`, `SiteRecord`, `HourPoint` shared by mock + real client.

---

## 5. Page 1 — Landing (`src/pages/Landing.tsx`)

1. **Nav** — transparent full-width bar; on scroll collapses to floating pill (Vunai behavior).
2. **Hero** — dark cinematic backdrop (gradient + subtle animated shader/glow), eyebrow + headline + lead, two CTAs (`Launch the dashboard →`, `Explore the platform`), spec-strip (`24–72h`, `Solar + Wind`, `Quantile bands p10/p50/p90`, `Decision support`).
3. **Hero product window** — mac-framed `.appwin` mock of the forecasting dashboard (a live bans read surge we render inflated).
4. **Data → Decision flow** — "Predict power → optimize its use → understand future needs → invest efficiently" (Core principle from spec §1).
5. **Product flow strip** — Data → Forecast → Compare → Optimize → Plan → Invest → Decide (spec §5).
6. **Three horizons** — Short-term 24–72h / Medium seasonal / Long-term years (spec §4) as a 3-card grid.
7. **Seven modules** — Forecasting · Balance · Seasonal patterns · Reliability · Investment · Demand · Optimization (spec §7–13) as cards with mono indices.
8. **End-to-end scenario** — the ₹500 crore worked example (spec §27) as a stepper.
9. **Uncertainty principle** — "forecast ≠ guarantee" brand block (spec §26): three quantiles, their decisions (spec §7 of input_output).
10. **MVP phases** — Phase 1 → 3 runway (spec §28).
11. **Tech stack** — mono chip wall (React/Vite/TS/Tailwind | Python 3.12/FastAPI | XGBoost | PostgreSQL | Redis | OR-Tools | Open-Meteo) (spec §24).
12. **CTA band** → `/dashboard`, **Footer**.

---

## 6. Page 2 — Dashboard (`src/pages/Dashboard.tsx`)

Very wide, data-first. All numbers minted by the mock data layer (schema-exact). Real API wired behind `USE_MOCK`.

### 6.1 Header
Brand row + global run status (`xgb-q-0.1.0 · openmeteo:icon_seamless · 151 sites · conformal calibration ON`) + button to re-run forecast.

### 6.2 Controls panel (`Input` — mirrors `POST /forecast`)
- **Target mode** segmented: `Registered site` | `Cold start (lat/lon)`.
- Site mode: site dropdown from `GET /sites` mock (name, tech, capacity, in_training_data flag).
- Cold-start: latitude / longitude / tech / capacity_mw; advanced: tilt_deg, azimuth_deg, hub_height_m.
- **horizon_h** slider 1–72 (default 72) labeled "72 h".
- Output: a live JSON "request preview" in `.code-card`.

### 6.3 Output (`Forecast response`)
**Stats row** (4–5 `.metric` cards): Capacity · Horizon · p50 total · 80 % confidence band · Surplus/shortage verdict.

**Main chart — 24–72h forecast band** (custom SVG, the centerpiece):
- X = hour, Y = MW; solar `0` at night; p10–p90 **shaded band**, p50 bold line, clearsky_mw dashed, physics_mw dotted, capacity cap line.
- Tech switch flips Solar/Wind; tooltip on hover: time, p10/p50/p90, clearsky, physics.

**Surplus / Shortage analysis** (uses Module 2 logic from spec §8):
- Forecast counts: "Can we meet demand?" bar chart (forecast p50 vs demand curve vs storage headroom), shortage = red pill, surplus = green pill, recommended action card (`Charge storage`, `Hold backup`, `Curtail`...).

**Forecast vs potential** — "Is the system delivering its clearsky potential?" coverage bars.

**Energy mix donut** (solar vs wind share of the 72 h) — only on the portfolio summary; monochrome w/ accent slice.

### 6.4 Sites registry (`GET /sites`)
`.itable` rows: site_id · technology · capacity_mw · in_training_data flag · "Forecast →" button that loads that site into the controls. Highlights genuinely unseen sites (`in_training_data:false`).

### 6.5 Request integrity footer
Envelope fields printed in mono: `issue_time_utc`, `model_version`, `weather_source`, `location_is_estimated`, `site_id`.

Graphs used only where they inform: band chart, mix donut, demand-vs-gen bars, potential coverage bars; tables stay tables.

---

## 7. Tech/routing/scaffold

- Vite React-TS template; React Router (`/` Landing, `/dashboard` Dashboard).
- Tailwind v4 via `@tailwindcss/vite`; plus a `src/styles/tokens.css` carrying the ported Vunai tokens + shared classes.
- Fonts copied from `Vunai/public/fonts` into `src/assets/fonts` (self-hosting, but Google Fonts link also in `index.html` for fallback).
- No Prisma/auth/admin/blog — out of scope.
- package scripts: `dev`, `build`, `preview`, `typecheck`.

---

## 8. Implementation order

| # | Milestone | Deliverable | Verify |
|---|---|---|---|
| 1 | Scaffold | Vite React-TS app + router + Tailwind v4 + fonts | `npm run dev` boots, no console errors |
| 2 | Design system | tokens.css, shared components (nav, navpill hook, footer, CTA, buttons, appwin, pills, chips, tables) | Landing skeleton renders w/ theme |
| 3 | Data layer | types.ts, mock.ts (schema-exact), config.ts, client.ts | typecheck passes; mock output satisfies schema invariants |
| 4 | Landing page | Full hero → footer as §5 | Review layout + responsiveness |
| 5 | Chart primitives | band/area/bar/donut SVG components + tooltip hook | Charts render on sample data |
| 6 | Dashboard | Controls + forecast output + mix + surplus/shortage + sites table + integrity footer | Walk all states; desktop + mobile |
| 7 | Polish & verify | Reveal animations (ported `.reveal`/IntersectionObserver), reduced-motion, favicon, metadata, `npm run build` + `npm run typecheck` clean | Lighthouse-style pass |

---

## 9. What I will NOT do (to keep it professional, not AI-ish)

- No rainbow gradients, glassmorphism-only fashion, generic "Generated with ❤" fluff, or stock-photo mock cities.
- No lorem ipsum.
- No forced charts on data that reads better as a table (model metadata stays mono text).
- No fake "guaranteed" claims — the platform's whole point is calibrated uncertainty (`p10/p50/p90`), so copy reflects scenarios not promises.

---

## 10. Approval

Reply **"approve"** (or flag changes) and I will implement milestones 1→7 in order, starting with the scaffold and design system, then the landing page, then the dashboard.