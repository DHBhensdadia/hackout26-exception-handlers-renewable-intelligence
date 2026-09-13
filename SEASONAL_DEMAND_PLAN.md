# Plan — rebuild Seasonal (05) and Demand (06)

Source of truth: `Refrence/model-outputs-and-visualisation.md` (current revision,
374 lines), with `renewable_energy_intelligence_platform_project_spec.md` §9 (Module 3),
§12 (Module 6), §16 (decision-first dashboard), §18 (USP) and the Vunai reference at
`Refrence/refrence elements/Vunai`.

## 1. What the doc actually says

| Module | Verdict in doc | The one real thing to build |
|---|---|---|
| **05 Seasonal** | §3 "❌ **Fabricated** — derived from a site-id hash". Endpoint `GET /seasonal/{region}` **cut**. | §5.3: three years of AEMO history are on disk → *recurring surplus by month × hour* as a **heat grid** (months down, hours across), bridging "tomorrow's surplus" to "this recurs every summer, and here is the storage it would take to absorb it". |
| **06 Demand** | §3 "❌ **Fabricated** — a real model exists and is better than what is shown." `POST /demand` **not built**. | §4.2: demand drawn with the **same band grammar as generation, mirrored, in `--c-blue`**, on a shared time axis; §2.2 per-region accuracy with the **VIC1 caveat**. |

Current code confirms both are fabrications:
- `lib/derive/seasonal.ts` — `seasonalPattern()` uses `hash01(site_id + ":season")` and fixed
  monthly shapes. 12 bars, no hour-of-day dimension.
- `lib/derive/capacity.ts` → `CapacityPanel` — demand comes from
  `demandForSite()` in `lib/derive/balance.ts`, which is `DEMAND_CURVE` (a hardcoded 24-value
  shape) × `hash01(site_id + ":demand")`.
- `DEMAND_CURVE` in `lib/derive/util.ts` is the single largest shown-vs-exists gap.

## 2. Constraints (doc §1, treated as binding)

- Near-black canvas, mono chrome, one indigo accent; **colour is data only** (green/blue/amber/red).
- Hairlines + ruled grids; new panels use `CellGrid`, not bespoke boxes.
- **Hand-rolled SVG in measured pixel coords** (`useMeasure`); no chart library.
- Mono + `font-variant-numeric: tabular-nums` for every figure.
- **Decision-first** (§16): lead with the call, number second.
- **Uncertainty is the product**: always draw `p10–p90`, median is a line through it.
- **Never sum per-site p10 for a region** (doc §4.4 prohibition) — regional bands come from the
  regional model / ensemble, never a quantile sum.

## 3. Architecture (the deep part)

Neither endpoint exists, so the boundary must be *contract-first*: the UI is written against
the shapes the backend will serve, and the only stand-in is the same `USE_MOCK` switch the
`/forecast` path already uses.

### 3.1 Data layer

Add to `src/types.ts` (names mirror `docs/api-contract.md`, the doc's cited contract):

```ts
// GET /regions
export interface RegionRecord {
  region_id: string;          // "SA1" | "NSW1" | "VIC1" | "QLD1" | "TAS1"
  name: string;
  nmae_pct: number;           // QLD1 1.84 … VIC1 4.33
  coverage_pct: number;       // 80.2 … 66.9 (VIC1)
  balance_available: boolean;
  caveat?: string;            // VIC1 seasonal bias
}

// POST /demand   (not built server-side yet)
export interface DemandRequest { region_id: string; horizon_h?: number; }
export interface DemandPoint { valid_time_utc: string; horizon_h: number; p10_mw: number; p50_mw: number; p90_mw: number; }
export interface DemandResponse {
  region_id: string; data_mode: "replay" | "live"; model_version: string;
  nmae_pct: number; coverage_pct: number; points: DemandPoint[];
}

// GET /seasonal/{region}   (cut) — cells keyed by month×hour
export interface SeasonalCell { month: number; hour: number; residual_mwh: number; surplus_pct: number; }
export interface SeasonalResponse {
  region_id: string; window_years: number; source: string;   // "AEMO 2021–2024"
  cells: SeasonalCell[]; storage_to_absorb_mwh: number;
}
```

`src/api/mock.ts`: `listRegions()`, `demand(req)`, `seasonal(req)` — deterministic, seeded by
region, using the doc's **measured metadata** (nMAE/coverage) for the confidence panel and a
physical diurnal/seasonal shape for the series. `src/api/client.ts`: `listRegions()`,
`demand()`, `seasonal()` with the same `USE_MOCK` switch; in real mode they call
`/regions`, `/demand`, `/seasonal/{id}` and **fall back to the derive model on 404** so the
panel degrades to a labelled `modelled` state instead of breaking.

### 3.2 Derive layer

- **`lib/derive/history.ts` (new)** — a deterministic 3-year hourly climatology per region
  (solar/wind shape + demand shape, seeded). This is the stand-in for the on-disk AEMO history,
  and it exists so Seasonal is a *real computation over a series*, not a hash.
- **`lib/derive/demand.ts` (new)** — regional demand band `p10/p50/p90` from the demand model,
  plus per-region confidence metadata and growth. `demandForSite()` stops reading `DEMAND_CURVE`
  and reads the demand band instead; `DEMAND_CURVE` is deleted from `util.ts`.
- **`lib/derive/seasonal.ts` (rewrite)** — `seasonalGrid(history)` → `cells[12×24]` of median
  residual and `surplus_pct` (share of the 3 years that hour/month pair was in surplus), plus
  `storageToAbsorb()` (size storage to shift each month's recurring surplus into its recurring
  deficit). Invariants unit-tested (grid is 12×24, residual sign matches state, storage ≥ 0).
- **`lib/derive/capacity.ts` (keep, re-fed)** — the long-term growth/gap model stays, but its
  base demand now comes from `demand.ts`, not the hashed curve.

### 3.3 Chart primitives

- **`components/charts/BandChart.tsx` (new)** — the band grammar extracted into one primitive:
  `useMeasure`, `niceMax`, p10/p90 area + p50 line, optional ghost line, optional reference rule,
  optional overlay series, hover readout. Demand uses it; `ForecastBandChart` is **left
  untouched** to protect the verified forecast module (migration noted as follow-up).
- **`components/dashboard/SeasonalHeatGrid.tsx` (new)** — a 12×24 CSS grid of cells on the
  `CellGrid` hairline rhythm, colour keyed to residual sign/magnitude, hover + keyboard readout.

## 4. Module 05 — Seasonal, design spec

Replace the 12-bar `SeasonalPanel` with:

```
§05 Seasonal                            modelled · AEMO 3-y climatology · mock
─────────────────────────────────────────────────────────────────────────────
Surplus recurs 12:00–16:00 through Mar–May — absorbing it needs ≈ 1,240 MWh.

       00 01 02 … 12 13 14 15 … 22 23          ← hour of day
  Jan  ░░ ░░ ░░   ▒▒ ▓▓ ▓▓ ▒▒        ░░
  Feb  ░░ ░░ ░░   ▒▒ ▓▓ ▓▓ ▒▒        ░░
  Mar  ░░ ░░ ░░   ▓▓ ▓▓ ▓▓ ▓▓   ░░
  …                                          ▓ surplus · ░ shortage · ┈ balanced
  Dec  ░░ ░░ ░░   ▒▒ ▒▒ ▒▒ ░░

  Peak window  Mar · 13:00    Recurring surplus  486 h/yr    Storage to absorb  1,240 MWh
```

- **Encoding**: one cell per month×hour; fill = data colour with alpha by |residual| —
  `--c-green` surplus, `--c-amber`/`--c-red` shortage, hairline only when balanced. Small
  squares on a 1px `--hairline` grid (the `CellGrid` rhythm), no rounded cards.
- **Lead sentence** (§16): strongest recurring window as a sentence, then the grid as evidence.
- **Bottom metrics** (`.metric`, Vunai): peak window, recurring surplus h/yr, **storage to
  absorb** — this is the spec §18 bridge.
- **Provenance**: `modelled · mock` tag; a note stating the endpoint is cut and what the real
  version reads (on-disk AEMO history). Honesty over invention (doc §3).
- **Responsive**: ≤860 the grid scrolls horizontally with sticky month labels; hours bucket to
  3-hour columns ≤640. Readout is `aria-live`.
- **A11y**: each cell is a focusable button with a full `aria-label` (month, hour, residual,
  surplus %); arrow-key roving optional.

## 5. Module 06 — Demand, design spec

Replace `CapacityPanel` in the Demand module with `DemandPanel`:

```
§06 Demand & capacity                   POST /demand · modelled · mock
─────────────────────────────────────────────────────────────────────────────
Demand peaks 18:00–20:00 at 4,180 MW — 1,610 MW below the dispatchable ceiling.

  MW ┤            ╭───╮        demand band (p10–p90, --c-blue)
     │        ╭───╯   ╰──╮      generation band (p10–p90, --accent) overlaid
     │   ╭───╯           ╰────
     │───┴──────────────────────────────── ─  shared 72 h axis, UTC
  ┌ region confidence ───────────────────────────────────────────────────────┐
  │ QLD1  nMAE 1.84 %  cov 80.2 %   NSW1  2.27 / 82.6   SA1  3.17 / 84.6      │
  │ TAS1  4.15 / 88.8   VIC1 4.33 / 66.9 ⚠ seasonal bias — not at parity      │
  └──────────────────────────────────────────────────────────────────────────┘
```

- **Band, mirrored** (§4.2): demand as a `--c-blue` p10–p90 band + p50 line, **on the same
  axis as the generation band** (`--accent`) so balance reads before any arithmetic. No third
  language.
- **Region confidence** (§2.2): ruled `.itable`-style table, mono, with a caveat marker on VIC1
  (66.9 % coverage) — a value-presenting panel that shows where it is weak.
- **Planning sub-section** (§12): the existing growth / capacity-gap / required-storage metrics,
  now fed by the demand model rather than the hash; keep decision wording.
- **Region / horizon control**: a `role="tablist"` or `Seg` control (reuse the reference's
  `.tabs__nav` / existing `Seg`) to switch region; state persists in the dashboard hook.
- **Provenance**: `modelled · mock` and the measured nMAE on the panel, plus a note that
  `POST /demand` is not built (doc Appendix).
- **Responsive**: band height clamps down; the region table collapses to stacked rows ≤640;
  y-axis tick count adapts to width (already the `BandChart` pattern).

## 6. Elements reused from the Vunai reference

| Element | From | Use |
|---|---|---|
| `.metric` cards | `devices.css` L784, L928 | headline numbers (Seasonal + Demand) |
| `.chip` / `.pill--ok/warn/bad` | L675, L839 | provenance + VIC1 caveat + surplus/shortage |
| `.itable__head/.itable__row` | L906–913 | region-confidence table |
| `.tabs__nav` | L259–266 | region switcher segmented control |
| `svg.ic` stroke icons | L945 | section markers |
| `.appwin` chrome + `.macbar` | L798–1001 | already the console shell |
| `.sp__ring/.sp__led` motif | L72–83 | optional "recurring pattern" accent on the headline |

No new colour, no new radius, no chart library — every addition fits the existing console.

## 7. Files

New:
- `src/lib/derive/history.ts`, `src/lib/derive/demand.ts`
- `src/components/charts/BandChart.tsx`
- `src/components/dashboard/SeasonalHeatGrid.tsx`, `src/components/dashboard/DemandPanel.tsx`

Changed:
- `src/types.ts` (region / demand / seasonal contracts)
- `src/api/mock.ts`, `src/api/client.ts` (regions + demand + seasonal, 404 fallback)
- `src/lib/derive/seasonal.ts` (rewrite), `capacity.ts` + `balance.ts` (re-fed), `util.ts` (drop `DEMAND_CURVE`)
- `src/hooks/useDashboard.ts` (derived: regions, demand, seasonal-grid), `useDashboardContext` shape
- `src/components/dashboard/SeasonalPanel.tsx`, `DemandModule.tsx`, `SeasonalModule.tsx`
- `src/styles/dashboard.css` / `console.css` (heat grid, region table, band overlay)
- `src/lib/derive/derive.test.ts` (new invariants)

Removed: the hashed `seasonalPattern` and the `DEMAND_CURVE` synthetic demand path.

## 8. Verification

- Unit: demand band `p10 ≤ p50 ≤ p90`; seasonal grid is exactly 12×24; `surplus_pct ∈ [0,1]`;
  residual sign matches state; `storage_to_absorb_mwh ≥ 0`; deterministic per region.
- Playwright: 288 heat cells render with correct row/col labels; hover/focus readout updates;
  demand band + generation overlay share an x-axis; region table shows all five regions with the
  VIC1 caveat; provenance tags present; responsive at 1440/1100/860/640/430 with no horizontal
  overflow; dashboard suite (20 checks) stays green.
- `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`.

## 9. Phasing

1. Contracts + mock + client (types, regions, demand, seasonal, 404 fallback).
2. Derive: history → demand → seasonal grid + storage; unit tests.
3. `BandChart` primitive; `DemandPanel` (band + overlay + region table + planning).
4. `SeasonalHeatGrid` + rewritten `SeasonalPanel`.
5. Provenance/empty states, responsive, a11y; full verification.

## 10. Out of scope (explicit)

- Reliability (04) — the doc rates it the highest risk (hashed risk scores), but you scoped this
  task to Seasonal and Demand. Flagged for the next pass.
- Clear-sky ghost line / lead-day markers (Forecast, §4.1), actual overlay + reliability diagram
  (Balance, §4.4/§5.2), aggregation comparison (§5.1), storage dispatch + VSS (§4.6/§4.7).
- `ForecastBandChart` is deliberately left untouched; the new `BandChart` is additive and a
  follow-up can migrate Forecast once the demand path is proven.
