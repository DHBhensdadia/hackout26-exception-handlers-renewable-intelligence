# Forecast benchmark

Phase 1 core model: 24-72 hour solar and wind power forecasting.

Every number below is computed on a **contiguous final time block that no model or
baseline saw during fitting**. Splits are never shuffled: weather is strongly
autocorrelated hour to hour, so a random split lets a model see the afternoon while
predicting the morning and reports an error far below anything achievable in operation.

Errors are normalised by **installed capacity**, not by mean output. Normalising by the
mean flatters solar heavily, because half the rows are night.

The headline is **skill against smart persistence** - holding the clear-sky index constant
from issue time. Plain persistence is easy to beat and proves nothing; smart persistence
already reproduces the entire diurnal and seasonal shape, so beating it is the claim worth
making. **Physics only** matters equally here: the model receives the physical estimate as
an input feature, so that column measures exactly what the learned correction adds.

## Solar

Trained on 188,997 rows from 9 sites
(2025-09-01 to 2026-08-31),
evaluated on 47,250 untouched holdout rows from
2026-06-19 onward. Horizons present in this data: 24-72 h.

### Overall, holdout

| Method | nMAE %cap | nRMSE %cap | Bias %cap | R2 | Skill vs smart persistence % |
|---|---:|---:|---:|---:|---:|
| **Model (quantile GBDT)** | 6.92 | 14.80 | 1.39 | 0.75 | 9.81 |
| Persistence | 7.68 | 17.00 | 0.40 | 0.61 | 0.00 |
| Smart persistence | 7.68 | 17.00 | 0.40 | 0.61 | 0.00 |
| Climatology | 18.81 | 24.09 | -0.67 | 0.17 | -144.94 |
| Physics only (no ML) | 13.72 | 25.69 | -9.55 | 0.02 | -78.70 |

Mean pinball loss on the dimensionless target: **0.0204**
(p10 0.0148, p50 0.0346, p90 0.0118).

Prediction interval coverage (p10-p90): **86.9%**
against a nominal 80%, with a mean width of 19.8% of capacity.

### By lead time

| Lead | n | Model nMAE | Persistence | Smart persist. | Climatology | Physics only | Skill % | PICP % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-24h | 15750 | 6.93 | 6.92 | 6.92 | 18.81 | 13.63 | -0.07 | 86.98 |
| 25-48h | 15750 | 6.92 | 8.08 | 8.08 | 18.81 | 13.79 | 14.44 | 86.91 |
| 49-72h | 15750 | 6.93 | 8.03 | 8.03 | 18.81 | 13.74 | 13.68 | 86.91 |
| all | 47250 | 6.92 | 7.68 | 7.68 | 18.81 | 13.72 | 9.81 | 86.94 |

Top features by gain: ghi_wm2_lead3, site_latitude, site_tilt, doy_sin, site_capacity_mw, ghi_wm2_lead2, solar_zenith, cloud_total_roll_mean.

## Wind

Trained on 251,994 rows from 12 sites
(2025-09-01 to 2026-08-31),
evaluated on 63,000 untouched holdout rows from
2026-06-19 onward. Horizons present in this data: 24-72 h.

### Overall, holdout

| Method | nMAE %cap | nRMSE %cap | Bias %cap | R2 | Skill vs smart persistence % |
|---|---:|---:|---:|---:|---:|
| **Model (quantile GBDT)** | 12.12 | 17.14 | 4.53 | 0.68 | 56.97 |
| Persistence | 28.17 | 37.80 | -1.28 | -0.61 | 0.00 |
| Smart persistence | 28.17 | 37.80 | -1.28 | -0.61 | 0.00 |
| Climatology | 25.92 | 31.21 | -3.86 | -0.11 | 7.98 |
| Physics only (no ML) | 13.74 | 21.35 | 6.38 | 0.54 | 51.24 |

Mean pinball loss on the dimensionless target: **0.0383**
(p10 0.0268, p50 0.0606, p90 0.0275).

Prediction interval coverage (p10-p90): **71.8%**
against a nominal 80%, with a mean width of 35.9% of capacity.

### By lead time

| Lead | n | Model nMAE | Persistence | Smart persist. | Climatology | Physics only | Skill % | PICP % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-24h | 21000 | 12.09 | 22.38 | 22.38 | 25.92 | 13.09 | 45.98 | 71.85 |
| 25-48h | 21000 | 12.12 | 29.08 | 29.08 | 25.92 | 13.68 | 58.31 | 71.79 |
| 49-72h | 21000 | 12.15 | 33.05 | 33.05 | 25.92 | 14.44 | 63.23 | 71.69 |
| all | 63000 | 12.12 | 28.17 | 28.17 | 25.92 | 13.74 | 56.97 | 71.77 |

Top features by gain: ws_corrected, ws_corrected_roll_mean, wind_speed_100m_roll_mean, wind_speed_100m, ws_corrected_lead2, site_capacity_mw, ws_corrected_lead1, ws_corrected_lead3.

## Forecast lead time: what is and is not measured

GEFCom2014 supplies a single day-ahead forecast run per day, so the horizons genuinely
present in this data are 1-24 h. It cannot, on its own, evidence skill at 48 or 72 h.

This is handled deliberately rather than papered over. The GBDT learns power = f(weather),
which is horizon-agnostic: what degrades with lead time is the *accuracy of the weather
input*, not the weather-to-power mapping. Lead-dependent behaviour is therefore supplied
separately, by calibrating how NWP error grows from lead 1 to lead 3 against Open-Meteo
Previous Runs, and widening the predictive interval accordingly. The evaluation report
states which numbers are measured on GEFCom holdout and which come from that calibration.

## Known limitations

**Domain shift.** The models are trained on GEFCom2014 - Australian plants, ECMWF forecast
fields, 2012-2014 - and served on Open-Meteo ICON forecasts for Indian sites. The design
mitigates this deliberately rather than ignoring it: targets are dimensionless, features
are expressed in source-agnostic physical units, and the physical estimate is an input, so
the model degrades toward physics rather than toward nonsense when it meets conditions
unlike its training set. It is still a real gap, and it is the first thing Phase 2 closes
once measured Gujarat plant data is available. The reported accuracy is measured on
Australian holdout data and should not be read as a measured Gujarat accuracy.

**Estimated coordinates.** GEFCom2014 anonymises its sites, so the solar clear-sky
reference relies on coordinates recovered from each plant's own generation record - solar
noon timing for longitude, the seasonal day-length swing for latitude. The recovered
day-length curves match to under 0.25 h RMSE across the year, but they remain estimates.

**Wind has no thermodynamic inputs in training.** The GEFCom wind track supplies only wind
components, so air density is constant throughout training and the trainer drops it. At
serve time the density correction is active, applied inside the hub-height wind speed,
where it is a physically-correct refinement rather than a learned effect.

![Error by lead time](figures/skill_by_lead.png)
