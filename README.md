# Renewable Energy Intelligence Platform

**24–72 hour solar and wind power forecasting with calibrated uncertainty bands.**

The platform described in `renewable_energy_intelligence_platform_project_spec.md`. Section 25
of that spec makes forecasting the central model that Modules 2–7 all consume, so Phase 1
delivers not just a model but **the forecast contract those six modules are built against**.
Phase 2 builds the first consumers of it — regional demand, energy balance and storage.

## Results

Two numbers matter, and they answer different questions. Both are normalised by installed
capacity and neither was seen during fitting.

**Generalisation to plants with no history** — 20% of sites held out entirely, which is the
question `/forecast` actually gets asked, since it takes an arbitrary latitude and longitude:

| | nMAE | 24 h | 48 h | 72 h | Interval coverage (nominal 80%) |
|---|---:|---:|---:|---:|---:|
| **Solar** | **8.35%** | 8.22% | 8.35% | 8.49% | 82.7% |
| **Wind** | **14.24%** | 13.69% | 14.12% | 14.92% | 78.9% |

**Against baselines**, on a contiguous time holdout at sites the model knows:

| | Model | Smart persistence | Climatology | Physics only |
|---|---:|---:|---:|---:|
| **Solar** | **5.67%** | 7.41% | 7.51% | 14.61% |
| **Wind** | **11.91%** | 28.41% | 25.86% | 16.20% |

The model beats every baseline on both technologies. The learned correction also removes a
large systematic bias: mean bias is −0.70% (solar) and +1.89% (wind), against −10.41% and
+5.87% for the physics-only estimate.

Training data is **genuine 24/48/72 hour forecasts** from the Open-Meteo Previous Runs
archive — what a forecaster actually had at that notice, not a best-available estimate — so
error growth with lead time is measured rather than assumed. The measured effect is real but
modest: mean interval width rises 1.8% (solar) and 9.2% (wind) from the 24 h bucket to the
72 h bucket. Day-to-day weather moves the band far more than lead time does.

Full breakdown: [`reports/benchmark.md`](reports/benchmark.md). Head-to-head against the
previous single-lead model: [`reports/lead_comparison.json`](reports/lead_comparison.json).

## Quick start

```bash
uv sync --extra dev
uv run pytest                                        # 64 tests

# Generation: real plant output, then matching multi-lead forecast weather
uv run python -m reip.ingest.aemo                    # AEMO SCADA -> canonical parquet
uv run python -m reip.ingest.build_corpus     --start 2025-05-01 --end 2026-08-31     --source previous_runs --corpus aemo_ml          # genuine 24/48/72h leads

# Market: regional demand, spot price, rooftop PV
uv run python -m reip.ingest.aemo_market --years 3
uv run python -m reip.models.demand.weather          # weather at each load centre

uv run python -m reip.models.train                   # p10/p50/p90 for solar and wind
uv run python -m reip.models.demand.train            # p10/p50/p90 for regional demand
uv run python -m reip.eval.report                    # benchmark against baselines

uv run uvicorn reip.api.main:app --port 8000
```

```bash
# A 730 MW site, or any latitude/longitude at all — no generation history required.
curl -X POST localhost:8000/forecast \
  -H 'content-type: application/json' \
  -d '{"latitude":23.03,"longitude":72.57,"tech":"solar","capacity_mw":50,"horizon_h":72}'
```

## The four decisions that matter

**1. Train on archived forecasts, never on observed weather.**
The standard way this class of project produces a fake accuracy number is to train on
measured irradiance, report a high R², and call it a 72-hour forecast. At hour 72 you do not
have measured irradiance — you have an NWP forecast whose error has been growing for three
days. GEFCom2014 is used precisely because it pairs *real weather forecasts* with *real
measured power*. ERA5 reanalysis is never used as a feature; it is the weather that
happened, and it does not exist at forecast time.

**2. Regress on a dimensionless target.**
Solar predicts the **clear-sky index** (`power / clear-sky power`), wind predicts **capacity
factor**. This strips out the fully deterministic component — diurnal cycle, season,
latitude — so the model spends all its capacity on the genuinely stochastic part: cloud and
wind variability. It is also what makes one model span a 1 MW anonymised zone and a 730 MW
Gujarat park, and what lets a site with no history be forecast at all.

**3. Physics is an input feature, not a competitor.**
The full pvlib chain (solar) and turbine power curve (wind) are computed and fed to the model
as features. The task becomes NWP post-processing — learning a correction to physics rather
than a mapping from scratch. The practical consequence is graceful degradation: on a site
unlike anything in training, the model falls back toward physics rather than toward nonsense.
`kt_nwp` and `physics_over_clearsky` are the top two features by gain for solar.

**4. One feature module, shared by training and serving.**
`features/build.py` is imported by both the trainer and the API. Train/serve skew is the
failure mode that silently destroys ML systems — offline scores stay excellent while served
predictions drift — and a single code path is the only real defence. Test T1 asserts both
call sites produce byte-identical matrices.

## Layout

```
src/reip/
  schemas.py          all data contracts; the forecast contract Phase 2 consumes
  sites/              site registry (GEFCom training zones + Gujarat demo sites)
  ingest/             gefcom.py (training corpus), openmeteo.py (serving weather)
  physics/            solar.py, wind.py, clearsky.py, fit_location.py
  features/build.py   THE shared feature path — the skew boundary
  models/             train.py, predict.py, backends.py
  eval/               baselines.py, metrics.py, report.py
  api/main.py         POST /forecast, GET /sites, GET /health
```

## Tests

| | What it protects |
|---|---|
| T1 | **Train/serve skew** — trainer and API produce identical feature matrices |
| T2 | **Leakage** — no feature derives from the target; CV folds are time-ordered |
| T3 | **Physics** — night is zero, power curve respects cut-in/rated/cut-out, density bounded |
| T4 | **Clear-sky consistency** — fitted coordinates reproduce the observed envelope |
| T5 | **Ingest** — de-accumulated irradiance is physical, diurnal cycle survived, UTC, no dupes |
| T6 | **Skill** — the model beats every baseline, and the uncertainty band is calibrated |
| T7 | **API contract** — 72 points, monotone quantiles, response validates against its schema |

T1 and T6 are the blocking pair: T1 protects correctness, T6 encodes "the model is actually
worth having."

## Two problems found and fixed during the build

Both had the same signature — nothing raised, the number just quietly became wrong.

**Accumulated radiation fields.** GEFCom publishes SSRD/STRD/TSR/TP as J/m² accumulated from
the start of each forecast run, resetting at 01:00 UTC. Used raw, they hand the model a
monotonic ramp that correlates with time of day by construction. They are now differenced
within each run and converted to W/m², with the reset detected rather than assumed.

**A falsy-zero default.** The site registry recorded `azimuth_deg: 180.0` for a plant at
latitude −34. A southern-hemisphere array faces *north* — azimuth `0.0` — which is falsy, so
`fitted.azimuth_deg or 180.0` silently turned every southern site around. The modelled
clear-sky reference collapsed to 0.03 MW in winter against 0.46 MW of real output, the
clear-sky index saturated at its cap on 45% of rows, and correlation with the physics prior
fell to −0.05. After the fix: 3.6% at cap, correlation 0.42.

## Known limitations

**Forecast lead time — resolved in Phase 2.** Phase 1 trained on a single nominal 24 h lead,
so `horizon_h` was constant, was dropped as a feature, and the band could not widen with
horizon. The corpus was rebuilt from Open-Meteo Previous Runs at genuine 24/48/72 h leads
(2.53 M solar rows, 2.76 M wind, 151 sites, 16 months). `horizon_h` now survives feature
selection and interval width grows with lead: 0.215 → 0.216 → 0.219 for solar, 0.391 → 0.405
→ 0.427 for wind.

The remaining limitation is *history length*: 16 months rather than three years, because all
three leads at three years costs about two days of API quota. Sixteen months covers a full
seasonal cycle but not interannual variation.

**Domain shift.** Trained on Australian plants with ECMWF fields (2012–2014), served on
Open-Meteo ICON forecasts for Indian sites. Mitigated structurally — dimensionless targets,
source-agnostic physical units, physics as an input — but real. **The reported accuracy is
measured on Australian holdout data and is not a measured Gujarat accuracy.** Closing this
needs measured Gujarat plant data; a `bias_correction` hook is stubbed for it.

**Estimated coordinates.** GEFCom anonymises its sites, so solar coordinates are recovered
from each plant's own output — solar-noon timing for longitude, seasonal day-length swing for
latitude. Recovered day-length curves match to under 0.25 h RMSE across the year, but they
remain estimates.

**No thermodynamic inputs for wind in training.** The GEFCom wind track carries only wind
components, so air density is constant during training and the trainer drops it. At serve
time the density correction is active inside the hub-height wind speed, where it is a
physically-correct refinement rather than a learned effect.

## Deviations from the spec

| Spec (§24) | Built | Why |
|---|---|---|
| XGBoost | **XGBoost** | As specified. LightGBM was benchmarked head to head and is available via `REIP_BACKEND=lightgbm`; see [`reports/backend_comparison.md`](reports/backend_comparison.md). |
| PostgreSQL | Parquet | Phase 1 is a batch training pipeline. `ingest/base.py` defines the repository seam where Postgres drops in when ingestion becomes continuous. |
