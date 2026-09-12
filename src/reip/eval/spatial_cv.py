"""Leave-one-site-out cross-validation: the honest test of generalisation.

The temporal holdout answers "can this model predict next month at a plant it already
knows?" That is not the question the platform is built to answer. `/forecast` accepts an
arbitrary latitude and longitude, and the Gujarat sites it is meant to serve have no
generation history at all. The real question is **"can it predict a plant it has never
seen?"** - and a temporal holdout cannot measure that, because every site in the test set
was also in the training set.

Leave-one-site-out measures it directly. Train on every plant but one, predict the one that
was held out, rotate through all of them. Each fold is an exact simulation of the
cold-start case: a plant the model has no history for, forecast from weather and metadata
alone.

Two expectations worth stating before running it:

* **Scores will get worse.** A site-aware model can lean on the quirks of plants it has
  memorised - the particular soiling, shading and curtailment behaviour of each one. Strip
  that away and error rises. The higher number is the truthful one.

* **The spread across folds matters as much as the mean.** A model that averages 8% but
  ranges from 4% to 25% is unreliable in a way the mean conceals; per-site results are
  reported for exactly that reason.

Full LOSO over 177 sites means 177 training runs. `folds` groups sites into k blocks
instead, which gives the same guarantee - no test site appears in its own training set -
at a fraction of the cost.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.eval.metrics import nmae, nrmse, picp, r_squared, skill_score
from reip.models.backends import get_backend
from reip.models.train import Dataset, assemble
from reip.schemas import LEAD_BUCKETS, QUANTILES, Tech

log = logging.getLogger(__name__)


@dataclass
class SiteResult:
    """Held-out performance for one site."""

    site_id: str
    n: int
    capacity_mw: float
    nmae_pct: float
    nrmse_pct: float
    r2: float
    picp_pct: float
    smart_persistence_nmae_pct: float

    @property
    def skill_pct(self) -> float:
        return skill_score(self.nmae_pct, self.smart_persistence_nmae_pct)


def _site_folds(site_ids: np.ndarray, k: int | None) -> list[list[str]]:
    """Partition sites into folds. `k=None` means true leave-one-site-out.

    Sites are dealt round-robin across folds after sorting, so each fold mixes large and
    small plants rather than clustering them - a fold of only tiny sites would produce a
    misleadingly noisy score.
    """
    unique = sorted(set(site_ids))
    if k is None or k >= len(unique):
        return [[s] for s in unique]
    return [unique[i::k] for i in range(k)]


def _persistence_reference(frame: pd.DataFrame) -> np.ndarray:
    """Smart-persistence prediction for a held-out block.

    Uses only the site's own past observations relative to each forecast's issue time, so
    it stays a fair reference even for a site the model never trained on.
    """
    index = pd.MultiIndex.from_arrays(
        [frame["site_id"], frame["valid_time_utc"] - pd.to_timedelta(frame["horizon_h"], unit="h")]
    )
    observed = (
        frame.set_index(["site_id", "valid_time_utc"])["actual_mw"]
        .groupby(level=[0, 1])
        .first()
    )
    at_issue = observed.reindex(index).to_numpy(dtype="float64")

    denominator = frame["denominator_mw"].to_numpy(dtype="float64")
    denominator_at_issue = (
        frame.set_index(["site_id", "valid_time_utc"])["denominator_mw"]
        .groupby(level=[0, 1])
        .first()
        .reindex(index)
        .to_numpy(dtype="float64")
    )

    ratio = np.divide(
        np.nan_to_num(at_issue),
        denominator_at_issue,
        out=np.zeros(len(frame)),
        where=denominator_at_issue > 1e-6,
    )
    return np.clip(ratio, 0.0, 1.3) * denominator


def run(
    tech: Tech,
    *,
    k_folds: int | None = 8,
    max_rounds: int = 400,
    out_dir: Path | None = None,
) -> dict:
    """Run grouped leave-one-site-out CV and return per-site and pooled results."""
    settings = get_settings()
    out_dir = out_dir or settings.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    data: Dataset = assemble(tech)
    site_ids = data.site_id.to_numpy()
    folds = _site_folds(site_ids, k_folds)
    backend = get_backend(settings.backend)

    log.info(
        "%s: %s rows, %d sites, %d folds (%s)",
        tech.value,
        f"{len(data):,}",
        len(set(site_ids)),
        len(folds),
        "true LOSO" if k_folds is None else f"grouped k={k_folds}",
    )

    predictions: list[pd.DataFrame] = []

    for i, held_out in enumerate(folds, 1):
        test_mask = np.isin(site_ids, held_out)
        train_mask = ~test_mask
        if not test_mask.any() or not train_mask.any():
            continue

        X_train, y_train = data.X[train_mask], data.y[train_mask]
        X_test = data.X[test_mask]

        quantile_preds = {}
        for quantile in QUANTILES:
            model, _ = backend.fit(
                X_train,
                y_train,
                alpha=quantile.alpha,
                seed=settings.random_seed,
                max_rounds=max_rounds,
                early_stopping_rounds=settings.early_stopping_rounds,
                valid=None,
            )
            quantile_preds[quantile.value] = model.predict(X_test)

        stacked = np.sort(
            np.column_stack([quantile_preds[q.value] for q in QUANTILES]), axis=1
        )
        denominator = data.denominator.to_numpy()[test_mask]
        capacity = data.capacity_mw.to_numpy()[test_mask]
        power = np.clip(stacked * denominator[:, None], 0.0, capacity[:, None])

        predictions.append(
            pd.DataFrame(
                {
                    "site_id": site_ids[test_mask],
                    "valid_time_utc": pd.DatetimeIndex(data.valid_time)[test_mask],
                    "horizon_h": data.horizon_h.to_numpy()[test_mask],
                    "capacity_mw": capacity,
                    "denominator_mw": denominator,
                    "actual_mw": data.y.to_numpy()[test_mask] * denominator,
                    "p10_mw": power[:, 0],
                    "p50_mw": power[:, 1],
                    "p90_mw": power[:, 2],
                    "target": data.y.to_numpy()[test_mask],
                }
            )
        )
        log.info("  fold %d/%d: %d sites, %s rows", i, len(folds), len(held_out), f"{int(test_mask.sum()):,}")

    combined = pd.concat(predictions, ignore_index=True)
    combined["smart_persistence_mw"] = _persistence_reference(combined)

    per_site: list[SiteResult] = []
    for site_id, block in combined.groupby("site_id"):
        y = block["actual_mw"].to_numpy(dtype="float64")
        cap = block["capacity_mw"].to_numpy(dtype="float64")
        per_site.append(
            SiteResult(
                site_id=str(site_id),
                n=len(block),
                capacity_mw=float(cap[0]),
                nmae_pct=nmae(y, block["p50_mw"].to_numpy(dtype="float64"), cap),
                nrmse_pct=nrmse(y, block["p50_mw"].to_numpy(dtype="float64"), cap),
                r2=r_squared(y, block["p50_mw"].to_numpy(dtype="float64")),
                picp_pct=picp(
                    y,
                    block["p10_mw"].to_numpy(dtype="float64"),
                    block["p90_mw"].to_numpy(dtype="float64"),
                ),
                smart_persistence_nmae_pct=nmae(
                    y, block["smart_persistence_mw"].to_numpy(dtype="float64"), cap
                ),
            )
        )

    y_all = combined["actual_mw"].to_numpy(dtype="float64")
    cap_all = combined["capacity_mw"].to_numpy(dtype="float64")
    pooled = {
        "n": int(len(combined)),
        "n_sites": int(combined["site_id"].nunique()),
        "nmae_pct": nmae(y_all, combined["p50_mw"].to_numpy(dtype="float64"), cap_all),
        "nrmse_pct": nrmse(y_all, combined["p50_mw"].to_numpy(dtype="float64"), cap_all),
        "r2": r_squared(y_all, combined["p50_mw"].to_numpy(dtype="float64")),
        "picp_pct": picp(
            y_all,
            combined["p10_mw"].to_numpy(dtype="float64"),
            combined["p90_mw"].to_numpy(dtype="float64"),
        ),
        "smart_persistence_nmae_pct": nmae(
            y_all, combined["smart_persistence_mw"].to_numpy(dtype="float64"), cap_all
        ),
    }
    pooled["skill_pct"] = skill_score(pooled["nmae_pct"], pooled["smart_persistence_nmae_pct"])

    by_lead = []
    for label, lo, hi in LEAD_BUCKETS:
        window = combined[(combined["horizon_h"] >= lo) & (combined["horizon_h"] <= hi)]
        if window.empty:
            continue
        yw = window["actual_mw"].to_numpy(dtype="float64")
        cw = window["capacity_mw"].to_numpy(dtype="float64")
        by_lead.append(
            {
                "lead_bucket": label,
                "n": int(len(window)),
                "nmae_pct": nmae(yw, window["p50_mw"].to_numpy(dtype="float64"), cw),
                "picp_pct": picp(
                    yw,
                    window["p10_mw"].to_numpy(dtype="float64"),
                    window["p90_mw"].to_numpy(dtype="float64"),
                ),
                "smart_persistence_nmae_pct": nmae(
                    yw, window["smart_persistence_mw"].to_numpy(dtype="float64"), cw
                ),
            }
        )

    spread = sorted(r.nmae_pct for r in per_site)
    result = {
        "tech": tech.value,
        "mode": "loso" if k_folds is None else f"grouped-{k_folds}",
        "pooled": pooled,
        "by_lead": by_lead,
        "per_site": [r.__dict__ | {"skill_pct": r.skill_pct} for r in per_site],
        "spread": {
            "best_nmae_pct": spread[0],
            "median_nmae_pct": float(np.median(spread)),
            "p90_nmae_pct": float(np.percentile(spread, 90)),
            "worst_nmae_pct": spread[-1],
        },
    }

    path = out_dir / f"spatial_cv_{tech.value}.json"
    path.write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    log.info(
        "%s unseen-site nMAE %.2f%% (median site %.2f%%, worst %.2f%%) vs smart persistence %.2f%%",
        tech.value,
        pooled["nmae_pct"],
        result["spread"]["median_nmae_pct"],
        result["spread"]["worst_nmae_pct"],
        pooled["smart_persistence_nmae_pct"],
    )
    return result


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Leave-one-site-out cross-validation")
    parser.add_argument("--tech", action="append", choices=[t.value for t in Tech])
    parser.add_argument("--folds", type=int, default=8, help="0 for true leave-one-site-out")
    args = parser.parse_args()

    for tech in [Tech(t) for t in args.tech] if args.tech else list(Tech):
        run(tech, k_folds=args.folds or None)
