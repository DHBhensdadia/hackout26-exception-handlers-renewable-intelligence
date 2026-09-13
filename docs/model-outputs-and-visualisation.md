# Model outputs, and how the dashboard should show them

**For the frontend team.** Written after Phase 2 replaced most of the modelling the current
dashboard was built against.

The dashboard was designed against a single-site forecast and an early model. That model has
been retrained, four new models sit behind it, and two of the seven modules now display
numbers the backend can compute properly but the UI is still inventing. This document says
what exists, what is stale, and how each output should be drawn — in the visual language the
site already has, not a new one.

Numbers quoted here are measured, from `artifacts/*_metadata.json` and `reports/*.json`. None
are illustrative.

---

## Contents

1. [The design ideology, as constraints](#1-the-design-ideology-as-constraints)
2. [What the models actually produce now](#2-what-the-models-actually-produce-now)
3. [Module-by-module: what is stale](#3-module-by-module-what-is-stale)
4. [How to draw each output](#4-how-to-draw-each-output)
5. [Three things the dashboard is missing entirely](#5-three-things-the-dashboard-is-missing-entirely)
6. [Priority order](#6-priority-order)

---

## 1. The design ideology, as constraints

Read from `tokens.css`, `AGENTS.md` and the existing components. These are not suggestions —
every proposal below obeys them.

| Rule | Why it matters here |
|---|---|
| **Near-black canvas, monochrome chrome, one indigo accent** (`--accent #5e6ad2`) | Chrome must never compete with data. Buttons, focus rings, active nav — indigo. Nothing else. |
| **Chromatic colour is reserved for data** — green, blue, purple, amber, red | So when a shortage goes red, red *means* something. Spending red on a decorative border spends the alarm. |
| **Hairline borders** (`--hairline #23252a`), ruled grids, generous space | The console reads as an instrument, not a card deck. New panels use `CellGrid`, not bespoke boxes. |
| **Hand-rolled SVG in measured pixel coordinates** (`ForecastBandChart`, `useMeasure`) | No chart library. Strokes stay true to size; nothing stretches with a viewBox. Any new chart follows this pattern. |
| **Mono for numbers** (`--font-mono`, IBM Plex Mono) | Digits align in a column. Every figure below is tabular. |
| **Spec §16: organised around decisions, not raw data** | The strongest constraint. Every panel should answer *what should I do*, with the number as evidence — not lead with the number. |

Two implications worth stating, because they decide several choices later:

**Uncertainty is the product, not a decoration.** A design that shows only `p50` throws away
what the entire modelling effort was for. The band is the thing; the median is a line through
it.

**A probability that is never checked against an outcome is decoration.** Wherever the
platform states a probability, and the outcome is known, show whether it held.

---

## 2. What the models actually produce now

Six trained models plus two derived layers. Four of the six are new since the dashboard was
designed.

### 2.1 Generation forecast — `POST /forecast` *(live, already wired)*

Per site, per hour, 1–72 h: `p10_mw`, `p50_mw`, `p90_mw`, `clearsky_mw`, `physics_mw`.

Measured on plants held out of training entirely:

| | nMAE | 24 h | 48 h | 72 h | Interval coverage (nominal 80%) |
|---|---:|---:|---:|---:|---:|
| Solar | **8.35%** | 8.22% | 8.35% | 8.49% | 82.7% |
| Wind | **14.24%** | 13.69% | 14.12% | 14.92% | 78.9% |

Against baselines on a time holdout:

| | Model | Smart persistence | Climatology | Physics only |
|---|---:|---:|---:|---:|
| Solar | **5.67%** | 7.41% | 7.51% | 14.61% |
| Wind | **11.91%** | 28.41% | 25.86% | 16.20% |

**What changed:** the corpus is now genuine 24/48/72 h forecasts, so `horizon_h` is a real
feature. Mean interval width grows with lead — solar 0.215 → 0.219, wind 0.391 → 0.427 — but
only by 1.8% and 9.2%. **Conditions move the band far more than lead time does.** A design
assuming a widening cone will look broken against real data; see §4.1.

### 2.2 Regional demand — *no endpoint yet* ⚠️

Per region, per hour: `p10_mw`, `p50_mw`, `p90_mw`. Trained on real AEMO operational demand.

| Region | nMAE | Coverage |
|---|---:|---:|
| QLD1 | 1.84% | 80.2% |
| NSW1 | 2.27% | 82.6% |
| SA1 | 3.17% | 84.6% |
| TAS1 | 4.15% | 88.8% |
| VIC1 | 4.33% | **66.9%** ⚠️ |

Overall **3.15% against 10.88%** for seasonal-naive — a 71% skill score.

**VIC1 is a known limitation**: seasonal bias no scalar correction reaches. If a demand panel
shows per-region confidence, VIC1 should carry a caveat marker rather than be presented at
parity.

**The dashboard currently invents demand** from a hashed synthetic curve in
`lib/derive/util.ts` (`DEMAND_CURVE`). That is the single largest gap between what is shown
and what exists.

### 2.3 Regional scenarios — *internal, feeds balance*

200 coherent 72-hour trajectories across every plant in a region. Not per-hour quantiles —
complete, physically plausible futures that preserve how errors move together.

Verified against outcomes:

| | Ensemble coverage | Naive quantile sum | Naive width |
|---|---:|---:|---:|
| Solar SA1 | **80.2%** | 99.2% | 2.6× wider |
| Wind SA1 | **83.5%** | 99.2% | 1.2× |
| Wind NSW1 | **86.6%** | 100.0% | 1.4× |
| Solar NSW1 | 71.8% | 100.0% | 3.5× |

**This is the strongest "why we built it this way" story in the project** and the dashboard
shows none of it. See §5.1.

### 2.4 Regional balance — `POST /balance` *(live, wired into Balance module)*

Per hour: demand band, renewable band, residual band, `p_surplus`, `p_shortage`, expected and
conditional magnitudes, `recommended_action`. Plus `events[]` (runs of 2+ hours) and
`actual[]` (what really happened).

| | Base rate | Brier | Skill vs climatology |
|---|---:|---:|---:|
| SA1 surplus | 18.5% | 0.0568 | **+62.3%** |
| SA1 shortage | 7.6% | 0.0174 | **+75.3%** |
| NSW1 shortage | 3.6% | 0.0119 | **+65.8%** |

**`data_mode` is `"replay"`.** The demand model needs load at the issue time and the AEMO
ingest ends before today, so the served window is real history, not tonight. The UI must say
so. It also means `actual[]` exists — use it (§4.4).

### 2.5 Storage dispatch — *no endpoint yet* ⚠️

Two-stage stochastic LP over the scenarios. Produces an hourly schedule (charge, discharge,
state of charge, curtailment, unserved), a committed hour-1 action, and an expected cost in
AUD.

And the headline result:

| | SA1 | NSW1 |
|---|---:|---:|
| **VSS** — planning against the ensemble vs the median | **170,422 AUD/yr** | 0 |
| **EVPI** — what perfect foresight would add | 40,086 AUD/yr | 0 |
| Windows where it mattered | 1 of 12 | 0 of 12 |

NSW1 is zero **correctly** — 10 GW of dispatchable headroom against 1.7 GW of import capacity
means nothing is ever scarce. Presenting that honestly is more convincing than hiding it.

### 2.6 Reference data — `GET /sites`, `GET /regions` *(live)*

`/sites` now carries `region` and a corrected `in_training_data`. **151 of 172 sites are
flagged as trained; the Gujarat sites are genuine cold starts.** The old endpoint reported
every trained plant as unseen, so any UI logic built on that flag was inverted.

---

## 3. Module-by-module: what is stale

| Module | Status | What to do |
|---|---|---|
| **01 Overview** | Partly stale | Headline figures predate the retrain. Rebuild from §2. |
| **02 Forecast** | ✅ Accurate | Real model. Only the metadata caption needs updating. |
| **03 Balance** | ✅ Regional panel is real | Site panel below it still uses the synthetic demand curve — label or retire. |
| **04 Reliability** | ❌ **Fabricated** | Backend has *no* reliability model, deliberately. See below. |
| **05 Seasonal** | ❌ **Fabricated** | Cut from Phase 2. Derived from a site-id hash. |
| **06 Demand** | ❌ **Fabricated** | A real model exists and is better than what is shown. |
| **07 Investment** | ⚠️ Scenario only | Phase 3. Honest if labelled; misleading if not. |

### The two that matter most

**Reliability (04) is the most serious.** `lib/derive/reliability.ts` produces risk scores from
`hash01(site_id)` — a deterministic hash, not a model. The backend deliberately has no
reliability model, because no public failure or maintenance records exist for these plants,
and spec §26 explicitly warns against claiming failure prediction. A panel that presents
hashed numbers as equipment risk is the one thing in this project that could mislead someone
into a maintenance decision.

> **Recommendation:** replace the panel content with an honest statement of the gap — what
> reliability analysis would require, why it was deferred, what the platform would need to do
> it. In the console's typographic style this reads as rigour, not absence. It is also true,
> which the current panel is not.

**Seasonal (05) is the same problem, lower stakes.** Derived from a hash. Either remove the
module or replace it with the one seasonal thing that *is* real: three years of AEMO history
are on disk, and recurring surplus by month × hour is computable in an afternoon (§5.3).

---

## 4. How to draw each output

### 4.1 The forecast band — refine, do not redesign

`ForecastBandChart` is good. Three changes:

**Stop implying the band widens with lead.** It grows 1.8% (solar) across three days while
conditions move it threefold. If the design suggests a cone, real data contradicts it. Let
width be what it is, and add a one-line reading aid: *"Band width tracks forecast conditions,
not lead time — a narrow band at hour 60 is a genuinely predictable period."*

**Draw `clearsky_mw` as a ghost line.** A faint dashed line at `--text-muted` above the band
turns the chart from "a number" into "output against the physical ceiling". The gap between
p50 and clear-sky *is* the cloud forecast, visible at a glance. This is the single
highest-value, lowest-cost addition to an existing chart.

**Mark the lead-day boundaries.** Two faint vertical hairlines at hours 24 and 48, labelled
`+1d` / `+2d` in mono. The horizon is three days and currently reads as one continuous run.

```
  MW ┤                    ╭──── clearsky (ghost, dashed, muted)
     │        ╭───────────╯
     │     ╭──┤▒▒▒▒▒▒▒▒▒▒▒│▒▒▒▒▒╮        ▒ = p10–p90, accent-soft
     │  ╭──┤▒▒▒▒▒━━━━━━━▒▒│▒▒▒▒▒▒▒╮      ━ = p50, accent
     │──┴──┴─────────────┼─────────┴──
        0h        │+1d   │+2d        72h
```

### 4.2 Demand — the same band grammar, mirrored

Once a demand endpoint exists, draw demand with the *same* band treatment in a different hue
(`--c-blue`), directly above or below generation on a shared time axis. Two bands, one axis,
and the reader sees the balance before any arithmetic is shown.

Do **not** invent a third visual language for it. The band grammar is already learned by then.

### 4.3 Residual load — the inverted axis is the whole point

`residual = demand − renewable`, so **negative means surplus**. This is the one field most
likely to be drawn backwards.

Draw it as a filled area crossing a zero line, with the fill colour keyed to the sign:
`--c-green` below zero (surplus), `--c-amber`/`--c-red` above the dispatchable headroom
(shortage), neutral between. Put a labelled horizontal rule at the headroom value — it is a
measured number (1,610 MW for SA1), not a guess, and it explains why some hours are shortage
and others merely tight.

```
   MW ┤─────────────────────── headroom 1,610 MW (measured)
      │▓▓▓                ▓▓▓▓         ▓ shortage  (above rule)
      │───────────────────────────  0
      │   ░░░░░░░░               ░░░   ░ surplus   (below zero)
```

### 4.4 Probabilities — and whether they held

This is where the console can do something most dashboards cannot.

**Probability strip.** A 72-cell horizontal band under the main chart, one cell per hour,
opacity keyed to `p_surplus` / `p_shortage`. It reads as a heat strip and makes runs visible
instantly — which is what `events[]` formalises. Use `CellGrid`'s hairline rhythm so it sits
in the existing grid.

**Show the outcome.** Because `data_mode` is `"replay"`, `actual[]` is in the payload. Overlay
the actual as a thin white line on the band and report the hit rate — *"the band held in 69 of
72 hours."* No forecasting product can normally show this. It is the most credible thing on
the screen and it costs one line.

**Never sum per-site p10 for a regional figure.** Summing across plants assumes every one has
a bad hour simultaneously; measured, that band covers 99–100% of hours at up to 3.5× the width
it needs. `/balance` does it correctly. This is documented as a prohibition in
`docs/api-contract.md` and repeated here because it is the easiest mistake to make.

### 4.5 Events — a table, not a chart

`events[]` is already decision-shaped: kind, window, duration, peak probability, energy. A
ruled table in mono, coloured by kind, is the right treatment — and it is what an operator
reads first.

Lead the module with the strongest event as a sentence, then the evidence:

> **Surplus likely, 08:30–14:30 local — 2,275 MWh over 7 hours, peak probability 100%.**

That is spec §16's "organised around decisions" in one line.

### 4.6 Storage dispatch — separate the commitment from the plan

The schedule has a property worth making visual: **hour 1 is a firm commitment, hours 2–72 are
indicative** and will be re-optimised as forecasts update.

Draw state of charge as a filled area with charge/discharge as a diverging bar beneath it, and
render hour 1 solid while the remainder is hatched or reduced in opacity. One visual device,
and the two-stage nature of the optimisation becomes self-explanatory.

### 4.7 The VSS — one number, stated plainly

**170,422 AUD/yr** is the answer to "why model uncertainty at all", and it deserves a single
large mono figure with the comparison beneath it, not a chart:

```
    VSS          A$170,422 / yr
    ── planning against 200 scenarios
       instead of the median forecast

    EVPI          A$40,086 / yr        ceiling a perfect forecast would add
    Positive in   1 of 12 windows      rare, and real when it happens
```

Report the rarity. "Positive in 1 of 12 windows" is more convincing than the annual figure
alone, because it is the kind of detail a fabricated number never includes. And show NSW1's
zero next to it — a metric that is honest about where it does *not* apply reads as measured.

---

## 5. Three things the dashboard is missing entirely

### 5.1 The aggregation comparison — the best unbuilt visual

One chart, two bands on the same axis: the naive per-site quantile sum against the correctly
aggregated ensemble. Measured, the naive band is **2.6× to 3.5× wider** and covers 99–100% of
hours against a nominal 80%.

This shows, in a single image, why the scenario machinery exists — that the obvious approach
produces a grid that looks far less reliable than it is, and would have an operator procure
reserve for a shortfall the fleet does not have. Data is already in
`reports/scenario_verification.json`.

### 5.2 A reliability diagram for the probabilities

Predicted probability on one axis, observed frequency on the other, the diagonal as reference.
Where the platform said 0.94, shortage occurred 93% of the time. In a ruled, monochrome
console a reliability diagram looks native, and it is the difference between asserting
calibration and demonstrating it. Data is in `reports/balance_verification.json`.

### 5.3 Seasonal patterns, done for real

Three years of AEMO history are on disk. Recurring surplus by month × hour is a small
computation and renders naturally as a heat grid — months down, hours across, one cell per
pair. It is the bridge from "tomorrow's surplus" to "this recurs every summer, and here is the
storage it would take to absorb it", which is spec §18's stated USP and currently nowhere in
the product.

---

## 6. Priority order

By value per unit of work.

| # | Change | Effort | Why |
|---|---|---|---|
| 1 | **Fix or remove the Reliability panel** | Low | It presents hashed numbers as equipment risk. Correctness before features. |
| 2 | **Clear-sky ghost line on the forecast chart** | Low | Turns a number into a number-against-a-ceiling. Data already in the payload. |
| 3 | **Actual overlay + "band held" on Balance** | Low | Already in the payload. Most credible thing on the screen. |
| 4 | **Expose the demand model, replace the synthetic curve** | Medium | Removes the largest shown-vs-exists gap. |
| 5 | **Aggregation comparison chart** | Medium | The strongest argument the project has, currently invisible. |
| 6 | **Storage dispatch panel + VSS figure** | Medium | The headline result. Needs an endpoint. |
| 7 | **Seasonal, computed for real** | Medium | Replaces a fabricated module with the spec's USP. |
| 8 | **Reliability diagram** | Low–Medium | Demonstrates calibration rather than claiming it. |

**Items 1–3 are a single afternoon** and between them remove the one misleading panel and add
the two most credible visuals in the product.

---

## Appendix: endpoints and their status

| Endpoint | Status | Feeds |
|---|---|---|
| `POST /forecast` | Live | Forecast module |
| `GET /sites` | Live | Site selector, cold-start flag |
| `GET /regions` | Live | Region selector, `balance_available` |
| `POST /balance` | Live (replay) | Balance module |
| `GET /health` | Live | Status banner |
| `POST /demand` | **Not built** | Demand module (§4.2) |
| `POST /storage/dispatch` | **Not built** | Storage panel (§4.6) |
| `GET /vss` | **Not built** | VSS figure (§4.7) |
| `GET /seasonal/{region}` | **Cut** | — |
| `GET /reliability` | **Deferred, no model** | — |

Exact request and response shapes, field semantics and the prohibitions are in
[`docs/api-contract.md`](api-contract.md). Real payloads from real runs are in
[`docs/fixtures/`](fixtures/).
