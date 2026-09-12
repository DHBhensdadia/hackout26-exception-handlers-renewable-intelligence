"""Train the regional demand model.

Architecture deliberately mirrors the generation trainer: quantile XGBoost through the same
`ModelBackend` protocol, three quantiles, conformal calibration per lead bucket, contiguous
time splits. Reusing the shape means the two models fail in the same recognisable ways and
the same tests apply to both.

Two things differ, and both are consequences of demand being a different kind of quantity.

**Pooled across regions, with region identity as a feature.** The generation model pools
across sites and is scored on sites it has never seen, because `/forecast` takes an
arbitrary latitude and longitude and Charanka has no history. There is no equivalent
question for demand: the NEM has five regions, all five are in the training data, and no
sixth is coming. Region one-hots are therefore legitimate here where site one-hots would
have been a leak of exactly the generalisation being claimed.

**Split on time only.** For the same reason there is no site-disjoint holdout: holding out
Tasmania to score Tasmania is not a meaningful test, because regional load curves are not
exchangeable - Tasmania is hydro-backed and industrially dominated and looks nothing like
South Australia. The holdout is the final contiguous block of the timeline, and the
calibration set the block before it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import MODEL_VERSION, get_settings
from reip.models.backends import MODEL_SUFFIX, get_backend
from reip.models.demand.features import LOAD_CENTRES, build_demand_features, feature_columns
from reip.models.demand.weather import load as load_weather
from reip.models.splits import (
    TARGET_COVERAGE,
    apply_conformal,
    conformal_widening_by_bucket,
    empirical_coverage,
    widening_for,
)
from reip.schemas import LEAD_BUCKETS, QUANTILES, lead_bucket

log = logging.getLogger(__name__)

# Fractions of the timeline, taken from the end. Calibration sits between training and
# test so the conformal correction is fitted on data the trees never saw but which precedes
# the final score - the same ordering as the generation model, projected onto time because
# there is no site dimension to hold out.
TEST_FRACTION = 0.20
CALIB_FRACTION = 0.10
VAL_FRACTION = 0.10

# The peak used to normalise each region. A high quantile rather than the maximum: a single
# extreme half hour would shrink every other region-relative value around it.
PEAK_QUANTILE = 0.999

# Below this many calibration rows a region cannot be centred or widened on its own
# evidence, and the correction would be fitted to noise.
MIN_REGION_CALIB_ROWS: int = 500


@dataclass
class DemandDataset:
    X: pd.DataFrame
    y: pd.Series
    region: pd.Series
    valid_time: pd.Series
    horizon_h: pd.Series
    peak_mw: pd.Series
    dropped_features: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.X)


def assemble(regions: list[str] | None = None) -> DemandDataset:
    """Pool every region into one normalised training set."""
    settings = get_settings()
    market_path = settings.data_canonical / "aemo_market.parquet"
    if not market_path.exists():
        raise FileNotFoundError(
            f"no market corpus at {market_path}; run `python -m reip.ingest.aemo_market`"
        )

    market = pd.read_parquet(market_path)
    weather = load_weather()
    regions = regions or sorted(LOAD_CENTRES)

    blocks: list[pd.DataFrame] = []
    peaks: dict[str, float] = {}
    for region in regions:
        frame = build_demand_features(market, weather, region)
        peak = float(market.loc[market["region"] == region, "demand_mw"].quantile(PEAK_QUANTILE))
        peaks[region] = peak

        frame["__region"] = region
        frame["__peak_mw"] = peak
        # Normalising by regional peak is what makes pooling legitimate: NSW1 runs at seven
        # times Tasmania's load, and without it the loss would be dominated by the biggest
        # region and the model would effectively be a NSW model applied everywhere.
        frame["__target_norm"] = frame["__target"] / peak
        blocks.append(frame)
        log.info("%s: %s rows, peak %.0f MW", region, f"{len(frame):,}", peak)

    pooled = pd.concat(blocks, ignore_index=True)
    pooled = pooled.sort_values("__valid_time", kind="mergesort").reset_index(drop=True)

    # Region one-hots. Legitimate here, unlike site one-hots in the generation model: every
    # region the platform will ever serve is present in training.
    for region in regions:
        pooled[f"region_{region}"] = (pooled["__region"] == region).astype("float64")
    pooled["region_peak_mw"] = pooled["__peak_mw"]

    X = pooled[feature_columns(pooled)]
    # The earliest rows have no 168-hour history yet. Dropping them costs a week and avoids
    # teaching the model that a missing lag is informative.
    complete = X.notna().all(axis=1)
    if not complete.all():
        log.info("dropping %s rows with incomplete history", f"{int((~complete).sum()):,}")
    X, pooled = X[complete], pooled[complete]

    constant = [c for c in X.columns if X[c].nunique(dropna=False) <= 1]
    if constant:
        log.info("dropping %d constant features: %s", len(constant), ", ".join(sorted(constant)))
        X = X.drop(columns=constant)

    return DemandDataset(
        X=X.reset_index(drop=True),
        y=pooled["__target_norm"].astype("float64").reset_index(drop=True),
        region=pooled["__region"].reset_index(drop=True),
        valid_time=pooled["__valid_time"].reset_index(drop=True),
        horizon_h=pooled["horizon_h"].astype("int16").reset_index(drop=True),
        peak_mw=pooled["__peak_mw"].astype("float64").reset_index(drop=True),
        dropped_features=sorted(constant),
    )


def time_splits(valid_time: pd.Series) -> dict[str, np.ndarray]:
    """Four contiguous blocks in chronological order: train, val, calib, test.

    Contiguous, and calibration sits immediately before test. That ordering was tried both
    ways and the measurement settled it.

    The obvious objection to a contiguous calibration block is seasonal: it lands on
    2025-10 to 2026-01, southern-hemisphere spring into summer, while test runs through to
    August and therefore into winter. Victorian load is 24% higher in test than in calib.
    Conformal prediction needs the two sets to be exchangeable, and two different seasons
    of a strongly seasonal quantity plainly are not.

    So calibration was re-cut as a stride-sampled set of whole days spread across every
    season of the pre-test period. Coverage got *worse* - 80.6% to 71.9% overall, and VIC1
    from 66.9% down to 55.9%.

    The reason is that the bias being corrected is itself seasonal. Averaged over a full
    year the median residual is near zero (VIC1's correction fell from +0.0115 to -0.0001),
    so a seasonally balanced calibration set has nothing left to correct with, while the
    test period still carries a specific season's bias.

    For a non-stationary series the useful calibration data is the data *closest in time*
    to what is being predicted, not the most representative sample of the past. Adjacency
    beats balance here. That is the opposite of the site-disjoint reasoning in
    `models/splits.py`, and the difference is that drift runs along the time axis and not
    the spatial one.

    It is a proxy, not a fix. VIC1 still covers 66.9% against a nominal 80%, and the
    residual gap is seasonal bias no scalar correction can reach. Recorded in the report as
    a known limitation rather than tuned away.
    """
    times = pd.DatetimeIndex(valid_time)
    span = times.max() - times.min()
    test_from = times.max() - span * TEST_FRACTION
    calib_from = test_from - span * CALIB_FRACTION
    val_from = calib_from - span * VAL_FRACTION

    return {
        "train": np.asarray(times < val_from),
        "val": np.asarray((times >= val_from) & (times < calib_from)),
        "calib": np.asarray((times >= calib_from) & (times < test_from)),
        "test": np.asarray(times >= test_from),
    }


def seasonal_naive(data: DemandDataset, mask: np.ndarray) -> np.ndarray:
    """Demand at the same hour one week earlier - the standard reference for load.

    Not plain persistence: load is strongly weekly, so yesterday at this hour is a much
    weaker guess than the same weekday last week. Beating this is the minimum bar.
    """
    return data.X.loc[mask, "load_lag_168h"].to_numpy(dtype="float64") / data.peak_mw[mask].to_numpy()


def train(regions: list[str] | None = None, *, out_dir: Path | None = None) -> dict:
    settings = get_settings()
    out_dir = out_dir or settings.artifacts_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    data = assemble(regions)
    split = time_splits(data.valid_time)
    log.info(
        "split: train %s / val %s / calib %s / test %s",
        *(f"{int(split[k].sum()):,}" for k in ("train", "val", "calib", "test")),
    )

    backend = get_backend(settings.backend)
    X_train, y_train = data.X[split["train"]], data.y[split["train"]]
    X_val, y_val = data.X[split["val"]], data.y[split["val"]]

    models, best_rounds, predictions = {}, {}, {}
    for quantile in QUANTILES:
        alpha = quantile.alpha
        model, rounds = backend.fit(
            X_train,
            y_train,
            alpha=alpha,
            seed=settings.random_seed,
            max_rounds=settings.max_boost_rounds,
            early_stopping_rounds=settings.early_stopping_rounds,
            valid=(X_val, y_val),
        )
        models[quantile.value] = model
        best_rounds[quantile.value] = rounds
        predictions[quantile.value] = {
            group: model.predict(data.X[split[group]]) for group in ("val", "calib", "test")
        }
        log.info("  %s: %d rounds", quantile.value, rounds)

    # --- conformal calibration, per lead bucket -------------------------------------
    def bounds(group: str) -> tuple[np.ndarray, np.ndarray]:
        lo, hi = predictions["p10"][group], predictions["p90"][group]
        return np.minimum(lo, hi), np.maximum(lo, hi)

    h_calib = data.horizon_h.to_numpy()[split["calib"]]
    lo_cal, hi_cal = bounds("calib")
    y_calib = data.y[split["calib"]].to_numpy()
    region_calib = data.region.to_numpy()[split["calib"]]

    h_test = data.horizon_h.to_numpy()[split["test"]]
    lo_test, hi_test = bounds("test")
    y_test = data.y[split["test"]].to_numpy()
    region_test = data.region.to_numpy()[split["test"]]

    # --- calibration is PER REGION, not pooled -------------------------------------
    #
    # A pooled correction landed on target overall and was wrong nearly everywhere:
    # measured per region, coverage came out at 93% for QLD1 and 69% for VIC1 and TAS1
    # against a nominal 80%. Pooling averages a too-wide region against a too-narrow one
    # and reports the mean as success.
    #
    # Regional load curves are not exchangeable - Tasmania is hydro-backed and industrially
    # dominated, Victoria is not - so the exchangeability that conformal prediction needs
    # simply does not hold across them. It holds *within* a region, which is where the
    # correction belongs.
    #
    # A location shift comes first. Pooling also left per-region bias in place: -3.3% of
    # peak for TAS1, +3.7% for VIC1. Conformal widening can only inflate an interval around
    # a centre it is given, so a displaced centre costs coverage on both sides at once.
    # Centring per region before widening fixes the cause rather than padding around it.
    bias: dict[str, float] = {}
    widening: dict[str, dict[str, float]] = {}
    for region in sorted(set(region_calib)):
        mask = region_calib == region
        if mask.sum() < MIN_REGION_CALIB_ROWS:
            log.warning("%s: only %d calibration rows; left uncentred", region, int(mask.sum()))
            bias[region], widening[region] = 0.0, {"all": 0.0}
            continue
        shift = float(np.median(y_calib[mask] - ((lo_cal[mask] + hi_cal[mask]) / 2.0)))
        bias[region] = shift
        widening[region] = conformal_widening_by_bucket(
            y_calib[mask],
            lo_cal[mask] + shift,
            hi_cal[mask] + shift,
            h_calib[mask],
            coverage=TARGET_COVERAGE,
        )

    def calibrated(lower, upper, horizons, regions):
        """Apply the per-region shift, then that region's per-bucket widening."""
        shift = np.array([bias.get(r, 0.0) for r in regions])
        widths = np.concatenate(
            [
                widening_for(widening.get(r, {"all": 0.0}), horizons[regions == r])
                for r in sorted(set(regions))
            ]
        )
        order = np.concatenate([np.flatnonzero(regions == r) for r in sorted(set(regions))])
        per_row = np.empty(len(horizons))
        per_row[order] = widths
        return apply_conformal(lower + shift, upper + shift, per_row, floor=-np.inf)

    cal_test = calibrated(lo_test, hi_test, h_test, region_test)
    cal_calib = calibrated(lo_cal, hi_cal, h_calib, region_calib)

    # --- scoring, in MW so the numbers mean something --------------------------------
    peak_test = data.peak_mw[split["test"]].to_numpy()
    truth_mw = y_test * peak_test
    model_mw = predictions["p50"]["test"] * peak_test
    naive_mw = seasonal_naive(data, split["test"]) * peak_test

    def nmae(pred: np.ndarray, mask: np.ndarray | None = None) -> float:
        sel = slice(None) if mask is None else mask
        return float(100 * np.mean(np.abs(pred[sel] - truth_mw[sel]) / peak_test[sel]))

    by_bucket, by_region = {}, {}
    buckets = np.array([lead_bucket(int(h)) for h in h_test])
    for label, _lo, _hi in LEAD_BUCKETS:
        mask = buckets == label
        if not mask.any():
            continue
        by_bucket[label] = {
            "n": int(mask.sum()),
            "model_nmae_pct": round(nmae(model_mw, mask), 3),
            "seasonal_naive_nmae_pct": round(nmae(naive_mw, mask), 3),
            "coverage": round(
                empirical_coverage(y_test[mask], cal_test[0][mask], cal_test[1][mask]), 4
            ),
            "mean_width_pct": round(float(100 * np.mean(cal_test[1][mask] - cal_test[0][mask])), 3),
        }

    regions_test = data.region.to_numpy()[split["test"]]
    for region in sorted(set(regions_test)):
        mask = regions_test == region
        by_region[region] = {
            "model_nmae_pct": round(nmae(model_mw, mask), 3),
            "seasonal_naive_nmae_pct": round(nmae(naive_mw, mask), 3),
            "coverage_raw": round(
                empirical_coverage(y_test[mask], lo_test[mask], hi_test[mask]), 4
            ),
            "coverage_calibrated": round(
                empirical_coverage(y_test[mask], cal_test[0][mask], cal_test[1][mask]), 4
            ),
            "bias_correction": round(bias.get(region, 0.0), 6),
        }

    metadata = {
        "model_version": MODEL_VERSION,
        "kind": "demand",
        "backend": settings.backend,
        "trained_at_utc": datetime.now(UTC).isoformat(),
        "regions": sorted(set(data.region)),
        "feature_order": list(data.X.columns),
        "dropped_constant_features": data.dropped_features,
        "n_rows": len(data),
        "split": {k: int(v.sum()) for k, v in split.items()},
        "training_window": [str(data.valid_time.min()), str(data.valid_time.max())],
        "peak_mw": {r: float(data.peak_mw[data.region == r].iloc[0]) for r in sorted(set(data.region))},
        # Per region, each a per-lead-bucket mapping. `bias` is the location shift applied
        # before widening; both are needed to reproduce a served interval.
        "conformal_widening": widening,
        "bias_correction": bias,
        "best_rounds": best_rounds,
        "test": {
            "model_nmae_pct": round(nmae(model_mw), 3),
            "seasonal_naive_nmae_pct": round(nmae(naive_mw), 3),
            "coverage_raw": round(empirical_coverage(y_test, lo_test, hi_test), 4),
            "coverage_calibrated": round(empirical_coverage(y_test, *cal_test), 4),
            "coverage_on_calibration_set": round(empirical_coverage(y_calib, *cal_calib), 4),
            "by_lead_bucket": by_bucket,
            "by_region": by_region,
        },
        "artifacts": {q.value: f"demand_{q.value}{MODEL_SUFFIX[settings.backend]}" for q in QUANTILES},
    }

    for quantile in QUANTILES:
        models[quantile.value].save(out_dir / metadata["artifacts"][quantile.value])
    (out_dir / "demand_metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )

    log.info(
        "demand: nMAE %.2f%% vs seasonal-naive %.2f%% | coverage %.1f%% -> %.1f%%",
        metadata["test"]["model_nmae_pct"],
        metadata["test"]["seasonal_naive_nmae_pct"],
        100 * metadata["test"]["coverage_raw"],
        100 * metadata["test"]["coverage_calibrated"],
    )
    return metadata


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Train the regional demand model")
    parser.add_argument("--region", action="append", choices=sorted(LOAD_CENTRES))
    args = parser.parse_args()

    result = train(args.region)
    print(json.dumps(result["test"], indent=2))
