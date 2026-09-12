# Phase 2 — Operational Intelligence

**Status:** approved design, ready for implementation planning
**Date:** 2026-09-12
**Depends on:** Phase 1 (`xgb-q-0.1.0`, merged to `main`)

---

## 1. Goal

> **Turn the per-site probabilistic MW forecast into an hourly regional energy balance with a
> recommended action and a price tag, 24–72 hours ahead, with uncertainty carried end to end.**

Phase 1 answered *"how much will be generated?"* Phase 2 answers *"will it be needed, can it be
stored, what should we do at 14:00 tomorrow, and what is that decision worth?"*

Spec §25 states the dependency chain: forecasting is the central model and every other module
consumes its output. Phase 2 builds the first two consumers — operational balance and storage — plus
the seasonal layer that connects short-term operations to long-term planning.

### Non-negotiable: every number is measured

The balance loop runs on real AEMO data — generation, regional demand, rooftop PV and spot price,
all from the same MMSDM archive, all aligned to the 151 plants in the trained corpus. No synthetic demand
curve, no assumed price. This is the reason the region decision went to Australia rather than
Gujarat (§10.1).

---

## 2. What Phase 2 consumes from the core model

The entire interface is the `SiteForecast` contract in `schemas.py`. Nothing else crosses the
boundary.

| Field | Downstream use |
|---|---|
| `p50_mw` | Expected generation — the centre of the balance equation |
| `p10_mw` | Firm generation — shortage risk, reserve sizing, backup commitment |
| `p90_mw` | Upside — curtailment risk, storage charge headroom |
| `p90 − p10` | Uncertainty width — *how much* reserve to hold, not merely whether |
| `clearsky_mw` | Theoretical maximum — curtailment attribution (weather vs. grid) |
| `physics_mw` | Audit trail, and graceful degradation out of distribution |
| `capacity_mw` | Normalisation for regional roll-up |

The `p10` is what makes the platform defensible. A shortage alert built on `p50` is a coin flip; one
built on a calibrated `p10` — ours covers 83.7% (solar) and 81.7% (wind) against a nominal 80% on
sites held out of training entirely — is a number an operator can act on.

---

## 3. The central design decision: scenarios, not quantiles

Everything downstream rests on this, so it is stated first and plainly.

**Marginal quantiles are insufficient for both aggregation and dispatch.**

**Aggregation.** Summing `p10` across 40 plants assumes their forecast errors are perfectly
correlated. They are not — a cloud over one plant is not a cloud over all of them — so the naive sum
understates firm regional capacity, and the error grows with site count. Conversely, treating them
as independent overstates it. Neither is acceptable when the output is a reserve-commitment number.

**Dispatch.** A battery's state of charge at hour 30 depends on what actually happened in hours
1–29. Storage is a path-dependent problem. You cannot dispatch against a quantile because a quantile
describes one hour in isolation; you dispatch against a *trajectory*.

### Resolution: empirical copula coupling (Schaake shuffle)

Convert the six models' output into **200 coherent scenarios**, each a complete 72-hour trajectory
across every site in the region.

1. From the Phase 1 holdout, collect the matrix of forecast errors: `(day) × (site) × (hour)`.
2. Sample historical error days as **whole blocks**, not element-wise.
3. Add each sampled block to the current `p50` forecast surface.
4. Rank-match back onto the model's own marginal quantiles so the per-hour, per-site marginals stay
   exactly as calibrated.

Block resampling preserves cross-site correlation and hour-to-hour correlation for free. There is no
new model to fit — it runs on residuals that already exist. This is the standard method in the
probabilistic power forecasting literature for precisely this problem.

**Scenarios become the currency of Phase 2.** Balance, storage and alerts all read scenarios.
Quantiles are re-derived from the scenario ensemble only at the very end, for display.

### Consequence for the API

Two distinct endpoints, and the contract must make the difference unmissable:

- `/forecast` — per-site marginal quantiles (Phase 1, unchanged)
- `/balance` — regional aggregate derived from scenarios

A consumer that sums `/forecast` `p10` values across sites will get a wrong answer. The contract
document states this as a prohibition, not a footnote (§8).

---

## 4. Architecture

```
   Phase 1 (done)                          NEW in Phase 2
   ──────────────                          ──────────────
   SiteForecast                    AEMO MMSDM: DISPATCHREGIONSUM
   p10/p50/p90 per site  ──┐                 DISPATCHPRICE
                           │                 ROOFTOP_PV_ACTUAL
                           │                        │
                           ▼                        ▼
              portfolio/aggregate.py        models/demand/
              Schaake shuffle               quantile XGBoost
              → 200 regional                → demand p10/p50/p90
                trajectories                        │
                           └───────────┬────────────┘
                                       ▼
                              balance/residual.py
                     residual_load = demand − generation
                     per hour × per scenario → P(surplus), P(shortage),
                     expected MWh, expected duration
                                       │
                                       ▼
                              storage/dispatch.py
                     two-stage stochastic LP over scenarios
                     objective in real $ from spot price
                     → committed action for hour 1, recourse after
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
            api/ + contract doc                  seasonal/patterns.py
      the frontend team builds against      3 yr history → recurring
                                            surplus / drought / storage gap
```

The Phase 1 structural rule carries forward unchanged: `features/build.py` remains the single
train/serve boundary, and the demand model gets its own equivalent — `models/demand/features.py`,
shared by its trainer and its server.

---

## 5. Data

### 5.1 New sources — all verified reachable 2026-09-12

Probed with `HEAD` through the existing `aemo.table_urls()` path; all returned 200.

| Table | Content | Size/month | Role |
|---|---|---|---|
| `DISPATCHREGIONSUM` | Regional demand, 5-min, per NEM region | 5.8 MB | Demand target, and more — below |
| `DISPATCHPRICE` | Regional spot price (RRP), 5-min | 2.0 MB | Dispatch objective in real $ |
| `ROOFTOP_PV_ACTUAL` | Behind-the-meter rooftop PV estimate, 30-min | 0.2 MB | Demand feature |
| `TRADINGPRICE` | 30-min settlement price | 0.7 MB | Cross-check on `DISPATCHPRICE` |

~280 MB for 36 months, matching the existing generation window (2023-09 → 2026-08).
**Ingested: 131,520 rows, 26,304 hours × 5 regions, no gaps.**

`DISPATCHREGIONSUM` proved to carry considerably more than demand, and three of its fields replace
quantities this design had planned to assume:

| Field | Replaces |
|---|---|
| `AVAILABLEGENERATION` | The configured dispatchable-headroom constant in §6.4 — now measured |
| `SS_*_UIGF` vs `SS_*_CLEAREDMW` | **Measured curtailment.** What the intermittent fleet could produce against what it was allowed to. Ground truth for the quantity §6.4 predicts, rather than a modelled proxy |
| `DEMANDFORECAST` | AEMO's own demand forecast — a second, much stronger baseline than seasonal-naive |
| `BDU_INITIAL_ENERGY_STORAGE` | Aggregate regional battery state of charge (from mid-2025 only) |

Two silent traps, both handled in `ingest/aemo_market.py`: dispatch tables carry intervention runs
that duplicate an interval, and `ROOFTOP_PV_ACTUAL` publishes both `MEASUREMENT` and `SATELLITE`
estimates for the same half hour.

**Negative demand is real and must not be filtered.** 257 hours over three years have operational
demand below zero, all in SA1. The extreme is Christmas Day 2025 at 13:30 local: a public holiday
with minimal industrial load, 1,780 MW of rooftop PV, demand at −280 MW and spot price at
−$251/MWh. Rooftop solar alone exceeded the entire state's consumption. This is the condition the
platform exists to anticipate, so validation permits it and guards the rate instead — a sign error
would make negative demand common rather than 0.2% of hours.

`ROOFTOP_PV_ACTUAL` was not in the original plan and is a material find. Operational demand is
*net* of rooftop PV, so on a sunny mild day it collapses in a way no calendar or temperature feature
can explain. Without this term the demand model would systematically miss the midday trough — which
is exactly the hour the surplus logic cares about most.

### 5.2 Regional structure

| NEM region | Solar sites | Solar MW | Wind sites | Wind MW | Total MW |
|---|---:|---:|---:|---:|---:|
| NSW1 (incl. ACT) | 27 | 2,910 | 17 | 2,460 | 5,370 |
| VIC1 | 10 | 1,127 | 28 | 3,809 | 4,936 |
| QLD1 | 30 | 2,546 | 4 | 968 | 3,514 |
| **SA1** | 9 | 829 | 26 | 2,494 | 3,323 |
| TAS1 | 0 | 0 | 4 | 567 | 567 |

Counts are registry entries (155). Four are excluded from the trained corpus by
`profile_matches_technology` — mislabelled batteries and units whose generation profile contradicts
their declared technology — leaving 151. The balance module must roll up over the *corpus* set, not
the registry, or it will attribute capacity to plants with no model behind them.

All five regions are supported. **SA1 is the flagship demo region**: the highest-penetration large
grid in the world, routinely above 100% instantaneous renewable share, with genuine curtailment and
genuine negative prices in the data. The surplus-and-storage narrative there is measured rather than
hypothetical. NSW1 is the secondary demo — the most balanced solar/wind mix and the largest site
count, so the correlation model is best exercised there.

Region is currently embedded in the site `name` suffix. Wave 0 promotes it to a first-class
`nem_region` field on `SiteMeta`.

### 5.3 Data domains still absent

Stated so the plan does not silently imply coverage the platform lacks. From spec §21:

| Domain | Status | Phase 2 treatment |
|---|---|---|
| Storage | No public per-site data | Configurable asset model (MWh, MW, η, SoC bounds) — the correct approach regardless |
| Equipment | No public failure or maintenance records | **Deferred** — see §9 |
| Economics | No CAPEX/OPEX feed | Phase 3; spot price covers Phase 2's needs |
| Demographic | None | Phase 3 |

### 5.4 `data_india.zip`

121 CEA *Daily Renewable Generation Reports* (Aug–Nov 2025). The `ISGS` sheet is a registry of ~235
named Indian plants with state, owner, technology, operational capacity and daily generation.

Not on the Phase 2 critical path — it has no demand, no hourly resolution and no coordinates. It is
retained for Phase 3 as (a) a real Indian site registry for cold-start demonstration and (b) a
domain-shift validation set, comparing forecast daily totals against CEA actuals.

---

## 6. Modules

### 6.1 Wave 0 — close the multi-lead gap (blocking)

**The defect.** `artifacts/*_metadata.json` records `horizons_present: [24, 24]`, and both
`horizon_h` and `lead_day` were auto-dropped as constant features. The corpus is single-lead: every
training row is a 24-hour-ahead NWP. The API serves horizons 1–72. A 72-hour NWP carries roughly
twice the error of a 24-hour one, so the model is overconfident at long leads and its band does not
widen with horizon.

This blocks Phase 2 rather than merely embarrassing Phase 1: the balance and dispatch modules read
band *width* directly, so a band that does not grow with lead time produces reserve numbers that are
too small exactly where uncertainty is largest.

**The fix.** Refetch from Open-Meteo Previous Runs at leads 1, 2 and 3 together, replacing the
single-lead corpus rather than patching extra leads onto it.

*This paragraph supersedes an earlier version of this section, which framed 6,844 as "remaining
quota" and proposed 11 months at leads 2–3 only. Checked against `weather_bulk.estimate_calls` —
which reproduces the existing corpus cost of 9,699 exactly — the real figures are:*

| Window, all 3 leads | Calls | Quota days @ 10k |
|---|---:|---:|
| 12 months | 6,789 | 0.68 |
| 16 months | 9,058 | 0.91 |
| 3 years | 20,367 | 2.04 |

Full 3-year multi-lead is affordable but spans ~2 quota days, which was ruled out on schedule.
**16 months at all three leads, all 151 corpus sites — 9,058 calls, one quota day.** That is
*more* data than the corpus it replaces (2.53 M solar rows against 1.89 M, 1.34×), from a single
clean source, with genuine lead resolution and a full seasonal cycle.

Site diversity over history length is the deliberate trade: diversity drives cold-start
generalisation, the property the whole design rests on, while lead-time skill decay is a smooth
function that does not need three years to estimate.

**There is no bulk-download bypass**, and this was checked rather than assumed — the Open-Meteo S3
open-data bucket was probed directly on 2026-09-12:

- `data_spatial/dwd_icon/` holds per-run files, the only lead-resolved source, and covers **8 days**
  (2026-09-05 to 09-12). A rolling window, not an archive.
- `data/dwd_icon/<var>/` holds ~3.35 years (116 chunks × 253 h) but is a best-available time series
  with **no lead dimension** — the same kind of data as the old corpus, merely unmetered.

So the API is the only source of genuine 24/48/72 h separation, and it is quota-bound. Recorded here
so the S3 route is not re-investigated for this purpose later; `ingest/weather_s3.py` remains useful
only for unmetered single-lead bulk history.

**Consequential change: CQR calibration becomes per-lead-bucket.** A single scalar widening across
1–72 h defeats the purpose. `splits.py::conformal_widening` returns a vector indexed by lead bucket
(1–24 / 25–48 / 49–72); `predict.py` selects by the horizon of each row. Calibration remains fitted
on the site-disjoint `calib` group, for the exchangeability reason established in Phase 1.

**Acceptance:** `horizon_h` survives feature selection; measured band width increases monotonically
across lead buckets; per-bucket coverage lands within ±3 pp of 80% on unseen sites; lead-1 nMAE does
not regress by more than 0.3 pp against the current 8.30% / 12.38%.

### 6.2 Demand model

Quantile XGBoost on regional operational demand, normalised by regional peak. Same architecture as
generation: three quantiles, CQR-calibrated per lead bucket, time-blocked split.

**Features:** calendar (hour, day-of-week, national holidays) · temperature with HDD/CDD and a
24 h accumulated-heat term · GHI, cloud and wind at the load centre · load lags at `t₀`,
`t₀ − 24 h`, `t₀ − 168 h` with rolling level and volatility · rooftop PV *lagged 24 h*.

**Correction to an earlier draft: measured `ROOFTOP_PV_ACTUAL` is not a feature.** The reasoning
for wanting it was right — operational demand is net of rooftop output — and that is exactly what
disqualifies the *measured* value: it is an actual, and nobody has it when the forecast is issued
two days ahead. Including it would post an excellent validation score for a model that cannot be
served. What is legitimate is everything rooftop output is made of — the GHI and cloud forecast at
the valid time, which an NWP genuinely provides — plus rooftop's own level as of the issue time.
Those carry the midday-trough signal without borrowing the answer. T10 asserts it stays out.

**Weather at load centres, not generation sites.** Demand follows the weather where people are; the
fleet sits hundreds of kilometres away. Five city cells (Sydney, Brisbane, Adelaide, Hobart,
Melbourne), fetched as archived *forecasts* rather than ERA5 reanalysis — a model trained on truth
and served on forecasts degrades silently.

**The load-lag departure.** Phase 1 deliberately banned power lags because a generation forecast at
`t₀ + 48 h` cannot see generation at `t₀ + 47 h`. Demand is different: load *at or before*
`issue_time` genuinely is known when the forecast is issued, and it is the single strongest
predictor. It is therefore admitted — but this makes leakage the dominant risk in this module, so it
gets a blocking test in the same spirit as T1: assert every lag offset used is `≤ issue_time`, and
assert that shuffling future load leaves predictions bit-identical.

**Baseline:** seasonal-naive (same hour, previous week), the standard reference for load. Also
compared against AEMO's own published demand forecast where it is available in the archive.

**Split:** time-blocked. Sites are not a dimension here — there are five regions, and holding one
out is not meaningful because regional load curves are not exchangeable. This is a real difference
from the generation model and is stated rather than glossed.

### 6.3 Portfolio aggregation

The Schaake shuffle described in §3, plus the residual-history store it needs.

**Verification:**
- Rank histogram / PIT on regional totals — flat means the ensemble is calibrated
- Variogram score on the multivariate trajectories — captures whether spatial correlation is right,
  which a marginal score cannot see
- An explicit chart contrasting the naive quantile-sum against the copula result, quantifying how
  wrong the simple approach is. This is a deliverable, not a diagnostic: it justifies the machinery.

### 6.4 Balance

Per hour, per scenario:

```
residual_load = demand − renewable_generation
surplus       when residual_load < 0
shortage      when residual_load > available_generation
```

Aggregated across scenarios into: probability of surplus, probability of shortage, expected
magnitude (MW), expected energy (MWh), expected run duration (h).

`available_generation` was to have been a configured constant, since no dispatchable-fleet data was
expected. `DISPATCHREGIONSUM.AVAILABLEGENERATION` supplies it as a measurement instead (§5.1), so
the shortage threshold is observed rather than assumed.

The same table also yields **measured curtailment**, which turns §6.4 from an unfalsifiable
construct into something scoreable: the surplus logic predicts curtailment, and `SS_*_UIGF` minus
`SS_*_CLEAREDMW` says what actually happened.

**Verification:** Brier score on the surplus and shortage events, plus a reliability diagram — so
that "70% chance of surplus" is a statement that held 70% of the time. A probability that is not
reliability-checked is decoration.

### 6.5 Storage dispatch

Two-stage stochastic linear program. Hour 1 is the here-and-now commitment; hours 2–72 are recourse
per scenario.

**Objective, in real dollars from spot price:**

```
minimise  E[ curtailment loss + unserved-energy penalty
             + import cost − export revenue ]
subject to SoC dynamics, power limits, round-trip efficiency,
           SoC bounds, terminal SoC condition
```

**Deliberately an LP, not a MILP.** The usual formulation adds a binary to forbid simultaneous
charge and discharge. That binary is redundant whenever round-trip efficiency < 1, because
simultaneous charge and discharge strictly loses energy and can never be optimal. Dropping it keeps
200 scenarios × 72 hours solvable in seconds instead of minutes, with no loss of correctness. The
solver is `scipy.optimize.linprog` (HiGHS); OR-Tools remains available behind the same interface if
Phase 3 introduces genuine integer constraints.

**Terminal SoC** is constrained to a configured fraction rather than left free — an unconstrained
horizon-end causes the optimiser to dump the entire battery in hour 72, which is an artefact of the
window, not a real recommendation.

### 6.6 Seasonal patterns (Module 3)

Mining the 3-year history rather than the forecast:

- Recurring surplus by (month × hour), per region
- Wind-drought (*Dunkelflaute*) identification and duration distribution
- **Storage adequacy:** what MWh would have been required to absorb the summer surplus that recurs
  every year?

That last question is the bridge from operations to investment and is the spec's stated USP (§18):
the platform does not just flag tomorrow's surplus, it recognises the surplus as recurring and sizes
the asset that would fix it.

---

## 7. The headline result

**Value of the Stochastic Solution (VSS).**

Backtest three dispatch policies over the holdout:

1. **Perfect foresight** — upper bound, not achievable
2. **Deterministic** — dispatch on the `p50` point forecast
3. **Stochastic** — dispatch on the full scenario set

The gap between (2) and (3), in dollars per year, is what the Phase 1 uncertainty work is *worth*.
The gap between (3) and (1) is honest headroom remaining.

This is the strongest single result Phase 2 can produce, because it closes the argument: it is the
quantitative reason the p10/p90 bands exist at all. A platform that merely displays an uncertainty
band asserts that uncertainty matters. This measures it.

---

## 8. Frontend contract deliverable

The frontend is built by a separate team, so the output contract is a first-class deliverable rather
than documentation written afterwards.

`docs/api-contract.md` must contain:

- Every endpoint: exact JSON shape, units, ranges, null semantics, error responses
- What each field *means* for a UI, and what it must **not** be used for — in particular the
  prohibition on summing per-site `p10` across sites (§3)
- Threshold and severity semantics for alerts, so their colour scale and our logic agree on what
  "critical" means
- **Real example payloads generated from actual runs**, committed as fixtures under
  `docs/fixtures/`, so nothing they build against is fictional
- A stability contract: which fields are frozen for Phase 2, which may change, and which are additive

Written and published before the backend is complete, so the two teams can work in parallel.

### Endpoint surface

| Endpoint | Returns |
|---|---|
| `POST /forecast` | Per-site quantile forecast (Phase 1, unchanged) |
| `GET /regions` | Region list, installed capacity by technology, site counts |
| `POST /balance` | Hourly regional balance: generation band, demand band, residual load, P(surplus), P(shortage), expected MWh |
| `POST /storage/dispatch` | Recommended schedule, committed hour-1 action, expected cost, SoC trajectory |
| `GET /seasonal/{region}` | Recurring patterns, drought statistics, storage adequacy |
| `GET /alerts` | Ranked operational alerts with severity, horizon and recommended action |
| `GET /health` | Extended with demand-model and scenario-store status |

---

## 9. Deferred: reliability (Module 4)

Spec §28 lists basic reliability analysis under Phase 2. It is deferred, for stated reasons:

1. **No data exists.** There are no public failure records, maintenance logs or component-level
   histories for these plants. The only available substitute is outage events mined from SCADA
   gaps — which conflates genuine equipment failure with curtailment, network constraint, and
   economic withholding. In a high-curtailment region like SA1 the latter dominate, so a "failure
   risk" score built this way would largely be measuring negative prices.
2. **The spec warns against exactly this.** §26: *"The system should not claim that a failure can
   always be predicted."* Shipping a weakly-grounded risk score would be the least defensible claim
   in the platform.

Deferred to Phase 3, contingent on obtaining real maintenance records. If it must ship sooner, the
honest form is availability-pattern reporting — observed outage frequency and duration by season and
by plant, clearly labelled as historical description rather than prediction.

---

## 10. Decisions and their reasoning

### 10.1 Region: Australia, not Gujarat

Australia has real regional demand, real spot price and real rooftop PV in an archive already
downloaded and aligned to the 151 corpus plants. Gujarat matches the spec's framing (GEDA, the ₹500 crore
scenario) but has no public hourly demand, so the balance module would run on a constructed load
curve — and every downstream number, including the VSS, would inherit that fabrication.

The cost is narrative fit. The mitigation is that the models are region-agnostic by construction
(dimensionless targets, physics priors, cold-start capable), so Phase 3 can point them at India with
the Indian registry from `data_india.zip` once demand data is sourced.

### 10.2 Scenarios over quantile arithmetic

Simpler alternative: naive quantile sum plus deterministic `p50` dispatch. Rejected — it is wrong in
a way a knowledgeable reviewer spots immediately, and it makes the VSS result impossible to compute,
which removes the strongest argument the project has.

### 10.3 LP over MILP

See §6.5. The binary is redundant under round-trip efficiency < 1.

### 10.4 Demand admits load lags; generation does not

See §6.2. Different information sets at issue time. The asymmetry is intentional and separately
tested.

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Error-correlation structure fitted on Australian sites may not transfer to other regions | It is residual-based and scales with site count rather than geography; documented as a transfer assumption, revisited when Indian data arrives |
| R2 | Open-Meteo quota exhausted mid-fetch in Wave 0 | Existing resumable per-site parquet cache and `QuotaExhausted` handling; 11-month window sized to leave a ~13% call margin (§6.1). If it still exhausts, the fetch resumes next quota day and Wave 0 blocks — so it runs first, alone |
| R3 | Demand-model leakage via load lags | Blocking test: assert all lag offsets `≤ issue_time`; assert predictions invariant to shuffled future load |
| R4 | Stochastic LP too slow for interactive API | LP not MILP; scenario count configurable; results precomputed per issue hour and cached, matching the existing weather-cache pattern |
| R5 | Retrain in Wave 0 regresses lead-1 accuracy | Explicit acceptance gate (§6.1); previous artifacts retained and restorable |
| R6 | Terminal-SoC artefact produces absurd hour-72 recommendations | Terminal SoC constrained (§6.5); regression test on the last 6 hours of the horizon |
| R7 | Frontend team blocked waiting on backend | Contract and fixtures published first (§8) |

---

## 12. Definition of done

1. `horizon_h` is a live feature; per-lead-bucket coverage within ±3 pp of 80% on unseen sites; band
   width increases monotonically with lead bucket; lead-1 nMAE not regressed beyond 0.3 pp.
2. Demand model beats seasonal-naive in every lead bucket, in every region, with calibrated bands.
3. Regional ensemble passes PIT/rank-histogram calibration; the naive-sum comparison chart exists
   and quantifies the difference.
4. Surplus/shortage probabilities pass a reliability diagram; Brier score beats climatology.
5. Storage dispatch returns a schedule respecting all physical constraints, verified against a
   brute-forced small instance.
6. **VSS computed and reported in dollars per year for SA1 and NSW1.**
7. `docs/api-contract.md` published with real fixtures; frontend team unblocked.
8. Reliability deferral stated in the report with its reasoning, not silently omitted.
9. Full test suite green, including the new blocking leakage test.
