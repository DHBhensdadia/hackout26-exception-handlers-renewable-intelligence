"""Verify the regional scenario ensemble against what actually happened.

Three questions, in order of how badly a wrong answer would matter.

1. **Is the regional ensemble calibrated?** If the true regional total lands outside the
   p10-p90 band far more or far less than 20% of the time, every surplus and shortage
   probability built on it is wrong by the same margin. Checked by coverage and by a rank
   histogram, which shows *how* it is wrong rather than only that it is.

2. **Did the shuffle damage the marginals?** Reordering must not change the set of values at
   any site-hour, only which scenario holds which. Per-site coverage before and after must
   be identical - if it is not, the implementation is wrong.

3. **Was any of this necessary?** The naive quantile sum is scored on the same hours. If it
   were about as good, the machinery would not be worth its complexity.

Verification runs on the holdout with the model's own predictions, so it measures the whole
chain - marginals, copula and aggregation - rather than the shuffle in isolation.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.portfolio import aggregate as aggregate_module
from reip.portfolio import residuals as residual_store
from reip.portfolio.aggregate import (
    DEFAULT_SCENARIOS,
    generate_from_arrays,
    rank_histogram,
)
from reip.schemas import Tech
from reip.sites.registry import SiteRegistry

log = logging.getLogger(__name__)

# Length of each verification window, hours. Matched to the served horizon so the temporal
# dependence being tested is the one the platform actually relies on.
WINDOW_H: int = 72

# Independent windows to score. Drawn from across the holdout rather than consecutively, so
# the result is not dominated by one week's weather.
N_WINDOWS: int = 40


def _regional_frame(tech: Tech, region: str) -> pd.DataFrame:
    """Holdout predictions and truth for one region, one row per (hour, site)."""
    from reip.eval.report import build_holdout_frame

    registry = SiteRegistry.load()
    wanted = {s.site_id for s in registry.by_region(region, tech)}
    if not wanted:
        raise ValueError(f"no {tech.value} sites in {region}")

    _, holdout = build_holdout_frame(tech)
    block = holdout[holdout["site_id"].isin(wanted)]
    if block.empty:
        raise ValueError(f"no holdout rows for {tech.value} in {region}")

    # One lead only. Mixing leads would put several different forecast vintages of the same
    # hour into one regional total, which is not a thing anyone would ever dispatch against.
    lead = int(block["horizon_h"].value_counts().idxmax())
    return block[block["horizon_h"] == lead].copy()


# Share of the holdout timeline used to FIT the dispersion factor. The remainder scores it.
# Fitting and scoring on the same windows would report back whatever coverage was asked for.
CALIB_FRACTION = 0.60


def _windows(times: pd.DatetimeIndex, n: int, seed: int) -> list:
    """Random contiguous windows of WINDOW_H hours, dropping any that span a gap."""
    rng = np.random.default_rng(seed)
    if len(times) <= WINDOW_H:
        return []
    starts = rng.choice(len(times) - WINDOW_H, size=min(n, len(times) - WINDOW_H), replace=False)
    out = []
    for start in starts:
        window = times[start : start + WINDOW_H]
        if (np.diff(window.to_numpy()) == np.timedelta64(1, "h")).all():
            out.append(window)
    return out


def _pivots(block: pd.DataFrame) -> dict:
    return {
        key: block.pivot_table(
            index="valid_time_utc", columns="site_id", values=col, aggfunc="mean"
        ).sort_index()
        for key, col in (
            ("p10", "p10_mw"),
            ("p50", "p50_mw"),
            ("p90", "p90_mw"),
            ("actual", "actual_mw"),
        )
    }


def _coverage_at(dispersion, windows, pivots, sites, caps, tech, store, n_scenarios):
    """Fraction of hours where the true regional total falls inside the p10-p90 band."""
    inside = []
    for window in windows:
        scenarios = generate_from_arrays(
            p10=pivots["p10"].loc[window, sites].to_numpy(dtype="float64"),
            p50=pivots["p50"].loc[window, sites].to_numpy(dtype="float64"),
            p90=pivots["p90"].loc[window, sites].to_numpy(dtype="float64"),
            capacities=caps,
            site_ids=sites,
            valid_times=window,
            horizons=np.full(len(window), WINDOW_H, dtype="int16"),
            tech=tech,
            n_scenarios=n_scenarios,
            seed=int(window[0].value % 2**31),
            store=store,
            dispersion=dispersion,
        )
        truth = pivots["actual"].loc[window, sites].to_numpy(dtype="float64").sum(axis=1)
        total = scenarios.regional_total()
        lo, hi = np.quantile(total, 0.10, axis=0), np.quantile(total, 0.90, axis=0)
        inside.append((truth >= lo) & (truth <= hi))
    return float(np.mean(np.concatenate(inside))) if inside else float("nan")


def calibrate(tech: Tech, regions: list, *, n_scenarios: int = 100, seed: int = 7) -> float:
    """Fit one dispersion factor per technology, on the earlier part of the holdout.

    Pooled across regions rather than fitted per region. The factor corrects a property of
    the forecast error itself - that its magnitude depends on conditions the ensemble does
    not condition on - and that belongs to the technology, not to a state boundary. Fitted
    per region it would rest on a handful of windows each and mostly track noise.

    Searched over a coarse grid rather than solved: coverage is a step function of the
    factor, so there is no gradient to follow, and a grid makes the flatness of the optimum
    visible rather than hiding it behind a converged number.
    """
    from reip.eval.report import build_holdout_frame

    registry = SiteRegistry.load()
    _, holdout = build_holdout_frame(tech)
    store = residual_store.load(tech)

    prepared = []
    for region in regions:
        wanted = {s.site_id for s in registry.by_region(region, tech)}
        block = holdout[holdout["site_id"].isin(wanted)]
        if block.empty:
            continue
        lead = int(block["horizon_h"].value_counts().idxmax())
        block = block[block["horizon_h"] == lead]
        pivots = _pivots(block)
        sites = [
            s
            for s in pivots["p50"].columns
            if s in pivots["actual"].columns and s in store.columns
        ]
        if len(sites) < 4:
            continue
        ok = pivots["actual"][sites].notna().all(axis=1) & pivots["p50"][sites].notna().all(axis=1)
        times = pivots["p50"].index[ok]
        cut = int(len(times) * CALIB_FRACTION)
        windows = _windows(times[:cut], 12, seed)
        if not windows:
            continue
        caps = block.groupby("site_id")["capacity_mw"].first()[sites].to_numpy()
        prepared.append((windows, pivots, sites, caps))

    if not prepared:
        log.warning("%s: nothing to calibrate on; dispersion stays at 1.0", tech.value)
        return 1.0

    best, best_gap = 1.0, float("inf")
    for factor in np.arange(0.8, 2.61, 0.1):
        coverages = [
            _coverage_at(float(factor), w, pv, st, cp, tech, store, n_scenarios)
            for w, pv, st, cp in prepared
        ]
        gap = abs(float(np.nanmean(coverages)) - 0.80)
        if gap < best_gap:
            best, best_gap = round(float(factor), 2), gap

    log.info(
        "%s dispersion %.2f (fitting coverage within %.1f pp of 80%%, %d regions)",
        tech.value,
        best,
        100 * best_gap,
        len(prepared),
    )
    return best


def verify(
    tech: Tech, region: str, *, n_scenarios: int = DEFAULT_SCENARIOS, seed: int = 42
) -> dict:
    frame = _regional_frame(tech, region)
    store = residual_store.load(tech)

    pivot = lambda column: frame.pivot_table(  # noqa: E731
        index="valid_time_utc", columns="site_id", values=column, aggfunc="mean"
    ).sort_index()

    p10, p50, p90 = pivot("p10_mw"), pivot("p50_mw"), pivot("p90_mw")
    actual = pivot("actual_mw")
    caps = frame.groupby("site_id")["capacity_mw"].first()

    sites = [s for s in p50.columns if s in actual.columns]
    times = p50.index
    # Only fully observed hours: a partially reported hour would compare a full forecast
    # against a partial actual and read as a large error that never happened.
    complete = actual[sites].notna().all(axis=1) & p50[sites].notna().all(axis=1)
    times = times[complete]
    if len(times) < WINDOW_H * 2:
        raise ValueError(f"{region}: only {len(times)} complete hours, too few to verify")

    # Score only on the stretch the dispersion factor was NOT fitted on.
    times = times[int(len(times) * CALIB_FRACTION) :]
    dispersion = aggregate_module.load_dispersion(tech)
    rng = np.random.default_rng(seed)
    starts = rng.choice(len(times) - WINDOW_H, size=min(N_WINDOWS, len(times) - WINDOW_H),
                        replace=False)

    inside_copula, inside_naive, ranks, widths_copula, widths_naive = [], [], [], [], []
    per_site_inside_before, per_site_inside_after = [], []

    for start in starts:
        window = times[start : start + WINDOW_H]
        if (np.diff(window.astype("int64")) != 3_600_000_000_000).any():
            continue  # not contiguous; splicing across a gap would fake a trajectory

        scenarios = generate_from_arrays(
            p10=p10.loc[window, sites].to_numpy(dtype="float64"),
            p50=p50.loc[window, sites].to_numpy(dtype="float64"),
            p90=p90.loc[window, sites].to_numpy(dtype="float64"),
            capacities=caps[sites].to_numpy(dtype="float64"),
            site_ids=sites,
            valid_times=window,
            horizons=np.full(len(window), WINDOW_H, dtype="int16"),
            tech=tech,
            n_scenarios=n_scenarios,
            seed=int(start),
            store=store,
            dispersion=dispersion,
        )

        truth_total = actual.loc[window, sites].to_numpy(dtype="float64").sum(axis=1)
        total = scenarios.regional_total()

        lo, hi = np.quantile(total, 0.10, axis=0), np.quantile(total, 0.90, axis=0)
        inside_copula.append((truth_total >= lo) & (truth_total <= hi))
        widths_copula.append(hi - lo)
        ranks.append(rank_histogram(truth_total, total))

        # The naive alternative, on identical hours.
        naive_lo = p10.loc[window, sites].to_numpy(dtype="float64").sum(axis=1)
        naive_hi = p90.loc[window, sites].to_numpy(dtype="float64").sum(axis=1)
        inside_naive.append((truth_total >= naive_lo) & (truth_total <= naive_hi))
        widths_naive.append(naive_hi - naive_lo)

        # Marginal preservation: per-site coverage from the model's own quantiles, against
        # per-site coverage recovered from the shuffled ensemble. These must agree.
        truth_site = actual.loc[window, sites].to_numpy(dtype="float64")
        per_site_inside_before.append(
            (truth_site >= p10.loc[window, sites].to_numpy())
            & (truth_site <= p90.loc[window, sites].to_numpy())
        )
        ens_lo = np.quantile(scenarios.values, 0.10, axis=0)
        ens_hi = np.quantile(scenarios.values, 0.90, axis=0)
        per_site_inside_after.append((truth_site >= ens_lo) & (truth_site <= ens_hi))

    if not inside_copula:
        raise ValueError(f"{region}: no contiguous {WINDOW_H}-hour windows in the holdout")

    histogram = np.sum(ranks, axis=0)
    result = {
        "tech": tech.value,
        "region": region,
        "n_sites": len(sites),
        "n_windows": len(inside_copula),
        "n_scenarios": n_scenarios,
        "dispersion": dispersion,
        "copula": {
            "coverage": round(float(np.mean(np.concatenate(inside_copula))), 4),
            "mean_width_mw": round(float(np.mean(np.concatenate(widths_copula))), 2),
        },
        "naive_quantile_sum": {
            "coverage": round(float(np.mean(np.concatenate(inside_naive))), 4),
            "mean_width_mw": round(float(np.mean(np.concatenate(widths_naive))), 2),
        },
        "marginals_preserved": {
            "per_site_coverage_before": round(
                float(np.mean(np.concatenate(per_site_inside_before))), 4
            ),
            "per_site_coverage_after": round(
                float(np.mean(np.concatenate(per_site_inside_after))), 4
            ),
        },
        "rank_histogram": histogram.tolist(),
        # A flat histogram is the calibrated case. Deviation is measured against the flat
        # expectation, so one number says how far off it is regardless of bin count.
        "rank_histogram_flatness": round(
            float(np.std(histogram / histogram.sum()) * len(histogram)), 4
        ),
    }

    width_ratio = result["naive_quantile_sum"]["mean_width_mw"] / max(
        result["copula"]["mean_width_mw"], 1e-9
    )
    result["naive_width_ratio"] = round(width_ratio, 3)

    log.info(
        "%s %s: %d sites, %d windows | copula coverage %.1f%% width %.0f MW | "
        "naive coverage %.1f%% width %.0f MW (%.1fx wider)",
        tech.value,
        region,
        len(sites),
        len(inside_copula),
        100 * result["copula"]["coverage"],
        result["copula"]["mean_width_mw"],
        100 * result["naive_quantile_sum"]["coverage"],
        result["naive_quantile_sum"]["mean_width_mw"],
        width_ratio,
    )
    return result


def main(regions: list[str] | None = None, *, fit: bool = True) -> dict:
    settings = get_settings()
    registry = SiteRegistry.load()
    regions = regions or registry.regions()

    if fit:
        factors = {t.value: calibrate(t, regions) for t in Tech}
        path = settings.artifacts_dir / aggregate_module.DISPERSION_FILE
        path.write_text(json.dumps(factors, indent=2), encoding="utf-8")
        log.info("wrote %s: %s", path, factors)

    results = []
    for region in regions:
        for tech in Tech:
            if len(registry.by_region(region, tech)) < 4:
                continue
            try:
                results.append(verify(tech, region))
            except (ValueError, FileNotFoundError) as exc:
                log.warning("%s %s: skipped (%s)", tech.value, region, exc)

    out = settings.reports_dir / "scenario_verification.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    log.info("wrote %s", out)
    return {"results": results}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Verify regional scenario calibration")
    parser.add_argument("--region", action="append")
    parser.add_argument(
        "--no-fit", action="store_true", help="score with the stored factor, do not refit"
    )
    args = parser.parse_args()

    output = main(args.region, fit=not args.no_fit)
    print(json.dumps(output, indent=2, default=str))
