"""Score two model generations on identical data, bucketed by lead time.

This exists because the multi-lead retrain appeared to fail its acceptance gate and had
not. Wind went from a headline 12.38% nMAE to 14.24% - six times the 0.3 pp regression the
gate allowed - and the honest reading of that number was the opposite of the obvious one.

The two figures were measured on different problems. The single-lead corpus was built from
Open-Meteo's `historical_forecast`, which returns the *best available* forecast for each
hour, roughly 0-24 h of lead. The multi-lead corpus returns what was actually forecast 24,
48 and 72 hours ahead. Predicting from a nearly-current forecast is a materially easier
task than predicting from a three-day-old one, so a pooled score across all three leads was
being compared against a score from the easiest of them.

Run head to head on the same rows, the new wind model is better at every lead. The old
model's 12.38% becomes 14.44% when it is asked the genuine 24-hour question.

The general point is worth keeping: **a headline metric is only comparable against another
metric measured on the same difficulty.** Changing the data can move a number further than
changing the model, and in the opposite direction to the truth.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from reip.config import get_settings
from reip.models.backends import MODEL_SUFFIX, get_backend
from reip.models.splits import make_split
from reip.models.train import assemble
from reip.schemas import LEAD_BUCKETS, QUANTILES, Tech, lead_bucket

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSet:
    """One generation of artifacts, loaded from a directory."""

    name: str
    metadata: dict
    models: dict[str, object]

    @property
    def feature_order(self) -> list[str]:
        dropped = set(self.metadata.get("dropped_constant_features", []))
        return [f for f in self.metadata["feature_order"] if f not in dropped]

    @classmethod
    def load(cls, directory: Path, tech: Tech, name: str) -> ModelSet:
        metadata = json.loads(
            (directory / f"{tech.value}_metadata.json").read_text(encoding="utf-8")
        )
        backend_name = metadata.get("backend", get_settings().backend)
        backend = get_backend(backend_name)
        suffix = MODEL_SUFFIX[backend_name]
        models = {
            q.value: backend.load(directory / f"{tech.value}_{q.value}{suffix}") for q in QUANTILES
        }
        return cls(name=name, metadata=metadata, models=models)


def compare(
    tech: Tech, current: Path, baseline: Path, *, seed: int = 42
) -> dict:
    """Score both generations on the current corpus, per lead bucket.

    Both are evaluated on the *same* rows - the current corpus's spatially-held-out test
    sites - so the only thing that differs is the model. The split is regenerated with the
    same seed and asserted identical to what each artifact recorded, because a comparison
    across different held-out sites would mean nothing.
    """
    new = ModelSet.load(current, tech, "current")
    old = ModelSet.load(baseline, tech, "baseline")

    data = assemble(tech)
    split = make_split(data.site_id, data.valid_time, seed=seed)

    for model in (new, old):
        recorded = set(model.metadata.get("split", {}).get("test_sites", []))
        if recorded and recorded != set(split.test_sites):
            raise ValueError(
                f"{tech.value}: {model.name} was tested on different sites; "
                "the comparison would not be like for like"
            )

    capacity = data.capacity_mw.to_numpy()[split.test]
    denominator = data.denominator.to_numpy()[split.test]
    truth_mw = data.y.to_numpy()[split.test] * denominator
    horizons = data.horizon_h.to_numpy()[split.test]
    X = data.X[split.test]

    def nmae(model: ModelSet, mask: np.ndarray) -> float:
        # Each generation is fed only the features it was fitted on. The older model
        # predates horizon_h surviving selection, so its column set is a strict subset.
        columns = [c for c in model.feature_order if c in X.columns]
        predicted = np.clip(
            model.models["p50"].predict(X[columns].loc[mask]) * denominator[mask],
            0.0,
            capacity[mask],
        )
        return float(100 * np.mean(np.abs(truth_mw[mask] - predicted) / capacity[mask]))

    buckets = np.array([lead_bucket(int(h)) for h in horizons])
    result: dict = {
        "tech": tech.value,
        "test_sites": split.test_sites,
        "n_test_rows": int(split.test.sum()),
        "by_lead_bucket": {},
    }
    for label, _lo, _hi in LEAD_BUCKETS:
        mask = buckets == label
        if not mask.any():
            continue
        current_score, baseline_score = nmae(new, mask), nmae(old, mask)
        result["by_lead_bucket"][label] = {
            "n": int(mask.sum()),
            "current_nmae_pct": round(current_score, 3),
            "baseline_nmae_pct": round(baseline_score, 3),
            "improvement_pp": round(baseline_score - current_score, 3),
        }
        log.info(
            "  %-7s n=%-9s current %.2f%%  baseline %.2f%%  (%+.2f pp)",
            label,
            f"{int(mask.sum()):,}",
            current_score,
            baseline_score,
            baseline_score - current_score,
        )

    # The figure each artifact reported for itself, which is what a reader would otherwise
    # compare - and which is exactly the trap this module exists to defuse.
    result["headline_as_reported"] = {
        "current": new.metadata.get("unseen_site_test", {}).get("nmae_pct"),
        "baseline": old.metadata.get("unseen_site_test", {}).get("nmae_pct"),
        "note": (
            "Not comparable: the baseline was scored on a best-available-forecast corpus "
            "(~0-24h lead), the current model on genuine 24/48/72h forecasts."
        ),
    }
    return result


def main(techs: list[Tech] | None = None, baseline: Path | None = None) -> dict:
    settings = get_settings()
    baseline = baseline or (settings.cache_dir / "artifacts_singlelead")
    if not baseline.exists():
        raise FileNotFoundError(f"no baseline artifacts at {baseline}")

    results = {}
    for tech in techs or list(Tech):
        log.info("%s:", tech.value)
        results[tech.value] = compare(tech, settings.artifacts_dir, baseline)

    out = settings.reports_dir / "lead_comparison.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    log.info("wrote %s", out)
    return results


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Compare model generations on identical data, per lead bucket"
    )
    parser.add_argument("--tech", action="append", choices=[t.value for t in Tech])
    parser.add_argument("--baseline", type=Path, default=None)
    args = parser.parse_args()

    output = main([Tech(t) for t in args.tech] if args.tech else None, args.baseline)
    print(json.dumps(output, indent=2, default=str))
