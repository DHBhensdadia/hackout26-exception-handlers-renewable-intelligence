# API contract

**For the frontend team.** Everything here is the shape the backend emits today, or the
shape it will emit when a marked endpoint lands. Example payloads under
[`docs/fixtures/`](fixtures/) are **generated from real model runs**, not written by hand,
so they can be used as mocks directly.

| | |
|---|---|
| Base URL (local) | `http://localhost:8000` |
| Content type | `application/json` |
| Timestamps | ISO-8601, UTC, always `Z`-suffixed: `2026-08-10T18:00:00Z` |
| Power | Megawatts (MW), float |
| Energy | Megawatt-hours (MWh), float |
| Probabilities | Float in `[0, 1]`, never percentages |
| Model version | `xgb-q-0.1.0` — echoed in every response |

---

## The one rule that will bite

> **Never add up `p10_mw` across sites to get a regional figure. Use `POST /balance`.**

`/forecast` returns per-site quantiles. A p10 is the level a single plant exceeds 90% of
the time. Summing those across 26 plants implicitly assumes every plant has a bad hour
*simultaneously*, which measurement says does not happen — mean pairwise correlation
between plants in a region is about +0.12 to +0.23, not 1.

Measured against real outcomes, the naive sum produces a band covering 99–100% of hours
against a nominal 80%, at up to 3.5× the width it needs. A dashboard built that way shows a
grid that looks far less reliable than it is, and an operator sizing reserve from that lower
bound would procure for a shortfall the fleet does not have.

`/balance` does the aggregation correctly, from 200 coherent scenarios. The same applies to
`p90` and to demand.

---

## Status of each endpoint

| Endpoint | Status | Notes |
|---|---|---|
| `POST /forecast` | **Live** | Unchanged from Phase 1 |
| `GET /sites` | **Live** | |
| `GET /health` | **Live** | Being extended, additively |
| `GET /regions` | **Live** | Includes `balance_available` per region |
| `POST /balance` | **Live** | Serves a precomputed replay window; see `data_mode` |
| `POST /storage/dispatch` | **Live** | Solved per request; battery size is interactive |
| `GET /demand/{region}` | **Live** | From the balance ensemble, so the two agree |
| `GET /seasonal/{region}` | **Live** | Measured history, not a forecast |
| `GET /vss` | **Live** | What the uncertainty modelling is worth, in AUD/yr |
| `GET /alerts` | **Planned** | May be cut; `/balance` carries the same information |

"Ready" means the computation and the payload are finished and verified; wiring the HTTP
route is mechanical. Build against those now.

---

## `POST /forecast`

One site, 1–72 hours. Works for a latitude/longitude with no generation history — that is
the cold-start path, and it is the main demonstration.

**Request** — either `site_id`, or all of `latitude`/`longitude`/`tech`/`capacity_mw`:

```json
{
  "site_id": "GJ-SOLAR-CHARANKA",
  "horizon_h": 72
}
```

```json
{
  "latitude": 23.03, "longitude": 72.57,
  "tech": "solar", "capacity_mw": 50.0,
  "horizon_h": 72,
  "tilt_deg": 23.0, "azimuth_deg": 180.0
}
```

`tech` is `"solar"` or `"wind"`. `hub_height_m` applies to wind only; `tilt_deg` and
`azimuth_deg` to solar only. Extra fields are rejected with 422.

**Response** — see [`fixtures/forecast.json`](fixtures/forecast.json):

```json
{
  "site_id": "GJ-SOLAR-CHARANKA",
  "tech": "solar",
  "issue_time_utc": "2026-09-13T00:00:00Z",
  "capacity_mw": 730.0,
  "model_version": "xgb-q-0.1.0",
  "weather_source": "openmeteo:icon_seamless",
  "location_is_estimated": false,
  "points": [
    {
      "valid_time_utc": "2026-09-13T01:00:00Z",
      "horizon_h": 1,
      "p10_mw": 0.0, "p50_mw": 0.0, "p90_mw": 0.0,
      "clearsky_mw": 0.0, "physics_mw": 0.0
    }
  ]
}
```

| Field | Meaning | UI use |
|---|---|---|
| `p50_mw` | Median. Half of outcomes fall below | The line |
| `p10_mw` / `p90_mw` | 80% interval | The shaded band |
| `clearsky_mw` | Theoretical maximum this hour, sun geometry only | Ghost line: "what a cloudless day would give". Always 0 at night. Wind returns nameplate |
| `physics_mw` | What physics alone predicts, before the learned correction | Optional diagnostic. Do not show by default |
| `location_is_estimated` | Coordinates were fitted, not known | Show a caveat marker if true |

**Guarantees:** `p10_mw ≤ p50_mw ≤ p90_mw` for every point, enforced server-side.
`horizon_h` is strictly increasing and contiguous. Solar is exactly `0.0` at night.
The interval is conformally calibrated — measured coverage on plants held out of training
entirely is 82.7% (solar) and 78.9% (wind) against a nominal 80%.

**Band width is driven mainly by conditions, not by lead time.** This is worth knowing
before you design around it. A settled overcast day forecasts tightly; a broken-cloud day
does not, and the band can differ threefold between two hours at the same lead. Lead time
does widen it — measured at +1.8% from the 1–24 h bucket to the 49–72 h bucket — but that
effect is small next to the weather, so **on any single forecast you should not expect the
band to grow smoothly left to right**, and a design that assumes a widening cone will look
broken against real data.

Treat width as information in its own right: a narrow band at hour 60 means a genuinely
predictable period, not a bug.

---

## `GET /regions`

Static reference data. Safe to fetch once and cache for the session.
See [`fixtures/regions.json`](fixtures/regions.json).

```json
{
  "model_version": "xgb-q-0.1.0",
  "regions": [
    {
      "region": "SA1",
      "technologies": {
        "solar": {"sites": 9, "capacity_mw": 828.5},
        "wind": {"sites": 26, "capacity_mw": 2494.2}
      },
      "total_capacity_mw": 3322.7
    }
  ]
}
```

Region codes are the five NEM regions: `NSW1`, `QLD1`, `SA1`, `TAS1`, `VIC1`. Treat them as
opaque strings. **`SA1` is the demo region** — the highest-renewable-penetration grid in
the world, and the only one where surplus actually occurs. `NSW1` never reaches surplus at
current penetration, so a surplus panel there will correctly always read zero.

---

## `POST /balance`

The decision endpoint. Regional generation against regional demand, hour by hour, as
probabilities. See [`fixtures/balance.json`](fixtures/balance.json).

**Request:**

```json
{"region": "SA1", "horizon_h": 72}
```

### Read `data_mode` before you label anything

The response carries `data_mode`, and today it is `"replay"`.

The demand model needs load at the issue time and at 24 and 168 hours before it, and the
AEMO market ingest currently ends before the present. So the served window is a **real
72-hour window replayed from held-out history** — real forecasts as they stood at that
issue time, against real metered demand. Every number in it happened; none of it is a
forecast for tonight.

Show `issue_time_utc` and say "replay" wherever this data appears. When the ingest runs to
the present, `data_mode` becomes `"live"` and nothing else about the payload changes.

Because it *is* history, the payload also carries `actual[]` — what really happened, hour
by hour. That lets a panel show whether the band contained the outcome, which is the one
thing a live forecast can never show.

| Field | Meaning |
|---|---|
| `data_mode` | `"replay"` or `"live"`. Never present a replay as a forecast |
| `data_note` | Human-readable explanation, safe to show verbatim |
| `actual[]` | `{valid_time_utc, renewable_mw, demand_mw, residual_mw}` — outcome, replay only |
| `horizon_h` | Echo of the request; `points` and `actual` are trimmed to it |

**Response:**

```json
{
  "region": "SA1",
  "issue_time_utc": "2026-08-10T18:00:00Z",
  "model_version": "xgb-q-0.1.0",
  "n_scenarios": 200,
  "dispatchable_headroom_mw": 1610.3,
  "technologies": ["solar", "wind"],
  "points": [
    {
      "valid_time_utc": "2026-08-10T18:00:00Z",
      "horizon_h": 1,
      "region": "SA1",
      "demand_p50_mw": 1404.85,
      "renewable_p10_mw": 578.51,
      "renewable_p50_mw": 1151.0,
      "renewable_p90_mw": 1555.65,
      "residual_p10_mw": -166.96,
      "residual_p50_mw": 234.59,
      "residual_p90_mw": 788.65,
      "p_surplus": 0.0627,
      "p_shortage": 0.0,
      "expected_surplus_mw": 9.45,
      "expected_shortage_mw": 0.0,
      "conditional_surplus_mw": 150.74,
      "conditional_shortage_mw": 0.0,
      "expected_surplus_mwh": 9.45,
      "expected_shortage_mwh": 0.0,
      "recommended_action": "normal"
    }
  ],
  "events": [
    {
      "kind": "surplus",
      "from_utc": "2026-08-11T01:00:00Z",
      "to_utc": "2026-08-11T06:00:00Z",
      "hours": 6,
      "peak_probability": 1.0,
      "energy_mwh": 1977.1
    }
  ]
}
```

### Field semantics

`residual_load = demand − renewable generation`. **Negative residual is surplus.** This
catches people out: the more renewable output, the *lower* this number goes, and the
interesting hours are the ones below zero.

| Field | Meaning |
|---|---|
| `renewable_p10/p50/p90_mw` | Regional total, correctly aggregated. Not a sum of site quantiles |
| `residual_p10/p50/p90_mw` | Demand minus generation. Can be negative |
| `p_surplus` | Probability generation exceeds demand |
| `p_shortage` | Probability the gap exceeds what dispatchable plant can cover |
| `expected_surplus_mw` | **Unconditional** mean: probability-weighted, zero where it does not occur |
| `conditional_surplus_mw` | How big the surplus is **if it happens**. This is the "how much" number |
| `expected_*_mwh` | Same number — hourly resolution means MW averaged over an hour is MWh. Safe to sum across hours for a period total |
| `dispatchable_headroom_mw` | Measured non-renewable capacity available. The shortage threshold |

**`expected_surplus_mw` is not "how big the surplus will be".** It is the average across all
200 scenarios, counting zero where no surplus occurs. A 5%-likely 900 MW surplus reports as
45 MW. That makes it additive into energy, and it is the right number to sum — but label it
"expected", never "forecast surplus".

To show the size of a surplus *if it happens*, use `conditional_surplus_mw`. The two are
related by `expected = probability × conditional`, and that identity holds in every
payload — a 6.27% chance of a 151 MW surplus reports as 9.45 MWh expected. Probabilities
carry four decimals for exactly this reason: rounded to two, the identity visibly fails
on small probabilities even though it holds in the values behind them.

`p_surplus` and `p_shortage` are **not complementary** and do not sum to 1. Most hours are
neither.

### `recommended_action`

One of five values, derived from the probabilities. The thresholds are published here so
your colour scale and our logic cannot drift apart:

| Value | Condition | Suggested treatment |
|---|---|---|
| `cover_shortage` | `p_shortage ≥ 0.5` | Critical — red |
| `hold_reserve` | `p_shortage ≥ 0.2` | Warning — amber |
| `absorb_surplus` | `p_surplus ≥ 0.5` | Opportunity — blue |
| `prepare_to_absorb` | `p_surplus ≥ 0.2` | Info — light blue |
| `normal` | otherwise | Neutral — grey |

Shortage is checked before surplus: an hour that is somehow both is a shortage hour.
Treat this as a closed enum but **fail soft** — render an unknown value as `normal` rather
than crashing, so adding a sixth action later is not a breaking change.

### `events`

Contiguous runs of 2+ hours above 50% probability. This is what makes a balance
actionable: one hour of surplus is absorbed by any battery, six consecutive hours is a
storage-sizing question. `energy_mwh` is the total expected energy over the run.

Single-hour blips are deliberately excluded — in a 200-scenario ensemble they are noise.

### How reliable are these probabilities?

Verified against actual outcomes on data the calibration never saw:

| | Base rate | Brier | vs climatology |
|---|---:|---:|---:|
| SA1 surplus | 18.5% | 0.0568 | **+62.3%** |
| SA1 shortage | 7.6% | 0.0174 | **+75.3%** |
| NSW1 shortage | 3.6% | 0.0119 | **+65.8%** |

Reliability tracks the diagonal where there is data — where the platform said 0.94, shortage
occurred 93% of the time across 115 hours. These are honest probabilities and can be
displayed as percentages without hedging.

---

## `GET /health`

See [`fixtures/health.json`](fixtures/health.json).

```json
{
  "status": "ok",
  "model_version": "xgb-q-0.1.0",
  "models_loaded": {"solar": true, "wind": true, "demand": true},
  "sites_registered": 172,
  "regions_available": ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"],
  "weather_source": "icon_seamless",
  "scenario_dispersion": {"solar": 1.0, "wind": 2.5}
}
```

Poll for a status banner. `status` is `"ok"` or `"degraded"`. If a technology shows
`false` in `models_loaded`, `/balance` for a region depending on it will fail — check this
before rendering a region selector.

---

## `GET /seasonal/{region}` — live

Recurring patterns mined from three years of measured history. **`data_mode` is
`"measured"`, not `"replay"`** — no model output is involved at all. A recurring pattern is a
property of the record, and a forecast in front of it would only add error.

```json
{
  "region": "SA1",
  "timezone": "Australia/Adelaide",
  "years_of_history": 3.0,
  "data_mode": "measured",
  "grids": { "surplus_mw": [[...24 hours...], ...12 months...], "renewable_share": [...], "price_aud_mwh": [...] },
  "by_month": [{ "month": 10, "surplus_mwh_per_year": 227391, "negative_price_hours_per_year": 302, "renewable_share": 0.93 }],
  "peak_surplus_month": 10,
  "droughts": { "per_year": 3.3, "days_per_year": 8.0, "duration_quantiles": {"p50": 2.0, "max": 3}, "longest": {...} },
  "storage": { "total_surplus_mwh_per_year": 1656102, "curve": [...], "targets": {"50pct": {...}, "80pct": {...}} }
}
```

**`grids` are 12 × 24** — months down, local hours across. This is the shape a duck curve is
actually visible in: a horizontal band is a diurnal pattern, a vertical one is seasonal.
Render as a heat grid. Cells may be `null`.

**Hours are local to the region**, not UTC, because the evening peak is at dinner time and
the solar trough is at local noon.

**`renewable_share` can exceed 1.0** and legitimately reaches 3.5 at SA1 midday in spring —
renewables producing three and a half times operational demand. It is an energy ratio
(summed renewable over summed demand), never a mean of hourly ratios: SA1 demand goes
negative 257 hours a year, and averaging ratios across a near-zero denominator produced a
"mean share" of 1590% before this was fixed.

**`droughts` are counted in days, not hours.** Scored hourly, a solar region is in drought
every night by definition. `storage.curve` is a sizing curve — absorbing half the surplus is
cheap, the last few percent costs several times more, and `targets` is where the knee is read
off.

---

## `GET /demand/{region}` — live

Regional demand p10/p50/p90 over the same window as `/balance`, taken from the same
ensemble so the two cannot disagree. Carries `actual_mw` for the replay window.

---

## `GET /vss` — live

An array, one entry per region. The headline: `vss_aud_per_year` is what planning against
the scenario ensemble is worth against planning on the median forecast.

Regions where it is **zero are returned, not filtered**. NSW1 is zero correctly — 10 GW of
dispatchable headroom against 1.7 GW of import capacity means nothing is ever scarce.
Showing that beside SA1's 170,422 AUD/yr is more convincing than showing only the win.
`windows_with_positive_vss` says how rare it is: 1 of 12 for SA1.

---

## `POST /storage/dispatch` — live

```json
{
  "region": "SA1",
  "horizon_h": 72,
  "storage": {
    "energy_mwh": 200.0,
    "power_mw": 100.0,
    "efficiency": 0.88,
    "initial_soc": 0.5
  }
}
```

Solved per request — the LP stays linear, so battery size and power are genuinely
interactive rather than fixed at precompute time.

Returns `schedule[]` (`charge`, `discharge`, `dispatchable`, `grid_import`, `grid_export`,
`curtail`, `unserved`, `energy`, `soc_fraction`, `net_battery_mw`), `committed`, and
`expected_cost_aud`.

**`committed` is hour 1 and is different in kind from the rest.** It is a firm decision taken
before anyone knows which future arrives, identical across every scenario. Hours 2 onward are
recourse and will be re-optimised as forecasts update. Make that visible — render hour 1
solid and the remainder hatched or reduced in opacity, and the two-stage nature of the
optimisation explains itself.

Guaranteed: no hour both charges and discharges, state of charge stays within bounds and
ends at the terminal level, and a larger battery never costs more.

---

## Errors

Standard FastAPI shape:

```json
{"detail": "unknown site_id 'XYZ'; known: [...]"}
```

| Code | Cause |
|---|---|
| 400 | Bad request the validator could not catch (unknown region, unservable site) |
| 422 | Validation failure — missing required field, out-of-range value, unexpected extra field |
| 503 | Model artifacts or upstream weather unavailable |

Messages are written for developers and name the offending value. They are safe to log,
**not** safe to show users verbatim.

---

## Stability contract

**Frozen for Phase 2** — these will not change shape or meaning:

- `/forecast`: every field of `SiteForecast` and `ForecastPoint`
- `/regions`: the whole payload
- `/balance`: `region`, `points[]` field names, units and semantics; `events[]`, including
  the `expected = probability × conditional` identity
- `recommended_action` values and their thresholds
- Units throughout: MW, MWh, probabilities in `[0, 1]`, UTC ISO-8601 with `Z`

**May change:** `/storage/dispatch` entirely; `/alerts` may not ship; additional fields may
be **added** to any response.

**Write clients to ignore unknown fields.** New fields are not a breaking change and will
be added without notice.

**What will not appear in Phase 2:** equipment reliability and failure risk (no public
failure records exist — deferred deliberately, see the design doc), seasonal pattern
analysis (cut for time), and investment or ROI analysis (Phase 3).

---

## Working before the backend is wired

`/regions`, `/balance` and `/health` are computed and verified; only the HTTP routes are
outstanding. The fixtures in [`docs/fixtures/`](fixtures/) are real payloads from real runs
— mock against them directly and the shapes will match.

Two things worth building early, because they are where this platform differs from a
forecast dashboard:

1. **The uncertainty band as a first-class object**, not decoration. `p10`/`p90` is the
   product. A design that shows only `p50` discards what the whole system was built for.
2. **Probability-led framing.** "72% chance of surplus, 14:00–20:00, ~2,072 MWh" is the
   sentence; the chart supports it. Not the other way round.
