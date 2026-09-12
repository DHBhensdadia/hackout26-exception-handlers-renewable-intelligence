"""Training: assemble the dataset, split it in time, fit the quantile models.

The two decisions that determine whether the resulting accuracy number is real:

**Splitting.** Every split here is contiguous in time. Shuffling a time series into random
folds lets the model see Tuesday afternoon while predicting Tuesday morning, and weather
is autocorrelated over hours, so a shuffled split reports an error far below anything
achievable in operation. Validation folds are forward-chaining (train on the past,
validate on the future that follows it) and the holdout is the final contiguous block,
untouched until evaluation.

**Pooling across sites.** All sites of a technology train one model. This is possible only
because the target is dimensionless, and it is what makes the model work on a site with no
history at all: it has learned the weather-to-output relationship across thirteen plants,
not the idiosyncrasies of one.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import MODEL_VERSION, get_settings
from reip.features.build import build_features, build_target
from reip.models.backends import MODEL_SUFFIX, get_backend
from reip.models.splits import (
    TARGET_COVERAGE,
    apply_conformal,
    conformal_widening_by_bucket,
    empirical_coverage,
    make_split,
    widening_for,
)
from reip.schemas import LEAD_BUCKETS, QUANTILES, Quantile, Tech, lead_bucket
from reip.sites.registry import SiteRegistry

log = logging.getLogger(__name__)


@dataclass
class Dataset:
    """A pooled, time-ordered training set for one technology."""

    X: pd.DataFrame
    y: pd.Series
    site_id: pd.Series
    valid_time: pd.Series
    horizon_h: pd.Series
    capacity_mw: pd.Series
    denominator: pd.Series
    dropped_features: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.X)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - provenance is nice to have, not required
        return "unknown"


# --------------------------------------------------------------------------------------
# Dataset assembly
# --------------------------------------------------------------------------------------


# Corpora in preference order.
#
# `aemo_ml` leads: it is the same plants and the same SCADA as `aemo`, but its weather
# carries genuine 24/48/72 h forecast leads from the Previous Runs archive rather than one
# nominal lead. That is what lets `horizon_h` vary, and therefore what lets the p10-p90
# band widen with lead time - the property every downstream consumer of the band depends on.
#
# `aemo` follows: real coordinates and real nameplate capacities, single lead.
# `gefcom` last: anonymised and pre-normalised, but it keeps the pipeline working on a
# fresh checkout that has only run the GEFCom ingest.
CORPUS_PREFERENCE: tuple[str, ...] = ("aemo_ml", "aemo", "gefcom")

# Corpora that share another's power half. Generation does not change when the weather
# source does, so re-fetching weather must not mean duplicating a multi-gigabyte power
# parquet - or worse, letting the two copies drift apart.
POWER_ALIAS: dict[str, str] = {"aemo_ml": "aemo"}


def power_corpus(corpus: str) -> str:
    """The corpus whose power parquet backs `corpus`."""
    return POWER_ALIAS.get(corpus, corpus)


def available_corpora(tech: Tech) -> list[str]:
    """Corpora on disk for a technology, most preferred first."""
    canonical = get_settings().data_canonical
    found = []
    for name in CORPUS_PREFERENCE:
        if (canonical / f"{power_corpus(name)}_{tech.value}_power.parquet").exists() and (
            canonical / f"{name}_{tech.value}_weather.parquet"
        ).exists():
            found.append(name)
    return found


def assemble(
    tech: Tech, *, registry: SiteRegistry | None = None, corpus: str | None = None
) -> Dataset:
    """Build the pooled feature matrix and target for every site of a technology.

    `corpus` selects a source by name; the default takes the most preferred one available.
    Corpora are deliberately not concatenated by default - they carry different capacity
    conventions and coordinate provenance, and silently mixing them would make the
    reported site count mean two different things at once.
    """
    settings = get_settings()
    registry = registry or SiteRegistry.load()

    choices = available_corpora(tech)
    if not choices:
        raise FileNotFoundError(
            f"no canonical {tech.value} corpus in {settings.data_canonical}; "
            f"run `python -m reip.ingest.aemo` or `python -m reip.ingest.gefcom`"
        )
    corpus = corpus or choices[0]
    log.info("%s: using corpus %r (available: %s)", tech.value, corpus, ", ".join(choices))

    weather_all = pd.read_parquet(settings.data_canonical / f"{corpus}_{tech.value}_weather.parquet")
    power_all = pd.read_parquet(
        settings.data_canonical / f"{power_corpus(corpus)}_{tech.value}_power.parquet"
    )

    frames: list[pd.DataFrame] = []
    for site in registry.by_tech(tech):
        weather = weather_all[weather_all["site_id"] == site.site_id]
        power = power_all[power_all["site_id"] == site.site_id]
        if weather.empty or power.empty:
            continue

        X = build_features(weather, site)
        y, denominator = build_target(power, site, X.index)

        block = X.copy()
        block["__target"] = y.to_numpy()
        block["__site_id"] = site.site_id
        block["__valid_time"] = X.index
        block["__capacity_mw"] = site.capacity_mw
        block["__denominator"] = denominator.to_numpy()
        frames.append(block)

    if not frames:
        raise RuntimeError(f"no usable sites for {tech.value}")

    pooled = pd.concat(frames, ignore_index=True)

    # Rows with no target are night (solar) or a genuine gap. They cannot teach anything
    # and would dominate the loss with trivially-zero cases.
    pooled = pooled[pooled["__target"].notna()].reset_index(drop=True)
    pooled = pooled.sort_values("__valid_time", kind="mergesort").reset_index(drop=True)

    meta_cols = [c for c in pooled.columns if c.startswith("__")]
    X = pooled.drop(columns=meta_cols)

    # A feature that never varies carries no information and only adds a dimension the
    # trees must scan. Wind is the concrete case: GEFCom supplies no temperature or
    # pressure, so air density is constant throughout training.
    constant = [c for c in X.columns if X[c].nunique(dropna=False) <= 1]
    if constant:
        log.info("dropping %d constant features: %s", len(constant), ", ".join(sorted(constant)))
        X = X.drop(columns=constant)

    return Dataset(
        X=X,
        y=pooled["__target"].astype("float64"),
        site_id=pooled["__site_id"],
        valid_time=pooled["__valid_time"],
        horizon_h=pooled["horizon_h"].astype("int16"),
        capacity_mw=pooled["__capacity_mw"].astype("float64"),
        denominator=pooled["__denominator"].astype("float64"),
        dropped_features=sorted(constant),
    )


# --------------------------------------------------------------------------------------
# Time-respecting splits
# --------------------------------------------------------------------------------------


def holdout_split(data: Dataset, fraction: float) -> tuple[np.ndarray, np.ndarray]:
    """Split on a time boundary, not a row count.

    Splitting by row index would cut through the middle of an hour that several sites
    share, leaking a site's neighbour at the same timestamp across the boundary.
    """
    times = pd.DatetimeIndex(data.valid_time)
    cutoff = times.min() + (times.max() - times.min()) * (1.0 - fraction)
    is_holdout = np.asarray(times > cutoff)
    return ~is_holdout, is_holdout


def forward_chaining_folds(times: pd.Series, n_folds: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window CV: each fold trains on all prior time and validates on the next block."""
    index = pd.DatetimeIndex(times)
    start, end = index.min(), index.max()
    edges = [start + (end - start) * (i / (n_folds + 1)) for i in range(1, n_folds + 2)]

    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(n_folds):
        train = np.asarray(index <= edges[i])
        valid = np.asarray((index > edges[i]) & (index <= edges[i + 1]))
        if train.sum() and valid.sum():
            folds.append((train, valid))
    return folds


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    """Mean pinball (quantile) loss - the objective these models are actually judged on."""
    delta = y_true - y_pred
    return float(np.mean(np.maximum(alpha * delta, (alpha - 1.0) * delta)))


# --------------------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------------------


def train_technology(tech: Tech, *, out_dir: Path | None = None) -> dict:
    """Fit p10/p50/p90 for one technology and write artifacts plus metadata."""
    settings = get_settings()
    settings.ensure_dirs()
    out_dir = out_dir or settings.artifacts_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    data = assemble(tech)
    split = make_split(data.site_id, data.valid_time, seed=settings.random_seed)
    log.info(
        "%s: %s rows, %d features, %d sites",
        tech.value,
        f"{len(data):,}",
        data.X.shape[1],
        data.site_id.nunique(),
    )

    X_train, y_train = data.X[split.train], data.y[split.train]
    X_val, y_val = data.X[split.val], data.y[split.val]
    X_calib, y_calib = data.X[split.calib], data.y[split.calib]
    X_test, y_test = data.X[split.test], data.y[split.test]

    backend = get_backend(settings.backend)
    feature_order = list(data.X.columns)
    artifacts: dict[str, str] = {}
    best_rounds: dict[str, int] = {}
    val_pinball: dict[str, float] = {}
    importances: dict[str, float] = {}
    val_pred: dict[str, np.ndarray] = {}
    calib_pred: dict[str, np.ndarray] = {}
    test_pred: dict[str, np.ndarray] = {}

    for quantile in QUANTILES:
        alpha = quantile.alpha
        # Validation drives early stopping directly. With a proper three-way split there
        # is no need for the old inner CV: the validation block is already held out, in
        # time, from sites the model does train on.
        model, rounds = backend.fit(
            X_train,
            y_train,
            alpha=alpha,
            seed=settings.random_seed,
            max_rounds=settings.max_boost_rounds,
            early_stopping_rounds=settings.early_stopping_rounds,
            valid=(X_val, y_val),
        )

        path = out_dir / f"{tech.value}_{quantile.value}{MODEL_SUFFIX[settings.backend]}"
        model.save(path)
        artifacts[quantile.value] = path.name
        best_rounds[quantile.value] = rounds

        val_pred[quantile.value] = model.predict(X_val)
        calib_pred[quantile.value] = model.predict(X_calib)
        test_pred[quantile.value] = model.predict(X_test)
        val_pinball[quantile.value] = pinball_loss(y_val.to_numpy(), val_pred[quantile.value], alpha)
        if quantile is Quantile.P50:
            importances = model.feature_importance()

        log.info(
            "  %s a=%.2f: %d rounds, val pinball %.5f",
            quantile.value,
            alpha,
            rounds,
            val_pinball[quantile.value],
        )

    # --- conformal calibration, fitted on HELD-OUT SITES ------------------------------
    # Calibrating on `val` (same sites, later time) does not transfer: an unseen plant
    # carries more uncertainty than a later hour at a known plant, so the correction is
    # fitted on sites the model never saw, matching the condition it will be judged on.
    lower_val = np.minimum(val_pred["p10"], val_pred["p90"])
    upper_val = np.maximum(val_pred["p10"], val_pred["p90"])
    raw_val_coverage = empirical_coverage(y_val.to_numpy(), lower_val, upper_val)

    lower_cal = np.minimum(calib_pred["p10"], calib_pred["p90"])
    upper_cal = np.maximum(calib_pred["p10"], calib_pred["p90"])
    raw_calib_coverage = empirical_coverage(y_calib.to_numpy(), lower_cal, upper_cal)
    # One widening per lead bucket. Forecast error grows with lead time, so a single scalar
    # over-covers the near term and under-covers the far term while still averaging to the
    # target - and it is the far term where a too-narrow band does the most damage.
    h_calib = data.horizon_h.to_numpy()[split.calib]
    widening = conformal_widening_by_bucket(
        y_calib.to_numpy(), lower_cal, upper_cal, h_calib, coverage=TARGET_COVERAGE
    )
    w_calib = widening_for(widening, h_calib)
    cal_calib_coverage = empirical_coverage(
        y_calib.to_numpy(), *apply_conformal(lower_cal, upper_cal, w_calib)
    )
    w_val = widening_for(widening, data.horizon_h.to_numpy()[split.val])
    cal_val_coverage = empirical_coverage(
        y_val.to_numpy(), *apply_conformal(lower_val, upper_val, w_val)
    )

    lower_test = np.minimum(test_pred["p10"], test_pred["p90"])
    upper_test = np.maximum(test_pred["p10"], test_pred["p90"])
    raw_test_coverage = empirical_coverage(y_test.to_numpy(), lower_test, upper_test)
    h_test = data.horizon_h.to_numpy()[split.test]
    cal_test = apply_conformal(lower_test, upper_test, widening_for(widening, h_test))
    cal_test_coverage = empirical_coverage(y_test.to_numpy(), *cal_test)

    # Per-bucket coverage and band width on unseen sites. Width must increase with lead,
    # and if it does not the multi-lead corpus has not done its job.
    per_bucket = {}
    test_buckets = np.array([lead_bucket(int(h)) for h in h_test])
    for label, _lo, _hi in LEAD_BUCKETS:
        mask = test_buckets == label
        if not mask.any():
            continue
        per_bucket[label] = {
            "n": int(mask.sum()),
            "widening": round(float(widening.get(label, widening["all"])), 6),
            "raw": round(
                empirical_coverage(y_test.to_numpy()[mask], lower_test[mask], upper_test[mask]), 4
            ),
            "calibrated": round(
                empirical_coverage(y_test.to_numpy()[mask], cal_test[0][mask], cal_test[1][mask]), 4
            ),
            "mean_width": round(float(np.mean(cal_test[1][mask] - cal_test[0][mask])), 6),
        }

    log.info(
        "  conformal widening %s (fitted on %d held-out calibration sites)",
        {k: round(v, 4) for k, v in widening.items()},
        len(split.calib_sites),
    )
    for label, stats in per_bucket.items():
        log.info(
            "    %-7s n=%-9s coverage %.1f%%->%.1f%%  mean width %.4f",
            label,
            f"{stats['n']:,}",
            100 * stats["raw"],
            100 * stats["calibrated"],
            stats["mean_width"],
        )
    log.info(
        "    coverage: calib %.1f%%->%.1f%% | UNSEEN-SITE TEST %.1f%%->%.1f%% (target %.0f%%)",
        100 * raw_calib_coverage,
        100 * cal_calib_coverage,
        100 * raw_test_coverage,
        100 * cal_test_coverage,
        100 * TARGET_COVERAGE,
    )

    # --- honest score on the spatially-unseen test sites -------------------------------
    capacity_test = data.capacity_mw.to_numpy()[split.test]
    denom_test = data.denominator.to_numpy()[split.test]
    actual_mw = y_test.to_numpy() * denom_test
    predicted_mw = np.clip(test_pred["p50"] * denom_test, 0.0, capacity_test)
    test_nmae = float(100 * np.mean(np.abs(actual_mw - predicted_mw) / capacity_test))
    test_nrmse = float(100 * np.sqrt(np.mean(((actual_mw - predicted_mw) / capacity_test) ** 2)))
    test_bias = float(100 * np.mean((actual_mw - predicted_mw) / capacity_test))
    log.info(
        "  UNSEEN-SITE TEST: nMAE %.2f%% | nRMSE %.2f%% | bias %+.2f%% | coverage %.1f%%",
        test_nmae,
        test_nrmse,
        test_bias,
        100 * cal_test_coverage,
    )

    times = pd.DatetimeIndex(data.valid_time)
    metadata = {
        "model_version": MODEL_VERSION,
        "tech": tech.value,
        "backend": settings.backend,
        "trained_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "feature_order": feature_order,
        "dropped_constant_features": data.dropped_features,
        "n_rows": len(data),
        "n_train_rows": int(split.train.sum()),
        "n_val_rows": int(split.val.sum()),
        "n_calib_rows": int(split.calib.sum()),
        "n_holdout_rows": int(split.test.sum()),
        "split": split.summary(len(data)),
        "conformal_widening": widening,
        "coverage": {
            "target": TARGET_COVERAGE,
            "calib_raw": raw_calib_coverage,
            "calib_calibrated": cal_calib_coverage,
            "val_raw": raw_val_coverage,
            "val_calibrated": cal_val_coverage,
            "test_raw": raw_test_coverage,
            "test_calibrated": cal_test_coverage,
            "test_by_lead_bucket": per_bucket,
        },
        "unseen_site_test": {
            "nmae_pct": test_nmae,
            "nrmse_pct": test_nrmse,
            "bias_pct": test_bias,
            "n": int(split.test.sum()),
            "n_sites": len(split.test_sites),
        },
        "sites": sorted(data.site_id.unique().tolist()),
        "training_window": [str(times.min()), str(times.max())],
        "val_starts": str(split.val_cutoff),
        "horizons_present": [int(data.horizon_h.min()), int(data.horizon_h.max())],
        "val_pinball": val_pinball,
        "best_rounds": best_rounds,
        "artifacts": artifacts,
        "top_features": dict(sorted(importances.items(), key=lambda kv: -kv[1])[:20]),
    }
    (out_dir / f"{tech.value}_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main(techs: list[Tech] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for tech in techs or list(Tech):
        meta = train_technology(tech)
        print(f"\n{tech.value}: {meta['n_rows']} rows, {len(meta['feature_order'])} features")
        for quantile, score in meta["val_pinball"].items():
            print(f"  {quantile} val pinball: {score:.5f}")
        t = meta["unseen_site_test"]
        print(
            f"  UNSEEN-SITE nMAE {t['nmae_pct']:.2f}%  bias {t['bias_pct']:+.2f}%  "
            f"coverage {100 * meta['coverage']['test_calibrated']:.1f}%"
        )
        print("  top features: " + ", ".join(list(meta["top_features"])[:6]))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train quantile forecasting models")
    parser.add_argument("--tech", action="append", choices=[t.value for t in Tech])
    args = parser.parse_args()
    main([Tech(t) for t in args.tech] if args.tech else None)
