# Plan — hero nav + Vunai console fidelity

Two pieces of work:

1. **Hero nav** — put the non-dashboard nav links inside the cinematic hero base
   itself (Image 1), since the site navbar only drops in after the hero ends.
2. **Console fidelity** — rebuild the dashboard shell to the Vunai `appwin`
   reference (Image 2): mac window chrome, app sidebar, a live KPI strip, a
   reactive horizon timeline, and status chips.

Sources: `Refrence/refrence elements/Vunai/public/css/devices.css`
(`.appwin`, `.macbar` L976–1001, `.appwin__*` L798–941, `.metric` L784–786,
`.chip` L675), `src/app/services/services-console.tsx` (console structure),
`src/components/site-chrome.tsx`. Our `tokens.css` is already ported from this
reference, so the palette/type/radii line up.

---

## Part 1 — hero nav

Current hero: `Landing.tsx` renders `.cine__ui` with `.cine__mark`
("re-forecast") top-left and `.cine__foot` (note + "Open Dashboard") bottom.
The site navbar (`SiteHeader`) is hidden until the hero scrolls past
(`navHidden`), so the hero is the only nav surface at the top.

Change:
- Wrap the mark in a `.cine__top` row and add `.cine__nav` with the three
  non-dashboard links, reusing `NAV_LINKS` labels:
  - **Forecast** → `/dashboard/forecast`
  - **Approach** → `#manifesto` (core principle)
  - **Research** → `#modules` (seven modules)
- Style: mono, uppercase, tracked, white at 78% → 100% on hover, matching the
  hero's existing `.cine__note` voice. `pointer-events: auto` (the hero UI layer
  is `pointer-events: none`). `focus-visible` uses the existing amber outline.
- Mobile: the row stays on one line and wraps under the mark only if needed.

## Part 2 — console shell

### 2.1 Chrome (port of Vunai `appwin`)

New `src/styles/console.css` ports, with the original values:

| Reference | Use |
|---|---|
| `.appwin` | rounded 16px frame, `#0f0f12`, hairline border, deep shadow, grid `rows auto 1fr / cols 208px 1fr` |
| `.macbar` + `.macbar__lights` | full-width title bar; triangular red/yellow/green lights; centred title |
| `.macbar__fav` | spark glyph before the title |
| `.appwin__side` | `#0b0b0d` sidebar, right hairline |
| `.appwin__brand` `.mk` `.cv` | "console" + gradient square + chevron |
| `.appwin__grp` / `.appwin__nav a` `.on` `.em` | MODULES label + icon nav |
| `.appwin__bar` | body top bar: module title (left), metadata (right) |
| `.metric` | rounded KPI cards (`12px`, `bg-elevated`) |
| `.chip` / `.pill--ok/warn/bad` | rounded chips + dot-status |
| `svg.ic` | 15–16px stroke icons, muted → white when active |

Layout: the appwin becomes the dashboard viewport (inset with a small margin on
desktop, full-bleed on mobile). Old `.shell*` / `.sidebar*` CSS in
`dashboard.css` is removed once the new classes take over.

### 2.2 Shell restructure

`DashboardLayout.tsx`:
```
.appwin
  .macbar            lights · spark · "re-forecast — {h} h forecast · {site}"
  .appwin__body-wrap (grid: side + body)
    Sidebar          .appwin__side
    .appwin__body
      .appwin__bar   {module bar title}      {model_version · p10/p50/p90}
      ConsoleSummary live KPI strip (persistent)
      main           .appwin__content > <Outlet/>
```
Mobile: the sidebar stays off-canvas; the hamburger and run button move into the
macbar (right side) instead of the old `.shell__bar`.

`ModulePage` drops the inner §-header (the appwin bar is now the page header);
the § number stays visible in the sidebar nav.

### 2.3 Live console summary (`ConsoleSummary.tsx`)

Rendered once above `<Outlet/>`, from `useDashboardContext()` so it updates on
every run / site switch:

- **Metric cards** (`.metric`, 4-up): Capacity `result.capacity_mw` MW ·
  Horizon `result.points.length` h · p50 median `mean(p50_mw)` MW · 80 % band
  `min(p10)–max(p90)` MW.
- **Horizon timeline**: dashed rail with a tick every 6 h (`now`, `+6h`, …,
  `+{h}h`); an animated "now" pulse; surplus/shortage windows drawn as coloured
  segments on the rail. Hover/focus a tick reads out that hour's p50 and
  p10–p90 band — this is the reactive part.
- **Status chips**: `Surplus {start}–{end} · charge storage` (green),
  `Shortage {start}–{end} · hold backup` (amber), reliability
  `{band} · ≈{expectedLossMwh} MWh at risk` (`.pill`, dot colour by tone).
  Windows come from the contiguous run in `balance.hours` around
  `worstSurplus` / `worstShortage`.

All numbers come from the existing derived layer; nothing new is modelled.

### 2.4 Motion & accessibility

- "now" pulse and chip dots animate; all gated by
  `@media (prefers-reduced-motion: reduce)`.
- Timeline ticks are real buttons with `aria-label`s; the readout is
  `aria-live="polite"`.
- Sidebar `NavLink` keeps `aria-current`; macbar lights are decorative.

## 3. Files

New: `src/styles/console.css`, `src/pages/dashboard/ConsoleSummary.tsx`.
Changed: `DashboardLayout.tsx`, `Sidebar.tsx`, `ModulePage.tsx`, `modules.tsx`
(bar-title), `main.tsx` (import), `dashboard.css` (drop old shell CSS),
`Landing.tsx` + `cinematic.css` (hero nav).
Untouched: every panel, the derive layer, `Refrence/`.

## 4. Verification

- `typecheck`, `build`, `test`.
- Playwright: 7 modules route; macbar title reflects the run; metrics equal the
  forecast (capacity/horizon/band); chips appear for surplus/shortage/reliability;
  timeline ticks focusable and update the readout; sidebar active state;
  drawer; mobile off-canvas; no console errors; no horizontal overflow.
