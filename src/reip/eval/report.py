"""Benchmark the trained models against the baselines on the untouched holdout.

Produces `reports/benchmark.md` plus a skill-versus-lead figure. Everything is computed on
the final contiguous time block, which no model or baseline saw during fitting.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.eval import baselines as bl
from reip.eval.metrics import by_lead_bucket, evaluate_predictions, pinball, skill_score
from reip.ingest.gefcom import LEAD_TIME_LIMITATION
from reip.models.predict import load_model
from reip.models.train import assemble, holdout_split
from reip.schemas import QUANTILES, Tech
from reip.sites.registry import SiteRegistry

log = logging.getLogger(__name__)


def build_holdout_frame(tech: Tech) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assemble train and holdout frames carrying predictions, truth and every baseline."""
    settings = get_settings()
    registry = SiteRegistry.load()
    model = load_model(tech)

    data = assemble(tech, registry=registry)
    train_mask, holdout_mask = holdout_split(data, settings.holdout_fraction)

    # Actual power in MW, recovered from the dimensionless target by the same reference
    # the training step divided by.
    actual_mw = data.y.to_numpy(dtype="float64") * data.denominator.to_numpy(dtype="float64")

    features = data.X[[f for f in model.feature_order]]
    quantile_preds = np.sort(
        np.column_stack(
            [
                np.asarray(model.models[q.value].predict(features), dtype="float64")
                for q in QUANTILES
            ]
        ),
        axis=1,
    )
    denominator = data.denominator.to_numpy(dtype="float64")
    capacity = data.capacity_mw.to_numpy(dtype="float64")
    power = np.clip(quantile_preds * denominator[:, None], 0.0, capacity[:, None])

    frame = pd.DataFrame(
        {
            "site_id": data.site_id.to_numpy(),
            "valid_time_utc": pd.DatetimeIndex(data.valid_time),
            "horizon_h": data.horizon_h.to_numpy(dtype="int16"),
            "capacity_mw": capacity,
            "denominator_mw": denominator,
            "actual_mw": actual_mw,
            "p10_mw": power[:, 0],
            "p50_mw": power[:, 1],
            "p90_mw": power[:, 2],
            "target": data.y.to_numpy(dtype="float64"),
        }
    )

    # Physics-only baseline, reconstructed from the features the model itself received.
    if tech is Tech.SOLAR:
        frame["physics_mw"] = data.X["physics_cf"].to_numpy(dtype="float64") * capacity
    else:
        frame["physics_mw"] = data.X["cf_powercurve"].to_numpy(dtype="float64") * capacity

    frame = _attach_issue_state(frame, tech)

    return frame[train_mask].reset_index(drop=True), frame[holdout_mask].reset_index(drop=True)


def _attach_issue_state(frame: pd.DataFrame, tech: Tech) -> pd.DataFrame:
    """Attach observed power and clear-sky reference at each forecast's issue time.

    Persistence baselines need the last observation available when the forecast was made.
    The issue time is `valid_time - horizon_h`, and the value at that instant is looked up
    per site.
    """
    frame = frame.copy()
    frame["issue_time_utc"] = frame["valid_time_utc"] - pd.to_timedelta(
        frame["horizon_h"], unit="h"
    )

    observed = frame.set_index(["site_id", "valid_time_utc"])[["actual_mw", "denominator_mw"]]
    lookup_index = pd.MultiIndex.from_arrays(
        [frame["site_id"], frame["issue_time_utc"]], names=["site_id", "valid_time_utc"]
    )
    at_issue = observed[~observed.index.duplicated()].reindex(lookup_index)

    frame["power_at_issue_mw"] = np.nan_to_num(at_issue["actual_mw"].to_numpy(dtype="float64"))
    frame["denominator_at_issue_mw"] = np.nan_to_num(
        at_issue["denominator_mw"].to_numpy(dtype="float64")
    )
    return frame


def score_all(train: pd.DataFrame, holdout: pd.DataFrame, tech: Tech) -> dict:
    """Score the model and every baseline on the holdout, overall and by lead bucket."""
    holdout = holdout.copy()
    holdout["persistence"] = bl.persistence(holdout)
    holdout["smart_persistence"] = bl.smart_persistence(holdout, tech)
    holdout["climatology"] = bl.climatology(train, holdout)
    holdout["physics_only"] = bl.physics_only(holdout)

    overall = {
        "model": evaluate_predictions(
            holdout, pred_col="p50_mw", lower_col="p10_mw", upper_col="p90_mw"
        )
    }
    for name in bl.BASELINE_LABELS:
        overall[name] = evaluate_predictions(holdout, pred_col=name)

    buckets = {"model": by_lead_bucket(holdout, "p50_mw", lower_col="p10_mw", upper_col="p90_mw")}
    for name in bl.BASELINE_LABELS:
        buckets[name] = by_lead_bucket(holdout, name)

    # Pinball on the dimensionless target, which is what the models were fitted against
    # and what makes the score comparable to published GEFCom2014 figures.
    truth = holdout["target"].to_numpy(dtype="float64")
    denom = np.where(holdout["denominator_mw"] > 1e-9, holdout["denominator_mw"], np.nan)
    pinball_scores = {
        q.value: pinball(truth, holdout[f"{q.value}_mw"].to_numpy(dtype="float64") / denom, q.alpha)
        for q in QUANTILES
    }
    pinball_scores = {k: float(np.nanmean([v])) for k, v in pinball_scores.items()}
    pinball_scores["mean"] = float(np.mean(list(pinball_scores.values())))

    return {
        "overall": overall,
        "buckets": buckets,
        "pinball": pinball_scores,
        "holdout": holdout,
    }


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def _fmt_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    header = "| " + " | ".join(label for label, _ in columns) + " |"
    sep = "|" + "|".join("---" if i == 0 else "---:" for i in range(len(columns))) + "|"
    body = []
    for row in rows:
        cells = []
        for _, key in columns:
            value = row.get(key)
            cells.append(f"{value:.2f}" if isinstance(value, float) else str(value))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body])


def _section(tech: Tech, scored: dict, metadata: dict) -> str:
    overall = scored["overall"]
    buckets = scored["buckets"]
    reference = overall["smart_persistence"]["nmae_pct"]

    comparison = [
        {
            "method": "**Model (quantile GBDT)**",
            "nmae": overall["model"]["nmae_pct"],
            "nrmse": overall["model"]["nrmse_pct"],
            "mbe": overall["model"]["mbe_pct"],
            "r2": overall["model"]["r2"],
            "skill": skill_score(overall["model"]["nmae_pct"], reference),
        }
    ]
    for name, label in bl.BASELINE_LABELS.items():
        comparison.append(
            {
                "method": label,
                "nmae": overall[name]["nmae_pct"],
                "nrmse": overall[name]["nrmse_pct"],
                "mbe": overall[name]["mbe_pct"],
                "r2": overall[name]["r2"],
                "skill": skill_score(overall[name]["nmae_pct"], reference),
            }
        )

    lead_rows = []
    for _, row in buckets["model"].iterrows():
        label = row["lead_bucket"]
        entry = {"bucket": label, "n": int(row["n"]), "model": row["nmae_pct"]}
        for name in bl.BASELINE_LABELS:
            match = buckets[name][buckets[name]["lead_bucket"] == label]
            entry[name] = float(match["nmae_pct"].iloc[0]) if len(match) else float("nan")
        entry["skill"] = skill_score(entry["model"], entry["smart_persistence"])
        entry["picp"] = row.get("picp_pct", float("nan"))
        lead_rows.append(entry)

    horizons = metadata.get("horizons_present", [1, 24])
    # `.get` throughout: this report has to keep rendering across metadata schema changes.
    # It has now broken twice on a renamed key - once on `cv_pinball`, once on
    # `holdout_starts` - each time after training had already succeeded, which is the worst
    # moment to lose the write-up of a run that took half an hour.
    holdout_from = str(metadata.get("val_starts") or metadata.get("holdout_starts") or "")[:10]
    lead_note = (
        f"a single nominal {horizons[0]} h lead"
        if horizons[0] == horizons[1]
        else f"genuine {horizons[0]}-{horizons[1]} h leads"
    )

    return f"""
## {tech.value.title()}

Trained on {metadata["n_train_rows"]:,} rows from {len(metadata["sites"])} sites
({metadata["training_window"][0][:10]} to {metadata["training_window"][1][:10]}),
evaluated on {int(overall["model"]["n"]):,} untouched holdout rows{f" from {holdout_from} onward" if holdout_from else ""}.
The corpus carries {lead_note}.

### Overall, holdout

{_fmt_table(comparison, [("Method", "method"), ("nMAE %cap", "nmae"), ("nRMSE %cap", "nrmse"), ("Bias %cap", "mbe"), ("R2", "r2"), ("Skill vs smart persistence %", "skill")])}

Mean pinball loss on the dimensionless target: **{scored["pinball"]["mean"]:.4f}**
(p10 {scored["pinball"]["p10"]:.4f}, p50 {scored["pinball"]["p50"]:.4f}, p90 {scored["pinball"]["p90"]:.4f}).

Prediction interval coverage (p10-p90): **{overall["model"].get("picp_pct", float("nan")):.1f}%**
against a nominal 80%, with a mean width of {overall["model"].get("interval_width_pct", float("nan")):.1f}% of capacity.

### By lead time

{_fmt_table(lead_rows, [("Lead", "bucket"), ("n", "n"), ("Model nMAE", "model"), ("Persistence", "persistence"), ("Smart persist.", "smart_persistence"), ("Climatology", "climatology"), ("Physics only", "physics_only"), ("Skill %", "skill"), ("PICP %", "picp")])}

Top features by gain: {", ".join(list(metadata.get("top_features", {}))[:8])}.
"""


def plot_skill(results: dict[Tech, dict], path: Path) -> Path | None:
    """Model versus baselines by lead time, per technology."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    techs = list(results)
    fig, axes = plt.subplots(1, len(techs), figsize=(6.2 * len(techs), 4.2), squeeze=False)

    for ax, tech in zip(axes[0], techs, strict=True):
        buckets = results[tech]["buckets"]
        labels = [b for b in buckets["model"]["lead_bucket"] if b != "all"]
        x = np.arange(len(labels))

        series = [("model", "Model", "o", 2.4)] + [
            (name, label, "s", 1.2) for name, label in bl.BASELINE_LABELS.items()
        ]
        for name, label, marker, width in series:
            frame = buckets[name]
            values = [
                float(frame[frame["lead_bucket"] == lab]["nmae_pct"].iloc[0]) for lab in labels
            ]
            ax.plot(x, values, marker=marker, linewidth=width, label=label)

        ax.set_xticks(x, labels)
        ax.set_xlabel("Forecast lead time")
        ax.set_ylabel("nMAE (% of installed capacity)")
        ax.set_title(f"{tech.value.title()} - error by lead time")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def generate(out_path: Path | None = None) -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    out_path = out_path or settings.reports_dir / "benchmark.md"

    results: dict[Tech, dict] = {}
    sections: list[str] = []

    for tech in Tech:
        try:
            model = load_model(tech)
        except FileNotFoundError:
            log.warning("no trained %s model; skipping", tech.value)
            continue
        train, holdout = build_holdout_frame(tech)
        scored = score_all(train, holdout, tech)
        results[tech] = scored
        sections.append(_section(tech, scored, model.metadata))
        log.info(
            "%s holdout nMAE %.2f%% vs smart persistence %.2f%%",
            tech.value,
            scored["overall"]["model"]["nmae_pct"],
            scored["overall"]["smart_persistence"]["nmae_pct"],
        )

    if not results:
        raise RuntimeError("no trained models found; run `python -m reip.models.train` first")

    figure = plot_skill(results, settings.reports_dir / "figures" / "skill_by_lead.png")
    figure_rel = figure.relative_to(settings.reports_dir).as_posix() if figure else None

    document = f"""# Forecast benchmark

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
{"".join(sections)}
## Forecast lead time: what is and is not measured

{LEAD_TIME_LIMITATION}
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

{f"![Error by lead time]({figure_rel})" if figure_rel else ""}
"""

    out_path.write_text(document, encoding="utf-8")

    summary = {
        tech.value: {
            "overall": {k: v for k, v in results[tech]["overall"].items()},
            "pinball": results[tech]["pinball"],
        }
        for tech in results
    }
    (settings.reports_dir / "benchmark.json").write_text(
        json.dumps(summary, indent=2, default=float), encoding="utf-8"
    )
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("written:", generate())
