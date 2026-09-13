# Frontend Audit — `re-forecast`

**Project:** hackout26-exception-handlers-renewable-intelligence
**Audit date:** 2026-09-13
**Auditor:** opencode
**Scope:** Entire `src/` tree, build config, `index.html`, public assets, produced production bundle.
**Method:** Static code review, CSS/selector analysis, dependency + asset inventory, production build (`vite build`) and type check.

---

## 1. Executive summary

The app is a polished, well-themed **React 19 + TypeScript + Vite 6 + React Router 7** single-page app with a marketing landing page and a 7-module "decision console" dashboard. Visual craft is high (consistent dark design tokens, ruled-grid system, charts), and the code type-checks and builds cleanly with no `any`, no TODOs, and only one `eslint-disable`.

It is, however, **not production-ready**. The main risks fall into five buckets:

1. **Performance / payload** — no route code-splitting, ~2.2 MB of unused images and ~280 KB of unused fonts shipped, uncompressed TTF variable fonts, unused Google `Inter` font loaded, and Tailwind included but effectively unused.
2. **Accessibility** — almost no visible keyboard focus, sortable table headers are mouse-only, chart data is mouse-only, and some ARIA menu patterns lack required keyboard behavior.
3. **Responsiveness** — a 7-column pipeline grid never collapses, and hero-console inner grids are inline-fixed.
4. **Data-layer correctness** — non-deterministic mock, no request cancellation (stale-response race), two conflicting demand curves, duplicated helpers.
5. **Dead code / maintainability** — many unused exports, a large amount of dead CSS, and hooks importing from components.

A full **scorecard**, a **prioritized roadmap (P0/P1/P2)** and a **quick-wins checklist** are at the end.

### Scorecard

| Area | Grade | One-line verdict |
|---|---|---|
| Visual design / theming | **A** | Coherent tokens, strong craft |
| Component structure | **B** | Clean split, but hook↔component coupling |
| Performance / bundle | **D** | No splitting, huge unused assets, redundant deps |
| Accessibility | **D** | Focus, keyboard, and chart a11y gaps |
| Responsiveness | **C−** | One broken grid + inline-fixed grids |
| Data layer / correctness | **C** | Mock race + duplicate/conflicting logic |
| SEO / metadata | **D** | Title + description only |
| Testing / tooling | **F** | No tests, no linter config |
| Code hygiene | **C** | Type-clean, but sizable dead code |

---

## 2. Project snapshot

| Item | Value |
|---|---|
| Framework | React `^19.0.0`, `react-dom ^19` |
| Router | `react-router-dom ^7.1.1` (client-only `BrowserRouter`) |
| Build | Vite `^6.0.7`, `@vitejs/plugin-react ^4.3.4` |
| Styling | Hand-written CSS + CSS variables; Tailwind v4 imported |
| Icons | `lucide-react ^0.468.0` |
| State | React context + hooks (no external store) |
| Source | 47 TS/TSX files, 3,475 lines; 3 CSS files, 3,179 lines |
| Build result | ✅ passes `tsc -b` and `vite build` |
| JS bundle | **342.52 kB** (107.01 kB gzip), 1,635 modules, single chunk |
| CSS bundle | **64.24 kB** (13.04 kB gzip) |
| Tests | none |
| Lint | no ESLint config / script (only one inline disable) |

### Routes

| Path | Component |
|---|---|
| `/` | `Landing` |
| `/dashboard` | index → `OverviewModule` |
| `/dashboard/forecast` | `ForecastModule` |
| `/dashboard/balance` | `BalanceModule` |
| `/dashboard/reliability` | `ReliabilityModule` |
| `/dashboard/seasonal` | `SeasonalModule` |
| `/dashboard/demand` | `DemandModule` |
| `/dashboard/investment` | `InvestmentModule` |
| `*` | falls back to `Landing` (`src/main.tsx:38`) |

---

## 3. P0 — Critical issues (fix first)

### 3.1 No code-splitting: the whole dashboard ships on the landing page
`src/main.tsx:7-17` statically imports `Landing`, `DashboardLayout` and **all seven module components**. The landing page therefore downloads and parses the entire dashboard (charts, tables, derive math) before first paint.

**Impact:** slower LCP/TTI on the marketing page; wasted work for users who never open the dashboard.
**Fix:** lazy-load the dashboard branch and each panel.

```tsx
// main.tsx
import { lazy, Suspense } from "react";
const Landing = lazy(() => import("@/pages/Landing"));
const DashboardLayout = lazy(() => import("@/pages/dashboard/DashboardLayout"));

<Suspense fallback={<FullPageLoader />}>
  <Routes>{/* ... */}</Routes>
</Suspense>
```

Also add manual chunking in `vite.config.ts` (`build.rollupOptions.output.manualChunks`) to split `react`/`react-dom`/`react-router`.

### 3.2 ~2.2 MB of unused images and ~280 KB of unused fonts are deployed
`public/images/` contains `hero-robot.png` (930 KB), `hand-right.png` (725 KB), `hand-left.png` (587 KB) — **none referenced anywhere** in `src/` or `index.html`. `public/fonts/` ships `pilcrow-*`, `ranade-*`, `dmmono-*` (≈ 280 KB) that are **never referenced** by any `@font-face`.

**Impact:** deployment/repo bloat, slower CI, accidental CDN cost. (These are only downloaded if referenced, but they are copied into `dist/` — see build output.)
**Fix:** delete unused assets; if a future hero robot illustration is needed, convert to WebP/AVIF and reference it. See `dist/` inventory in §14.

### 3.3 Uncompressed variable fonts
`public/fonts/suse-var.ttf` (**220 KB**) and `josefin-sans-var.ttf` (**117 KB**) are raw `.ttf` and are the primary body/display fonts (`src/styles/tokens.css:128-129,80,87`).

**Fix:** convert to `woff2` (usually 60–75 % smaller), subset to `latin`, and `preload` the two or three faces used above the fold.
**Expected saving:** ~250 KB → ~60–80 KB.

### 3.4 Sortable table headers are not keyboard accessible
`src/components/dashboard/ForecastTable.tsx:79-88` attaches sorting to `<th onClick>` with no `tabIndex`, `role`, or keyboard handler. Keyboard and screen-reader users cannot sort.

**Fix:** render a real `<button>` inside the `<th>` and keep `aria-sort` on the `<th>`:

```tsx
<th aria-sort={...}>
  <button type="button" className="th-sort" onClick={() => click(c.key)}>
    {c.label} {dir === 1 ? "↑" : "↓"}
  </button>
</th>
```

### 3.5 No visible focus styles
Only two focus rules exist in the entire codebase — `.cp__select select:focus, .cp__input:focus` (`src/styles/global.css:1630-1634`). `dashboard.css` has **zero** `:focus` rules. Buttons, links, menu items, nav links and table headers show no visible focus ring.

**Fix:** add a global, brand-consistent focus ring and never remove outlines without replacement.

```css
:where(a, button, [role="button"], input, select, textarea, summary, th[aria-sort]):focus-visible {
  outline: 2px solid var(--accent-2);
  outline-offset: 2px;
  border-radius: 2px;
}
```

### 3.6 Stale-response race in forecast runs
`src/hooks/useDashboard.ts:64-71` fires `forecast(...).then(setResult)` with no cancellation. Running twice quickly (e.g. clicking "Run forecast" repeatedly, or picking a site while a run is in flight) lets an older response overwrite a newer one.

**Fix:** use `AbortController` and cancel the previous request; add request timeouts.

```ts
const ctrl = new AbortController();
// pass { signal: ctrl.signal } into fetch, and ctrl.abort() before a new run
```

---

## 4. Performance & bundle

| Finding | Location | Impact | Fix |
|---|---|---|---|
| No route/module code-splitting | `src/main.tsx:7-17` | Initial JS 342 kB for all users | `React.lazy` + `manualChunks` |
| Tailwind imported but not used | `src/styles/tokens.css:7` | Extra dependency, config, scan time; its reset duplicates the custom reset in tokens.css:161-204 | Remove `@import "tailwindcss"` and the Tailwind Vite plugin, or commit to using utilities |
| Unused Google font `Inter` (6 weights) | `index.html:14-17` | Render-blocking `<link>` for a font that is only a *fallback* (Satoshi/SUSE are primary) | Drop `Inter` from the Google URL; keep only `IBM Plex Mono` (or self-host it) |
| Non-preloaded self-hosted fonts | `src/styles/tokens.css:10-88`, `index.html` | FOUT/CLS on headings/body | `<link rel="preload" as="font" type="font/woff2" crossorigin>` for Satoshi-medium + SUSE + Josefin |
| 5 font families (Satoshi, Quicksand, Josefin Sans, SUSE, IBM Plex Mono) | `tokens.css:126-130` | Many downloads, inconsistent typographic voice | Reduce to 2–3 families (e.g. one display, one body, one mono) |
| Large inline SVG/div mock chart in hero | `HeroConsole.tsx:52-71` | 16 divs always rendered | Fine, but consider a single static SVG |
| ResizeObserver per chart, no throttle | `hooks/useMeasure.ts:12` | Minor layout thrash on resize | Optional: rAF-throttle |
| `toLocaleString` in hot loops/render | `lib/format.ts`, `util.ts:29` | Minor | Cache formatters (`Intl.NumberFormat`) |
| No `base` configured for sub-path deploys | `vite.config.ts` | Breaks if deployed under a path | Add `base` from env |

**Bundle action items**

1. Lazy dashboard + modules (P0).
2. `manualChunks`: `react`, `react-dom`, `react-router-dom`, `lucide-react`.
3. Delete unused assets (§3.2) and convert TTFs (§3.3).
4. Remove Tailwind or adopt it deliberately.
5. Consider dropping `lucide-react` for ~10 inline SVGs if bundle pressure remains (it tree-shakes, so lower priority).

---

## 5. Accessibility (a11y)

**Strengths:** good `aria-*` usage overall (58 occurrences), charts have `role="img"` + descriptive `aria-label` (`ForecastBandChart.tsx:93-94`, `BalanceChart.tsx:65-66`), native `<dialog>` for the drawer, `aria-expanded`/`aria-pressed` on toggles, reduced-motion handled globally (`global.css:1361-1380`), and a custom scrollbar.

**Gaps**

| # | Issue | Location | Fix |
|---|---|---|---|
| 1 | No focus-visible styles (P0) | `global.css` (only 2 focus rules) | Global `:focus-visible` ring |
| 2 | Sortable `<th onClick>` not focusable | `ForecastTable.tsx:79-88` | `<button>` inside `<th>` |
| 3 | Chart tooltips mouse-only | `ForecastBandChart.tsx:75-79` | Add keyboard focus per point, or expose data in the already-present table; `onFocus`/arrow keys |
| 4 | ARIA `menu`/`menuitemradio` without arrow-key nav | `Sidebar.tsx:50-76` | Implement roving tabindex + Arrow/Home/End/Escape, or drop the menu roles and use a plain list of buttons |
| 5 | `<a>` without `href` (not focusable, no-op) | `HeroConsole.tsx:21-26` | Use `<span>` for decorative nav or real links |
| 6 | Header nav missing `aria-current="page"` | `SiteNav.tsx:20-38` | Set `aria-current` (NavLink does this automatically; header uses manual `isActive`) |
| 7 | No "skip to content" link | layout | Add a visually-hidden skip link to `#main` |
| 8 | Landing has no `<main>` landmark | `Landing.tsx` | Wrap body sections in `<main id="main">` |
| 9 | Tiny type: labels at `0.58–0.68rem` (~9–11px), uppercase mono | dashboard.css widely | Raise minimum to `0.72–0.75rem`; reserve micro-type for non-essential meta |
| 10 | `aria-label` on a non-interactive `<div>` | `HeroConsole.tsx:8` | Use `role="img"` or `figure`/`figcaption` if it conveys content |
| 11 | Dialog backdrop close has no explicit cancel semantics | `ControlsDrawer.tsx:24-26` | Native `<dialog>` already closes on Esc; ensure `onCancel` is handled and returns focus |
| 12 | Color as the only status signal in some tags | `DecisionCallout.tsx`, tags | Most tags include text labels (good); keep label + color, never color alone |

**Contrast check:** `--text-muted #8a8f98` on `--bg #08090a` ≈ **6.1:1** and `--text-secondary #d0d6e0` ≈ far higher — body/muted text passes WCAG AA. The concern is **size**, not contrast.

---

## 6. UX & responsiveness

| # | Issue | Location | Fix |
|---|---|---|---|
| 1 | **`.grid--7` is undefined** and forced with inline `gridTemplateColumns: "repeat(7, 1fr)"` — 7 unshrinkable columns on mobile | `Landing.tsx:268`; class list `global.css:749-768` only defines `--2/--3/--4` | Define `.grid--7` with responsive collapse, e.g. `repeat(auto-fit, minmax(160px, 1fr))`, and remove the inline style |
| 2 | Hero console inner stat grid inline-fixed to 4 columns | `HeroConsole.tsx:38` | CSS class + media query (2 → 1 columns) |
| 3 | Header `Dashboard` and `Forecast` both link to `/dashboard` and **both highlight as active** | `SiteNav.tsx:6-7,20-21` | Point Forecast to `/dashboard/forecast`; fix `isActive` to exact/prefix correctly |
| 4 | Dead navigation links: `Approach`, `Research` → `href="#"` | `SiteNav.tsx:8-9` | Implement sections or remove |
| 5 | Footer uses `Link to="#modules"` (hash-only) | `SiteFooter.tsx:42-56` | Use `to="/#modules"` so cross-route hashes work |
| 6 | Social links are placeholders `href="#"` | `SiteFooter.tsx:18-35` | Real URLs or remove |
| 7 | Panel local state resets on module navigation (budget slider, table sort) | `InvestmentPanel.tsx:13`, `ForecastTable.tsx:20` | Lift to `DashboardProvider` or persist in URL/localStorage |
| 8 | Loading state is plain text, no skeleton | `ModulePage.tsx:15-21` | Add skeleton cells/chart placeholders |
| 9 | Duplicated "Run forecast" control on mobile (top bar + sidebar) | `DashboardLayout.tsx:54`, `Sidebar.tsx:101` | Keep one primary action |
| 10 | No empty/error retry action | `ModulePage.tsx:17-20` | Add a Retry button when `error` |
| 11 | `window.scrollTo` + `scroll-behavior: smooth` | `Shell.tsx:8`, `tokens.css:170` | Already uses `behavior:"auto"`; fine, but note interaction |
| 12 | `data-scroll-behavior="smooth"` is a non-standard attribute | `index.html:2` | Remove (CSS already sets smooth) |
| 13 | No 404 route | `main.tsx:38` | Add a proper `NotFound` page |

---

## 7. Correctness & data layer

| # | Issue | Location | Impact | Fix |
|---|---|---|---|---|
| 1 | Mock is **not deterministic** despite the comment "deterministic mock data" | `api/mock.ts:11-20, 194` (`Math.random()`) | Data changes every run; harder to demo/QA | Seed from request + fixed base, or `crypto`-free stable seed |
| 2 | Two **conflicting demand curves** | `api/mock.ts:50` (38–58) vs `lib/derive/util.ts:26` (52–95) | Same site yields inconsistent demand across features | Single source of truth in `lib/derive` |
| 3 | **Duplicated `hourLabel`** | `components/charts/ForecastBandChart.tsx:9` and `lib/derive/util.ts:29` | Drift risk | Re-export from `lib/derive` |
| 4 | No request cancellation/timeout/retry | `hooks/useDashboard.ts:64-71`, `api/client.ts:18-36` | Stale responses, infinite hangs | `AbortController` + timeout + optional retry |
| 5 | Raw server body surfaced in errors | `api/client.ts:25` | Can leak internals; ugly UI | Map to friendly messages, log detail |
| 6 | `USE_MOCK` hardcoded `true` | `config.ts:2` | Ships mock data; real path never exercised | Env-driven: `import.meta.env.VITE_USE_MOCK ?? import.meta.env.DEV` |
| 7 | Deviation between advertised p10/p50/p90 sums and derived balance uses p50 only | `DecisionCallout.tsx:17-20`, `balance.ts:75` | Fine, but “80 % band” messaging must stay consistent | Document; keep p50 for dispatch |
| 8 | `verify.ts` scenario invariants never run (default `scenarios = []`) | `useDashboard.ts:143-147` | Allocation-sum checks dead | Pass `investmentScenarios(...)` or drop the branch |
| 9 | `toRequest` injects `capacity_mw`/`tech` into a site request that the schema doesn’t define | `ControlsPanel.tsx:18-34` | Mock ignores; real API may 422 | Build payloads per mode strictly |
| 10 | React 19 StrictMode double-invokes `listSites` in dev | `useDashboard.ts:92-104` | Extra calls only in dev | Acceptable; guard if noisy |
| 11 | Charts recompute path strings each render | `ForecastBandChart.tsx:60-65`, `BalanceChart.tsx:34-44` | Minor CPU | `useMemo` on paths |
| 12 | Race between `booted` ref and fast remounts | `useDashboard.ts:107-113` | Low | Could key the boot off a stable flag |

---

## 8. Architecture & maintainability

**Strengths:** clear folder split (`api`, `components`, `hooks`, `lib/derive`, `pages`); derive layer is pure and well-typed; `DashboardProvider` correctly keeps the run alive across routes (`useDashboardContext.tsx:12-15`); aliasing `@/` is consistent.

**Issues**

1. **Hook imports from a component** — `useDashboard.ts:5` imports `toJson`, `toRequest`, `DashboardForm` from `components/dashboard/ControlsPanel.tsx`. This couples data orchestration to presentational code and creates a risky cycle.
   **Fix:** move the form model + serializers to `src/lib/dashboardForm.ts`.
2. **Dead exports / components**
   - `NavPill` — `components/SiteNav.tsx:67` (never rendered)
   - `formatMw` — `lib/format.ts:8`
   - `SquareIconButton` — `components/ui/SquareIconButton.tsx`
   - `ArrowUpRightIcon`, `Logo`, `CtaPill` — `components/ui.tsx:24,34,43`
   - `SiteTechnology` — `types.ts:58`
   - `MOCK_SITES` exported but only used internally (`api/mock.ts:34`)
3. **Two competing reveal systems** — `useScrollBehaviour` (`Shell.tsx:18`) selects all `.reveal` and toggles `.in`, while the `Reveal` component (`Reveal.tsx`) independently observes the same elements. Pick one.
4. **Inline styles** — 40 `style={{…}}` across 12 files (`HeroConsole.tsx` 13, `Landing.tsx` 8). Move to classes for consistency and maintainability.
5. **Magic numbers in derive models** (e.g. `reliability.ts:103` `* 0.08`, `capacity.ts:37` `* 24 * 2`, `investment.ts:28-35`). Extract to named constants/config so they are tunable and testable.
6. **No error boundary** — any render throw blanks the SPA. Add a top-level `ErrorBoundary` + a dashboard-level one.
7. **Naming collision** — `MODULES` exists in both `Landing.tsx:38` and `pages/dashboard/modules.tsx` (acceptable, but be aware).
8. **`@source not "../../Refrence"`** references a folder that does not exist (`tokens.css:8`). Remove.

---

## 9. CSS & design system

- **Total CSS: 3,179 lines** (`global.css` 2,089, `dashboard.css` 949, `tokens.css` 228). Good token foundation; the design language is genuinely consistent.
- **Dead CSS is significant.** These classes have **zero** TSX references and appear to be legacy from a previous landing iteration:
  `.marquee*`, `.feature-row*`, `.ticklist*`, `.linkarrow*`, `.page-hero*`, `.mstripe`, `.divider`, `.dash-main`, `.balance-grid`, `.bal-2`, `.itable__head/row`, `.appwin__screen*`, `.code-card__body`, `.chip--green/amber/red`, `.pill--bad`, `.btn--sm`, and the `--c-coral*` legacy aliases (`tokens.css:119-122`).
  **Fix:** run a purge (e.g. PurgeCSS / manual) against built HTML, or delete by section. Expect a meaningful reduction of the 64 kB CSS bundle.
- **`!important` usage:** 8 occurrences in `global.css` — mostly inside the reduced-motion block (acceptable) but audit the rest.
- **Breakpoints are ad-hoc** (`420, 520, 560, 640, 680, 720, 760, 820, 860, 900, 980, 1000, 1080`). Consolidate to a small set (e.g. 640 / 860 / 1080) via tokens.
- **No print styles**, no high-contrast/forced-colors support.
- **Inline CSS custom properties** for dynamic values (`--seg-n`, `--seg-i`, `--cells-n`) are a good pattern — keep.

---

## 10. SEO & metadata

`index.html` currently has only `<title>` and `<meta name="description">`.

Missing:
- Open Graph (`og:title`, `og:description`, `og:image`, `og:type`, `og:url`)
- Twitter/X card
- `<link rel="canonical">`
- `theme-color` / `color-scheme: dark`
- `robots.txt`, `sitemap.xml`
- JSON-LD (Organization/SoftwareApplication)
- Preload of critical fonts (see §4)
- `<meta name="apple-mobile-web-app-*">` / PWA manifest (optional)

Since this is a client-rendered SPA, also consider prerendering the landing page (`vite-plugin-prerender` / SSG) for crawlers and faster FCP.

---

## 11. Tooling, testing, DX

| Item | Status | Recommendation |
|---|---|---|
| Type check | ✅ `tsc -b --noEmit` passes | Keep; run in CI |
| Build | ✅ passes | Keep |
| ESLint | ❌ no config/script (one inline disable at `useDashboard.ts:112`) | Add `eslint` + `typescript-eslint` + `eslint-plugin-react-hooks`, `npm run lint` |
| Prettier | ❌ | Add for consistent formatting |
| Tests | ❌ none | Add Vitest + Testing Library; unit-test `lib/derive/*` (pure, high value) and an integration test for a forecast run |
| CI | ❌ none visible | GitHub Actions: install → typecheck → lint → test → build |
| Env handling | Partial (`VITE_API_BASE_URL`) | Add `.env.example`, validate env at startup |
| Git hooks | None | Add `husky` + `lint-staged` |
| Agent docs | None | Add `AGENTS.md` documenting lint/test/build commands |

Suggested `package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -b --noEmit",
    "lint": "eslint . --max-warnings 0",
    "format": "prettier --write .",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

---

## 12. Security & configuration

- **No secrets in the repo** — good. `VITE_API_BASE_URL` defaults to `http://localhost:8000` (`config.ts:3`).
- **HTTP default** — if the API is ever served over HTTPS, mixed-content will block it. Ensure the env var is HTTPS in production.
- **Error messages** include raw server response text (`client.ts:25`) — sanitize before showing.
- **No CSP / security headers** — configure on the static host (Netlify `_headers`, Vercel `vercel.json`, etc.): `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.
- **No auth / rate limiting** — expected for a hackathon frontend, but note the `/forecast` endpoint is open.
- **Social/footer links are `#`** — replace or remove to avoid dead/unsafe navigation.

---

## 13. Prioritized roadmap

### P0 — do now (high impact, low/medium effort)

1. Lazy-load dashboard routes/modules + `manualChunks` (§3.1).
2. Delete unused images/fonts; convert `suse-var.ttf`/`josefin-sans-var.ttf` to woff2 + preload (§3.2, §3.3, §4).
3. Add global `:focus-visible` styles (§3.5, §5).
4. Make `ForecastTable` headers real buttons with keyboard support (§3.4, §5).
5. Abort stale forecast requests (§3.6, §7).
6. Fix `.grid--7` responsive collapse and hero-console inline grids (§6).
7. Drive `USE_MOCK` from env (§7).

### P1 — next (correctness, UX, hygiene)

8. Single source of truth for demand curve + `hourLabel` (§7).
9. Deterministic mock seed (§7).
10. Fix header active-link bug and dead links; implement real footer anchors (§6).
11. Remove dead components/exports and dead CSS; remove Tailwind or adopt it (§4, §8, §9).
12. Add `ErrorBoundary` + skeleton loaders + retry UI (§6, §8).
13. Add SEO/OG/Twitter/canonical/theme-color + prerender landing (§10).
14. Reduce font families; drop unused `Inter` (§4).
15. Add ESLint + Prettier + Vitest, and a CI workflow (§11).

### P2 — polish (nice-to-have)

16. Lift panel state into context/URL (budget, sort) (§6).
17. Implement ARIA arrow-key nav for the sidebar switcher menu, or simplify roles (§5).
18. Keyboard-accessible chart exploration or rely on the forecast table (§5).
19. Consolidate breakpoints; add print/forced-colors styles (§9).
20. Add 404 page, PWA manifest, security headers (§6, §10, §12).
21. Memoize chart paths; cache `Intl` formatters (§4, §7).

---

## 14. Quick-wins checklist

- [ ] Delete `public/images/hero-robot.png`, `hand-left.png`, `hand-right.png`
- [ ] Delete unused `public/fonts/{pilcrow,ranade,dmmono}-*`
- [ ] Convert `suse-var.ttf`, `josefin-sans-var.ttf` → `.woff2` and preload
- [ ] Remove `Inter` from the Google Fonts URL in `index.html`
- [ ] Remove `data-scroll-behavior` from `<html>`
- [ ] Remove `@source not "../../Refrence"` from `tokens.css`
- [ ] Add `:focus-visible` ring globally
- [ ] Wrap `ForecastTable` `<th>` contents in `<button>`
- [ ] Point header "Forecast" link to `/dashboard/forecast`; remove/implement "Approach"/"Research"
- [ ] Change footer `to="#..."` → `to="/#..."`
- [ ] Delete `NavPill`, `formatMw`, `SquareIconButton`, `ArrowUpRightIcon`, `Logo`, `CtaPill`, `SiteTechnology`
- [ ] Remove unused `MOCK_SITES` export if external use is not planned
- [ ] `React.lazy` the dashboard and add `manualChunks`
- [ ] Add `AbortController` to `runWith`
- [ ] Replace `.grid--7` inline style with a real responsive class
- [ ] Add `.env.example` with `VITE_USE_MOCK` / `VITE_API_BASE_URL`
- [ ] Add `AGENTS.md` with lint/test/build commands

---

## 15. Appendix — build output & file inventory

### Production build (from `vite build`)

```
dist/index.html                 1.14 kB │ gzip:   0.61 kB
dist/assets/index-*.css        64.24 kB │ gzip:  13.04 kB
dist/assets/index-*.js        342.52 kB │ gzip: 107.01 kB
✓ built in ~4.3s · 1,635 modules · single JS chunk
```

### Largest shipped assets

| Size | Asset | Referenced? |
|---:|---|---|
| 930,347 B | `images/hero-robot.png` | ❌ |
| 724,938 B | `images/hand-right.png` | ❌ |
| 586,735 B | `images/hand-left.png` | ❌ |
| 342,515 B | `assets/index-*.js` | ✅ |
| 220,056 B | `fonts/suse-var.ttf` | ✅ (raw TTF) |
| 117,720 B | `fonts/josefin-sans-var.ttf` | ✅ (raw TTF) |
| ~24 kB each | `fonts/pilcrow-*` (×4) | ❌ |
| ~20 kB each | `fonts/ranade-*` (×2), `fonts/dmmono-*` (×3) | ❌ |

### Landmark source files

| Concern | File(s) |
|---|---|
| Entry / routing | `src/main.tsx` |
| Config / env | `src/config.ts`, `src/vite-env.d.ts` |
| Data client + mock | `src/api/client.ts`, `src/api/mock.ts` |
| Orchestration | `src/hooks/useDashboard.ts`, `useDashboardContext.tsx` |
| Pure models | `src/lib/derive/*.ts` |
| Landing | `src/pages/Landing.tsx`, `components/SiteNav.tsx`, `SiteFooter.tsx`, `HeroConsole.tsx`, `CtaBand.tsx`, `Reveal.tsx` |
| Dashboard shell | `src/pages/dashboard/DashboardLayout.tsx`, `Sidebar.tsx`, `ControlsDrawer.tsx`, `modules.tsx`, `ModulePage.tsx` |
| Panels/charts | `src/components/dashboard/*.tsx`, `src/components/charts/*.tsx` |
| Styles | `src/styles/tokens.css`, `global.css`, `dashboard.css` |

---

### Closing note

Fix the **P0** list first — items 1–7 deliver the largest user-visible gains (speed, keyboard access, mobile layout, correctness) for relatively little effort. After that, the **P1** work removes the technical debt (dead code/CSS, duplicated logic, missing SEO/tooling) that will otherwise compound as the product grows.

---

## 16. Remediation log (applied)

The following items from this report were implemented. Verified with `npm run ci` (typecheck + lint + 12 unit tests + production build) — all green.

### P0 — completed

- **Code splitting** — `src/main.tsx` now lazy-loads `Landing`, `DashboardLayout`, every module page and a new `NotFound`. `vite.config.ts` sets `manualChunks` (react / router / icons / vendor) and a `base` env. Dashboard shell uses a nested `<Suspense>` so only the content area shows a fallback while a module chunk loads. Build went from **1 chunk (342 kB)** to per-route chunks (landing ≈ 21 kB, each module 1–9 kB).
- **Unused assets removed** — deleted `public/images/{hero-robot,hand-left,hand-right}.png` (~2.2 MB) and unused `pilcrow-*`, `ranade-*`, `dmmono-*` fonts (~280 KB).
- **Focus visibility** — added a global `:focus-visible` ring in `global.css`.
- **Keyboard-sortable table** — `ForecastTable` headers are now real `<button>`s with `scope="col"` and `aria-sort`.
- **Request cancellation** — `api/client.ts` gained an abortable, 15 s time-boxed `fetchJson`; `useDashboard` cancels the previous run and on unmount; mock honours the signal. `isAbortError` prevents aborted runs from setting error state.
- **Responsive grids** — defined `.grid--7` with breakpoints and removed the inline 7-column style; moved `HeroConsole` inline styles to `.appwin__*` classes with 640 px rules.
- **Env-driven config** — `USE_MOCK` now reads `VITE_USE_MOCK`; added `.env.example` and typed `vite-env.d.ts`.

### P1 — completed

- **Single source of truth** — one `DEMAND_CURVE` (in `lib/derive/util.ts`); removed the duplicate mock curve and dead `demandSeries`; `ForecastBandChart` reuses the shared `hourLabel`.
- **Deterministic mock** — seed derived from the request via `hash01` (was `Math.random()`), plus simulated latency that respects abort.
- **Navigation fixes** — header "Forecast" → `/dashboard/forecast`, dead `#` links replaced with real `/#…` anchors, exact-match active state + `aria-current`; footer anchors made route-absolute; `ScrollToTop` now handles in-page hashes.
- **Resilience** — added `ErrorBoundary`, a `NotFound` 404 page, module skeleton loaders and a Retry action.
- **SEO/metadata** — added `robots`, `theme-color`, `color-scheme`, Open Graph and Twitter tags; removed the unused `Inter` Google font; preloaded self-hosted fonts.
- **Dead code removed** — deleted `SquareIconButton.tsx`; removed `NavPill`, `ArrowUpRightIcon`, `Logo`, `CtaPill`, `formatMw`, `SiteTechnology`, `DemandHour`, `MOCK_SITES` export; removed unused legacy CSS (`marquee`, `feature-row`, `ticklist`, `linkarrow`, `page-hero`, `mstripe`, `divider`, `dash-main`, `itable`, `appwin__screen`, `code-card__body`, chip/pill variants); removed the stale `@source` directive.
- **Architecture** — moved `DashboardForm`/`toRequest`/`toJson` to `src/lib/dashboardForm.ts` so the hook no longer imports from a component.
- **Tooling** — added ESLint (flat config), Prettier, Vitest (12 passing derive tests), CI workflow (`.github/workflows/ci.yml`), new scripts (`lint`, `format`, `test`, `ci`) and `AGENTS.md`.

### Remaining (P2)

Panel local state still resets on module navigation; ARIA arrow-key nav for the sidebar menu; chart keyboard exploration; breakpoint consolidation; PWA manifest; security headers; Tailwind retained intentionally as the CSS reset.

---

## 17. Landing motion pass (applied)

A reduced-motion-safe motion layer was added across the landing page (`global.css` "Landing motion system", `src/lib/style.ts`, `src/components/ScrollProgress.tsx`):

- **Scroll progress** — `ScrollProgress` bar pinned to the top, scaleX updated via rAF (no re-renders).
- **Nav** — entrance `navDrop` + a `.nav--scrolled` state that tightens the pill and strengthens its shadow after 24 px.
- **Hero** — slow `glowDrift` on `.hero__glow`; animated accent underline on "what to do".
- **Spec strip** — two cells stagger in; the gradient numerals shimmer via `gradientShift`.
- **Hero console** — bars grow with a per-bar stagger (`--i`), stat cards rise, status pills cascade; the console reveals on scroll instead of animating on mount.
- **Stagger system** — `.reveal--stagger` lets containers keep their scroll reveal while children rise in sequence (principle chain, pipeline, horizons, questions, modules, runway). Accent bars draw in, arrows flow, runway dots pulse, vertical rules scale in.
- **Cards** — diagonal hover sheen (`.card::after`) + heading lift.
- **Footer** — `reveal` on the top/bottom rows.

All of the above is disabled or reduced under `prefers-reduced-motion: reduce`, and the full CI (`typecheck`, `lint`, `test`, `build`) passes.
