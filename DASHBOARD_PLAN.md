# Dashboard Implementation Plan — Decision Console

Status: **PROPOSAL — for review**
Scope: `src/pages/Dashboard.tsx` and the components/data it composes.
Sources of truth: `Refrence/renewable_energy_intelligence_platform_project_spec.md`, `Refrence/input_output.md`,
`Refrence/refrence elements/Vunai` (design system), and the local `HC` build (reference implementation).

> The `Refrence/` folder is read-only research material. Nothing from it is copied verbatim into the repo,
> and it stays untracked.

---

## 1. What the reference material actually asks for

### 1.1 From the project spec (§16) — five views, not five tabs of raw data

| View | Required content |
|---|---|
| Operations | 24–72 h solar + wind forecast · total renewable · demand forecast · surplus/shortage periods · recommended actions · storage status |
| Reliability | equipment risk · failure-prone conditions · maintenance alerts · historical failure patterns · expected generation loss |
| Planning | future demand · regional growth · required capacity · storage requirement · capacity gap |
| Investment | solar vs wind · storage requirements · ROI/financials · recommended locations · scenarios · budget allocation |
| Decision | key alerts · priority recommendations · what-if comparison · short-term actions · long-term plan |

Spec §16 is explicit: **"The final dashboard should be organized around decisions rather than raw data."**
That is the single most important architecture constraint in the plan.

### 1.2 From `input_output.md` — the exact contract and its decision mapping

Six models = 2 technologies × 3 quantiles. Each output field maps to a decision:

| Field | Meaning | Consumed by |
|---|---|---|
| `p10_mw` | pessimistic; truth above it ~90% of the time | shortage risk, backup scheduling |
| `p50_mw` | median forecast | expected generation |
| `p90_mw` | optimistic; truth below it ~90% of the time | surplus risk, storage sizing |
| `clearsky_mw` | cloudless-sky ceiling | forecast vs potential, curtailment context |
| `physics_mw` | pure physics estimate (no ML) | audit trail — what the correction added |
| envelope (`issue_time_utc`, `model_version`, `weather_source`, `location_is_estimated`) | provenance | integrity strip |

Guarantees to surface: always `p10 ≤ p50 ≤ p90`; values in `[0, capacity_mw]`; solar exactly 0 at night; 80% conformal calibration.

### 1.3 From the spec — constraints that shape copy and UI

- §26: never present prediction as guarantee. Uncertainty ranges, scenarios, risk scoring — not promises.
- §10: "risk estimates and preventive recommendations, not claims of perfect failure prediction."
- §11 & §21: investment output is a **scenario comparison**, not a financial forecast.
- §14: storage is a first-class variable (SoC, charge/discharge, required capacity).

### 1.4 Reality check on the live API

The real backend exposes `POST /forecast`, `GET /sites`, `GET /health`. Everything else (demand, storage,
reliability, seasonal, investment) is **derived client-side** from the forecast + registry, deterministically,
and is labelled as modelled/scenario. This is honest and matches §25: *the forecast is the intelligence
layer; every other view consumes it.*

---

## 2. Problems with the current dashboard

| # | Problem | Evidence |
|---|---|---|
| 1 | Content is hidden behind tabs → violates "decision-first", hides the connected chain | `Dashboard.tsx` tabs |
| 2 | Duplicate "Run forecast" controls (header + panel) | header + `ControlsPanel` |
| 3 | Styling is inline-style soup; inconsistent radii/shadows read as generic/AI cards | `BalanceModule`, `SitesTable`, `ForecastTable` |
| 4 | Rounded-rectangle card grid as the only layout language | every panel |
| 5 | Only 3 of the spec's 5 views exist; no reliability, planning, or investment surfaces | codebase |
| 6 | Forecast tables dump rows without prioritising the decision-relevant ones (deficits, peaks, worst hours) | `ForecastTable` |
| 7 | Duplicate `config` object (`src/config.ts` and `src/types.ts`) | both files |

---

## 3. Information architecture — one console, ruled sections

Replace tabs with a **single scrolling decision console**:

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│  RUN RAIL    │  §01  THE CALL                                               │
│  (sticky,    │  verdict · recommended action · priority alerts              │
│   ~320px)    ├───────────────────────────────────────────────────────────────┤
│              │  §02  FORECAST                                    24–72 h     │
│  site        │  band chart · p10/p50/p90 decision legend · period table    │
│  tech        ├───────────────────────────────────────────────────────────────┤
│  capacity    │  §03  BALANCE                                     + storage   │
│  horizon     │  generation vs demand vs headroom · windows · dispatch       │
│  storage     ├───────────────────────────────────────────────────────────────┤
│              │  §04  RELIABILITY                                   risk-only  │
│  [ Run ]     │  failure-prone conditions · expected loss · maintenance      │
│              ├───────────────────────────────────────────────────────────────┤
│  ── index ── │  §05  SEASONAL PATTERNS                                      │
│  §01 · §02 … │  recurring surplus / low-output / high-demand windows        │
│              ├───────────────────────────────────────────────────────────────┤
│  provenance  │  §06  DEMAND & CAPACITY                             planning  │
│  model/time  │  growth curve · capacity gap · required storage              │
│              ├───────────────────────────────────────────────────────────────┤
│              │  §07  INVESTMENT SCENARIOS                     ₹500 cr      │
│              │  A–E scenario comparison · budget allocation · risk          │
│              ├───────────────────────────────────────────────────────────────┤
│              │  §08  FLEET REGISTRY                    GET /sites            │
│              │  site rows → click to load into the rail                     │
│              ├───────────────────────────────────────────────────────────────┤
│              │  §09  INTEGRITY & LIMITATIONS                                │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

Rationale:
- **The call first.** A grid operator opens the dashboard to make a call; the verdict and recommended
  action must be the first thing read. Everything below is the evidence.
- **The chain is visible.** Forecast → balance → reliability → planning → investment reads as one
  connected story (spec §25), not isolated tabs.
- **The rail is both control and index.** It holds the run inputs (the re-architected `ControlsPanel`)
  and a numbered § index that scroll-spies. One run control, not two.
- **§ numbering is the navigation.** Mono `§01…§09` markers point to the section header system.

Phasing (so the page is never half-built):
- **Phase 1 (core):** §01, §02, §03, §08, §09 + rail.
- **Phase 2 (planning):** §04, §05, §06.
- **Phase 3 (strategy):** §07 + a what-if drawer.

---

## 4. Content inventory per section

Every value is labelled either **measured** (from `/forecast` / `/sites`), **derived** (deterministic
client model), or **scenario** (budget/what-if). Nothing is presented as a guarantee.

| § | Section | Fields shown | Source |
|---|---|---|---|
| 01 | The Call | verdict (surplus / shortage / balanced), recommended action, confidence, 2–3 priority alerts, worst deficit/surplus window | derived from §03 |
| 02 | Forecast | p10/p50/p90 band chart, clearsky + physics overlays, capacity cap, hover readout, period table (sortable but decision-sorted: deficits first), `issue_time_utc` | measured |
| 03 | Balance | generation vs demand overlay, storage headroom bar, surplus/shortage hours + energies, dispatch recommendations (charge / hold backup / curtail), p90-vs-p50 storage-sizing note | derived |
| 04 | Reliability | risk index (0–1), failure-prone conditions (wind: cut-out/gusts; solar: cell temp), expected generation loss (MW/h), maintenance window suggestions, "risk, not prediction" note | derived |
| 05 | Seasonal | recurring summer surplus, monsoon dips, high-demand seasons, low-output windows — 12-month pattern strip | derived (deterministic) |
| 06 | Demand & capacity | demand growth curve (5 yr), capacity gap (MW), required storage (MWh), regional tags | derived + spec §12 |
| 07 | Investment | scenarios A–E (100% solar · solar+storage · wind+storage · solar+wind · hybrid), CAPEX/ROI/payback/risk/capacity adequacy vs ₹500 cr, recommended allocation | scenario |
| 08 | Fleet registry | site id, name/region, tech, capacity, trained/unseen, load action | measured (`GET /sites`) |
| 09 | Integrity | envelope fields in mono, invariants (`p10≤p50≤p90`, clamped, solar 0 at night, conformal 80%), data-quality caveats | measured + spec §26 |

---

## 5. Data & state architecture

### 5.1 Layers

```
api/client.ts          forecast() · listSites()          (unchanged public surface)
   │
hooks/useDashboard.ts  one hook: { site, form, forecast, loading, error, run }
   │
lib/derive/*.ts        pure, deterministic, unit-testable:
   │                     balance.ts      generation vs demand vs headroom → verdict + actions
   │                     storage.ts      headroom, SoC, required MWh
   │                     reliability.ts  risk score + conditions + expected loss
   │                     seasonal.ts     12-month pattern from seeded determinism
   │                     capacity.ts     demand growth + capacity gap
   │                     investment.ts   scenarios A–E, budget allocation
   │
components (dumb)      render props only; no business logic in JSX
```

### 5.2 Rules

- All derived functions are **pure** and take `(forecast, site, options)`; a fixed seed keeps the demo stable
  per site while still looking live.
- Every derived panel renders a small `modelled` / `scenario` tag next to its § header (mono, muted).
- Keep the mock exact to the contract (`mock.ts` already satisfies the invariants). Extend `mock.ts` only for
  site metadata needed by derivation (e.g. storage capacity per site), never to break the `/forecast` shape.
- Consolidate `config`: keep `src/config.ts`, delete the duplicate in `src/types.ts` (and fix imports).

### 5.3 Invariants to assert (cheap runtime checks in dev)

- `p10 ≤ p50 ≤ p90`, values within `[0, capacity]`, solar `0` at night.
- `surplusHours + shortageHours === horizon`, energies `≥ 0`.
- Investment scenarios sum to the budget; capacity adequacy is a range, not a single promise.

---

## 6. Visual system — the anti-AI language

The reference (specifically the Sharplink-style FAQ grid in **Image 1** and its implementation in `HC`) does
**not** use floating rounded cards. It uses a **ruled grid**: dashed hairlines divide space into cells, and
content sits directly on the canvas.

### 6.1 Layout primitives to port

| Primitive | Reference | Use |
|---|---|---|
| `DashedLine` (vertical/horizontal, SVG pattern 2px dash / 2px gap) | `HC/src/components/ui/DashedLine.tsx` | column + section separators, full-height grid rules |
| 12-column grid (`--layout-columns-count`, `--layout-margin`, `--layout-gap`) | `HC/src/styles/layout.css`, `tokens.css` | page grid at ≥1200px; 4-col mobile |
| Numbered eyebrow chip (`§NN` in a small square, mono) | `HC` FAQ `.faq-item .header .eyebrow` | section headers, KPI indices |
| Square icon button (34×34, no radius, white glyph, rotates on toggle) | `HC` FAQ `.icon-wrapper` | expand/collapse, sort, load |
| `.itable` rows (grid columns, hairline row rules, hover = surface shift) | `Vunai/public/css/devices.css` | fleet table, period table |
| `.cvseg` segmented switch | `Vunai` console | rail controls (already in `ControlsPanel`) |
| `.cvwin` / `.appwin` window chrome + `cvlive` status | `Vunai` console | panel headers ("live" dot + title) |
| `.cvchart` / `.cockpit__tiles` (1px-gap cell grid on hairline background) | `Vunai` console | KPI cells, stat rows |

### 6.2 Rules (enforced in review)

1. **No rounded-rectangle soup.** Structural surfaces are ruled bands (top/bottom hairlines) or cell grids
   (1px gaps over `--hairline`). Radius is reserved: `0` for structure, `--r-sm` (6px) for inputs/buttons,
   pill only for status.
2. **Dashed rules are the primary separator.** Solid hairlines are secondary. This single choice is what
   makes the layout read as a designed grid instead of generated cards.
3. **One accent colour.** `--accent` for interactive/primary; status colours (`--c-green/amber/red/blue`)
   only inside data.
4. **Type roles are fixed.** Display/heading = Satoshi; prose = SUSE; every label, index, unit, timestamp =
   IBM Plex Mono. Never mix roles.
5. **Numbers:** tabular figures, right-aligned when comparing magnitudes; units in mono, smaller.
6. **Hover = background/underline shift**, never `translateY` + shadow.
7. **No gradients on chrome**, no glow, no glassmorphism, no emoji, no icon without meaning. Gradients only
   inside data marks (band fill, `--m-gradient` display text).
8. **Cell-grid KPIs** instead of cards: a row of cells separated by 1px hairlines, each with a mono label,
   display value, and a small delta/context line.
9. **Section header pattern:**
   `§03 — BALANCE · modelled` (mono kicker) over the section title, with a dashed rule underneath and an
   optional right-aligned meta (`+ storage`, `24–72 h`, `risk-only`).
10. **The reference grid is the page skeleton**: full-height dashed verticals at the rail edge and column
    boundaries, horizontal dashed rules between sections, so the page reads as one ruled system.

### 6.3 Before → after example

| Now | Plan |
|---|---|
| `.card` with radius 10 + shadow per metric | cell grid: 1px hairlines, no radius, no shadow |
| Surplus pills floating over panels | a "call" band: verdict + action + evidence counts, ruled |
| Tab bar hiding balance/reliability/planning | § index rail + scroll sections, all visible |
| Text-glyph legends (`━━ ┄ ∙∙`) | swatch legend (solid/dashed/dotted/band) |
| Sortable table of 72 equal rows | decision-sorted table: deficits, peaks, then the rest |

---

## 7. Component & file map

| Action | Path | Notes |
|---|---|---|
| new | `src/components/ui/DashedLine.tsx` | port from `HC` (SVG pattern) |
| new | `src/components/ui/CellGrid.tsx` | 1px-gap cell grid primitive |
| new | `src/components/ui/SquareIconButton.tsx` | 34×34 square button |
| new | `src/components/dashboard/RunRail.tsx` | controls + § index + provenance (replaces tabs) |
| new | `src/components/dashboard/Section.tsx` | `§NN` header + dashed rule + body |
| new | `src/components/dashboard/DecisionCallout.tsx` | §01 |
| new | `src/components/dashboard/KpiGrid.tsx` | replaces ad-hoc stat rows |
| new | `src/components/dashboard/ReliabilityPanel.tsx` | §04 |
| new | `src/components/dashboard/SeasonalPanel.tsx` | §05 |
| new | `src/components/dashboard/CapacityPanel.tsx` | §06 |
| new | `src/components/dashboard/InvestmentPanel.tsx` | §07 |
| new | `src/components/dashboard/ProvenanceFooter.tsx` | §09 |
| new | `src/lib/derive/*.ts` | pure derivation modules |
| new | `src/hooks/useDashboard.ts` | orchestration hook |
| rework | `src/components/dashboard/BalanceModule.tsx` | → `BalancePanel` on cell grid |
| rework | `src/components/dashboard/SitesTable.tsx` | → `.itable` fleet table |
| rework | `src/components/dashboard/ForecastTable.tsx` | decision-sorted, mono, sticky header |
| rework | `src/components/dashboard/RunSummary.tsx` | `StatsRow` → `KpiGrid` |
| keep | `ControlsPanel.tsx`, `ForecastPanel.tsx`, `ForecastBandChart.tsx` | already re-architected |
| thin | `src/pages/Dashboard.tsx` | composition only; remove tabs + duplicate run button |
| new css | `src/styles/dashboard.css` | ruled-band + cell-grid system; retire `.card` inside dashboard |
| fix | `src/config.ts` / `src/types.ts` | remove duplicate `config` export |

---

## 8. Milestones

| # | Milestone | Deliverable | Verify |
|---|---|---|---|
| 1 | Grid primitives | `DashedLine`, `CellGrid`, `SquareIconButton`, `Section`, layout tokens | primitives render on the dark theme; dashes align |
| 2 | Data layer | `derive/*` + `useDashboard` + types; remove duplicate config | `npm run typecheck`; invariant assertions pass in dev |
| 3 | Shell | `RunRail` (one run control + § index) + section stack; `Dashboard.tsx` composition | no tabs; all sections reachable; single run action |
| 4 | Core sections | §01 The Call · §02 Forecast · §03 Balance | decision-first reading order holds |
| 5 | Registry + integrity | §08 fleet (`.itable`) · §09 provenance/invariants | clicking a row loads it into the rail |
| 6 | Planning sections | §04 Reliability · §05 Seasonal · §06 Demand & capacity | modelled tags present; scenarios not promises |
| 7 | Strategy | §07 Investment A–E · what-if drawer | budget allocation sums correctly |
| 8 | Polish | responsive (390/768/1280/1920), keyboard + aria, reduced motion, build | `npm run build` clean; anti-AI checklist passes |

---

## 9. Definition of done

- `npm run typecheck` and `npm run build` pass; no unused exports.
- Every section is reachable without a tab and the call is above the fold.
- No floating rounded-rectangle cards on the dashboard; structural surfaces are ruled bands / cell grids.
- Every derived number carries a `modelled` or `scenario` tag; no guarantee language.
- Provenance strip shows `model_version`, `weather_source`, `issue_time_utc`, `location_is_estimated`.
- Responsive from 390 → 1920 without horizontal scroll; dashed grid stays aligned.
- Reference folder remains untracked; no reference content copied verbatim.

---

## 10. Non-goals / anti-patterns

- No new charting dependency — custom SVG primitives continue.
- No rainbow KPI tiles, no icon-per-metric decoration, no glassmorphism, no drop-shadow hover lift.
- No hiding content behind tabs to "simplify"; the chain is the point.
- No fake real-time; "live" is used only where a value actually refreshes.
- No committed `Refrence/` material.

---

## 11. Implementation status — verified

### 11.1 Verification run (automated)

| Check | Result |
|---|---|
| `npm run typecheck` | pass |
| `npm run build` | pass — 85 modules, CSS ≈ 62.7 KB, JS ≈ 335 KB |
| Derivation invariants — 8 sites × 6 models + cold start + budget sweep | pass: `p10 ≤ p50 ≤ p90`, values ∈ `[0, capacity]`, hours partition the horizon, energies ≥ 0, exactly one recommended scenario, deterministic per site, budget monotonicity |
| Browser smoke — Playwright at 1440 px and 390 px | pass: 9 sections in order, 1 run control, forecast + balance charts render, 4 cell grids, 12 seasonal months, 5 capacity years, 5 scenarios, 8 fleet rows, 72 table rows, 5 provenance fields, **0 console/page errors, 0 horizontal overflow** |
| Anchor navigation clears the fixed nav | `scroll-margin-top` on sections |

### 11.2 Delivered against the plan

- **Decision-first console** — §01 The Call is first; tabs removed; the chain is visible in one scroll.
- **Single run control** — only the rail's `Run forecast`; the duplicate header action is gone.
- **Ruled grid** — `DashedLine`, `CellGrid`, `Section`, square icon buttons; structural frames squared (`.console .panel2`, `.console .code-card` → `border-radius: 0`); no floating rounded cards inside the console.
- **Derived layer** — `lib/derive/{storage,balance,reliability,seasonal,capacity,investment,verify}.ts` + `useDashboard`.
- **Content coverage** — the spec §16 Operations, Reliability, Planning, Investment and Decision views are all present.
- **Honesty** — every derived section carries a `modelled` / `scenario` tag; reliability is risk-only; investment is scenario-only; the integrity footer lists invariants and limits.

### 11.3 Deliberate deviations

- The plan's "what-if drawer" is implemented as an inline budget slider in §07 so the scenarios stay visible while comparing.
- The period table keeps all 72 rows in a sticky-header scroll area instead of truncating, so no data is hidden.
- Mock fix: removed the all-night solar horizon quirk so a 72 h run always carries a real diurnal shape.

### 11.4 Boundaries

- Demand, storage, reliability, seasonal, capacity and investment are deterministic client models over `/forecast` + `/sites`. Each `derive/*` module is the single swap point when the backend grows endpoints.
- `config.USE_MOCK = false` targets the real `/forecast` + `/sites`; no other endpoints are assumed.
