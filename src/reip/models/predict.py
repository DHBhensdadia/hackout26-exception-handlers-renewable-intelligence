"""Prediction: load artifacts, run the shared feature path, convert back to megawatts.

Denormalisation is the mirror of `build_target`, and it has to be exact. The model emits a
dimensionless number - a clear-sky index for solar, a capacity factor for wind - and this
module multiplies it by the same reference the target was divided by during training. Any
discrepancy between those two quantities becomes a systematic bias in every forecast
served, with nothing raising an error.

Three guards are applied after denormalisation, in order:

1. **Feature-order assertion.** The ordered feature list is stored in the artifact metadata
   and checked here. Trees index features positionally, so a reordered column would score
   silently against the wrong variable.
2. **Quantile sorting.** The three quantile models are fitted independently and nothing
   couples them, so p10 can cross above p50 in sparse regions. Sorting each row restores
   monotonicity.
3. **Physical clamping.** Output is bounded to [0, capacity], and forced to exactly zero
   for solar when the clear-sky reference says the sun is down.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.features.build import NIGHT_CLEARSKY_FLOOR_MW, build_features
from reip.physics.clearsky import PvlibClearSky
from reip.physics.solar import solar_physics_frame
from reip.physics.wind import wind_physics_frame
from reip.schemas import (
    CLEARSKY_INDEX_MAX,
    QUANTILES,
    ForecastPoint,
    SiteForecast,
    SiteMeta,
    Tech,
)

log = logging.getLogger(__name__)


class ArtifactMissing(FileNotFoundError):
    """Raised when a technology has no trained model on disk."""


@dataclass(frozen=True)
class LoadedModel:
    """The three quantile boosters for one technology, plus their training metadata."""

    tech: Tech
    metadata: dict
    models: dict[str, object]

    @property
    def feature_order(self) -> list[str]:
        """Features the artifact was fitted on, excluding those dropped as constant."""
        dropped = set(self.metadata.get("dropped_constant_features", []))
        return [f for f in self.metadata["feature_order"] if f not in dropped]

    @property
    def version(self) -> str:
        return str(self.metadata.get("model_version", "unknown"))


@lru_cache(maxsize=4)
def load_model(tech: Tech, artifacts_dir: Path | None = None) -> LoadedModel:
    """Load and cache the quantile models for a technology."""
    from reip.models.backends import MODEL_SUFFIX, get_backend

    settings = get_settings()
    artifacts_dir = artifacts_dir or settings.artifacts_dir
    meta_path = artifacts_dir / f"{tech.value}_metadata.json"
    if not meta_path.exists():
        raise ArtifactMissing(
            f"no trained {tech.value} model at {meta_path}; run `python -m reip.models.train`"
        )

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    backend = get_backend(metadata.get("backend", settings.backend))
    suffix = MODEL_SUFFIX[metadata.get("backend", settings.backend)]

    models = {
        quantile.value: backend.load(artifacts_dir / f"{tech.value}_{quantile.value}{suffix}")
        for quantile in QUANTILES
    }
    return LoadedModel(tech=tech, metadata=metadata, models=models)


def _align_features(features: pd.DataFrame, expected: list[str], tech: Tech) -> pd.DataFrame:
    """Reorder to the artifact's feature list, asserting nothing required is absent."""
    missing = [f for f in expected if f not in features.columns]
    if missing:
        raise ValueError(
            f"{tech.value}: feature builder produced no {missing}; the artifact was trained "
            f"against a different feature set (train/serve skew)"
        )
    return features[expected]


def reference_series(
    features: pd.DataFrame, site: SiteMeta, weather: pd.DataFrame
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Denormalisation reference, physics-only estimate, and clear-sky ceiling, in MW.

    Three quantities, and they are no longer the same thing. The *denominator* must match
    whatever `build_target` divided by - installed capacity under the capacity-factor
    target - while the *clear-sky ceiling* remains the physical maximum the sun allows.
    Conflating them made `/forecast` report a 50 MW clear-sky value at midnight and, worse,
    disabled the night clamp, which keys off the sun being down rather than off the
    normalisation happening to be small.
    """
    times = pd.DatetimeIndex(features.index)

    if site.tech is Tech.WIND:
        physics = wind_physics_frame(
            times,
            site,
            ws_10m=pd.Series(weather["wind_speed_10m"].to_numpy(dtype="float64"), index=times),
            ws_100m=pd.Series(weather["wind_speed_100m"].to_numpy(dtype="float64"), index=times),
            temp_c=pd.Series(
                np.nan_to_num(weather["temp_2m_c"].to_numpy(dtype="float64"), nan=15.0), index=times
            ),
            pressure_hpa=pd.Series(
                np.nan_to_num(weather["pressure_hpa"].to_numpy(dtype="float64"), nan=1013.25),
                index=times,
            ),
        )
        denominator = pd.Series(site.capacity_mw, index=times)
        # Wind has no clear-sky analogue; the physical ceiling is the nameplate.
        return denominator, physics["cf_powercurve"] * site.capacity_mw, denominator

    use_capacity = get_settings().solar_target == "capacity_factor"
    solar = solar_physics_frame(
        times,
        site,
        ghi=pd.Series(weather["ghi_wm2"].to_numpy(dtype="float64"), index=times),
        temp_air=pd.Series(weather["temp_2m_c"].to_numpy(dtype="float64"), index=times),
        wind_speed=pd.Series(weather["wind_speed_10m"].to_numpy(dtype="float64"), index=times),
        dni=pd.Series(weather["dni_wm2"].to_numpy(dtype="float64"), index=times),
        dhi=pd.Series(weather["dhi_wm2"].to_numpy(dtype="float64"), index=times),
    )
    # Must mirror `build_target` exactly: any divergence here is a systematic bias on
    # every served forecast, with nothing raising.
    clearsky = PvlibClearSky()(times, site)
    denominator = pd.Series(site.capacity_mw, index=times) if use_capacity else clearsky
    return denominator, solar["physics_ac_mw"], clearsky


def predict_frame(
    weather: pd.DataFrame, site: SiteMeta, *, model: LoadedModel | None = None
) -> pd.DataFrame:
    """Predict p10/p50/p90 in MW for a canonical weather frame.

    Returns one row per forecast hour with the quantiles, the clear-sky reference and the
    physics-only estimate, so a consumer can see the prediction against what physics alone
    expected.
    """
    model = model or load_model(site.tech)

    features = build_features(weather, site)
    aligned = _align_features(features, model.feature_order, site.tech)
    denominator, physics_mw, clearsky_mw = reference_series(
        features, site, weather.sort_values("valid_time_utc")
    )

    raw = np.column_stack(
        [np.asarray(model.models[q.value].predict(aligned), dtype="float64") for q in QUANTILES]
    )
    # Independently-fitted quantiles can cross; sorting each row restores monotonicity
    # without distorting the median.
    raw = np.sort(raw, axis=1)

    power = raw * denominator.to_numpy(dtype="float64")[:, None]
    power = np.clip(power, 0.0, site.capacity_mw)

    if site.tech is Tech.SOLAR:
        clearsky = clearsky_mw.to_numpy(dtype="float64")

        # Cap at the physical ceiling. Under the clear-sky-index target this held by
        # construction - the model predicted a fraction of clear-sky and could not exceed
        # it. The capacity-factor target removed that guarantee, and the model duly began
        # predicting several times the available sunlight in twilight hours, where
        # capacity factor is small but clear-sky output is smaller still.
        #
        # The bound is CLEARSKY_INDEX_MAX rather than 1.0 because cloud enhancement is
        # real: bright cloud edges can briefly push a panel above its clear-sky value.
        power = np.minimum(power, (CLEARSKY_INDEX_MAX * clearsky)[:, None])

        # A PV plant produces nothing at night. No amount of learned correction should be
        # able to say otherwise, so this is enforced rather than hoped for. Keyed off the
        # clear-sky curve, never the denominator: under the capacity-factor target the
        # denominator is a constant and would never trip this.
        night = clearsky < NIGHT_CLEARSKY_FLOOR_MW
        power[night, :] = 0.0

    ordered = weather.sort_values("valid_time_utc").reset_index(drop=True)
    return pd.DataFrame(
        {
            "valid_time_utc": pd.DatetimeIndex(features.index),
            "horizon_h": ordered["horizon_h"].to_numpy(dtype="int16"),
            "p10_mw": power[:, 0],
            "p50_mw": power[:, 1],
            "p90_mw": power[:, 2],
            "clearsky_mw": np.clip(clearsky_mw.to_numpy(dtype="float64"), 0.0, site.capacity_mw),
            "physics_mw": np.clip(physics_mw.to_numpy(dtype="float64"), 0.0, site.capacity_mw),
        }
    )


def predict_site(
    weather: pd.DataFrame, site: SiteMeta, *, issue_time: pd.Timestamp | None = None
) -> SiteForecast:
    """Full `SiteForecast` for one site - the object the API returns and Phase 2 consumes."""
    model = load_model(site.tech)
    frame = predict_frame(weather, site, model=model)

    issue_time = issue_time or pd.Timestamp(weather["issue_time_utc"].iloc[0])
    source = str(weather["source"].iloc[0]) if "source" in weather else "unknown"

    points = [
        ForecastPoint(
            valid_time_utc=row.valid_time_utc.to_pydatetime(),
            horizon_h=int(row.horizon_h),
            p10_mw=round(float(row.p10_mw), 4),
            p50_mw=round(float(row.p50_mw), 4),
            p90_mw=round(float(row.p90_mw), 4),
            clearsky_mw=round(float(row.clearsky_mw), 4),
            physics_mw=round(float(row.physics_mw), 4),
        )
        for row in frame.itertuples()
    ]

    return SiteForecast(
        site_id=site.site_id,
        tech=site.tech,
        issue_time_utc=issue_time.to_pydatetime(),
        capacity_mw=site.capacity_mw,
        model_version=model.version,
        weather_source=source,
        location_is_estimated=site.location_is_estimated,
        points=points,
    )
