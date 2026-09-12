"""Serve the demand model: load artifacts, run the shared feature path, return MW.

The mirror of `models/predict.py`. Same contract, same guards: the feature order stored in
the artifact is asserted here, the quantiles are sorted, and the conformal widening that
training fitted is actually applied - the omission of which was the first bug Phase 2 found.
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
from reip.models.demand.features import build_demand_features
from reip.models.splits import apply_conformal, widening_for
from reip.schemas import QUANTILES

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DemandModel:
    metadata: dict
    models: dict[str, object]

    @property
    def feature_order(self) -> list[str]:
        dropped = set(self.metadata.get("dropped_constant_features", []))
        return [f for f in self.metadata["feature_order"] if f not in dropped]

    def peak_mw(self, region: str) -> float:
        return float(self.metadata["peak_mw"][region])


@lru_cache(maxsize=1)
def load_demand_model(artifacts_dir: Path | None = None) -> DemandModel:
    from reip.models.backends import MODEL_SUFFIX, get_backend

    settings = get_settings()
    artifacts_dir = artifacts_dir or settings.artifacts_dir
    path = artifacts_dir / "demand_metadata.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no demand model at {path}; run `python -m reip.models.demand.train`"
        )

    metadata = json.loads(path.read_text(encoding="utf-8"))
    backend_name = metadata.get("backend", settings.backend)
    backend = get_backend(backend_name)
    suffix = MODEL_SUFFIX[backend_name]
    models = {
        q.value: backend.load(artifacts_dir / f"demand_{q.value}{suffix}") for q in QUANTILES
    }
    return DemandModel(metadata=metadata, models=models)


def predict(
    market: pd.DataFrame,
    weather: pd.DataFrame,
    region: str,
    *,
    horizons: tuple[int, ...] | None = None,
    model: DemandModel | None = None,
) -> pd.DataFrame:
    """Demand p10/p50/p90 in MW for one region, one row per (valid_time, horizon)."""
    model = model or load_demand_model()
    frame = build_demand_features(
        market, weather, region, **({"horizons": horizons} if horizons else {})
    )

    # Region one-hots and the peak scale are added by the trainer, not the feature builder,
    # so they are reconstructed here. Any mismatch is caught by the assertion below.
    for known in model.metadata["regions"]:
        frame[f"region_{known}"] = 1.0 if known == region else 0.0
    peak = model.peak_mw(region)
    frame["region_peak_mw"] = peak

    available = set(frame.columns)
    missing = [f for f in model.feature_order if f not in available]
    if missing:
        raise ValueError(
            f"demand feature builder produced no {missing}; the artifact was trained "
            "against a different feature set (train/serve skew)"
        )

    complete = frame[model.feature_order].notna().all(axis=1)
    frame = frame[complete]
    X = frame[model.feature_order]

    raw = np.sort(
        np.column_stack(
            [np.asarray(model.models[q.value].predict(X), dtype="float64") for q in QUANTILES]
        ),
        axis=1,
    )
    horizon_values = frame["horizon_h"].to_numpy(dtype="int32")
    widening = widening_for(model.metadata.get("conformal_widening", 0.0), horizon_values)
    lower, upper = apply_conformal(raw[:, 0], raw[:, 2], widening, floor=-np.inf)
    raw[:, 0] = np.minimum(lower, raw[:, 1])
    raw[:, 2] = np.maximum(upper, raw[:, 1])

    return pd.DataFrame(
        {
            "valid_time_utc": frame["__valid_time"].to_numpy(),
            "horizon_h": horizon_values,
            "region": region,
            "p10_mw": raw[:, 0] * peak,
            "p50_mw": raw[:, 1] * peak,
            "p90_mw": raw[:, 2] * peak,
            "actual_mw": frame["__target"].to_numpy(dtype="float64"),
        }
    )


def holdout_predictions(region: str, *, fraction: float | None = None) -> pd.DataFrame:
    """Demand predictions over the final block of the timeline, for residual building.

    Uses the same tail fraction as the trainer's test split, so these are predictions on
    data the trees never saw.
    """
    from reip.models.demand.train import TEST_FRACTION
    from reip.models.demand.weather import load as load_weather

    settings = get_settings()
    market = pd.read_parquet(settings.data_canonical / "aemo_market.parquet")
    frame = predict(market, load_weather(), region, horizons=(24,))

    fraction = fraction if fraction is not None else TEST_FRACTION
    times = pd.DatetimeIndex(frame["valid_time_utc"])
    cutoff = times.max() - (times.max() - times.min()) * fraction
    return frame[times > cutoff].reset_index(drop=True)
