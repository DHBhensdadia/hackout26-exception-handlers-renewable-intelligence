"""The headline result: what planning against uncertainty is actually worth.

Every earlier stage of this platform argued that uncertainty should be modelled rather than
averaged away - quantile models instead of point forecasts, conformal calibration, coherent
scenarios instead of summed quantiles. Each was justified on its own terms. None of them
answered the only question a decision-maker really has, which is whether any of it changes
what they should do, and by how much.

This measures that, in dollars, against real prices and real outcomes.

Three dispatch policies over the same hours:

* **Wait-and-see** - perfect foresight. A lower bound nobody can reach.
* **Stochastic** - plan against all 200 scenarios. Achievable today.
* **Expected-value** - plan against the median forecast, which is what a platform without
  any of this work would do.

`VSS = expected-value cost - stochastic cost` is the answer. `EVPI = stochastic - perfect`
bounds what any further forecasting improvement could ever add, which is a useful thing to
know before spending months on one.

A caveat worth stating up front: **VSS is regime-dependent, and can legitimately be zero.**
With unconstrained interconnectors every imbalance is settled at the spot price, nothing is
scarce, and how well a battery is dispatched does not matter. At the other extreme, if the
region is so short that every scenario fails, a battery too small to change that is worth
nothing either. Value lives in between - which is where SA1 sits, and why it is the demo
region. Reporting the zero cases alongside the positive one is the honest presentation.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from reip.balance import residual as balance
from reip.config import get_settings
from reip.eval.balance import prepare_region
from reip.eval.scenarios import WINDOW_H, _windows
from reip.portfolio.aggregate import generate_from_arrays
from reip.storage.asset import GridLimits, StorageAsset, grid_limits_from_market
from reip.storage.dispatch import value_of_stochastic_solution

log = logging.getLogger(__name__)

# Fewer scenarios than the balance module uses. The LP grows linearly in scenarios and is
# solved four times per window; 60 keeps a full evaluation to minutes while leaving the
# ensemble wide enough that the tails still carry the events that create value.
N_SCENARIOS: int = 60
N_WINDOWS: int = 12

HOURS_PER_YEAR: int = 8760


def _window_ensembles(region: str, window: pd.DatetimeIndex, prepared: dict, n_scenarios: int):
    """Renewable and demand ensembles for one window, on shared historical hours."""
    generation, block_starts = {}, None
    for tech, data in prepared["tech_data"].items():
        scenarios = generate_from_arrays(
            p10=data["pivots"]["p10"].loc[window, data["sites"]].to_numpy(dtype="float64"),
            p50=data["pivots"]["p50"].loc[window, data["sites"]].to_numpy(dtype="float64"),
            p90=data["pivots"]["p90"].loc[window, data["sites"]].to_numpy(dtype="float64"),
            capacities=data["caps"],
            site_ids=data["sites"],
            valid_times=window,
            horizons=np.full(len(window), WINDOW_H, dtype="int16"),
            tech=tech,
            n_scenarios=n_scenarios,
            seed=int(window[0].value % 2**31),
            store=data["store"],
            dispersion=data["dispersion"],
        )
        generation[tech] = scenarios
        if block_starts is None:
            block_starts = scenarios.block_starts

    renewable = np.sum([s.regional_total() for s in generation.values()], axis=0)
    demand = balance.demand_scenarios(
        region,
        prepared["demand_frame"].loc[window, "p50_mw"].to_numpy(dtype="float64"),
        window,
        n_scenarios=n_scenarios,
        block_starts=block_starts,
        peak_mw=prepared["peak"],
        store=prepared["demand_store"],
    )
    return renewable, demand


def evaluate(
    region: str,
    *,
    asset: StorageAsset | None = None,
    grid: GridLimits | None = None,
    n_windows: int = N_WINDOWS,
    n_scenarios: int = N_SCENARIOS,
    seed: int = 23,
) -> dict:
    """Run all three dispatch policies over sampled windows and aggregate."""
    asset = asset or StorageAsset()
    grid = grid or grid_limits_from_market(region)

    settings = get_settings()
    market = pd.read_parquet(settings.data_canonical / "aemo_market.parquet")
    prices = (
        market[market["region"] == region]
        .drop_duplicates("valid_time_utc")
        .set_index("valid_time_utc")["rrp_aud_mwh"]
        .sort_index()
    )

    prepared = prepare_region(region)
    common = prepared["common"].intersection(prices.dropna().index)
    if len(common) < WINDOW_H * 2:
        raise ValueError(f"{region}: only {len(common)} usable hours")

    rows = []
    for window in _windows(common, n_windows, seed):
        renewable, demand = _window_ensembles(region, window, prepared, n_scenarios)
        result = value_of_stochastic_solution(
            renewable_mw=renewable,
            demand_mw=demand,
            price_aud_mwh=prices.loc[window].to_numpy(dtype="float64"),
            asset=asset,
            grid=grid,
            dispatchable_mw=prepared["headroom"],
        )
        result["from_utc"] = pd.Timestamp(window[0]).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(result)

    if not rows:
        raise ValueError(f"{region}: no contiguous {WINDOW_H}-hour windows available")

    frame = pd.DataFrame(rows)
    hours = int(frame["horizon_h"].sum())
    scale = HOURS_PER_YEAR / hours

    summary = {
        "region": region,
        "n_windows": len(rows),
        "n_scenarios": n_scenarios,
        "hours_evaluated": hours,
        "asset": {
            "energy_mwh": asset.energy_mwh,
            "power_mw": asset.power_mw,
            "duration_h": round(asset.duration_h, 2),
            "efficiency": asset.efficiency,
        },
        "grid": {
            "import_limit_mw": round(grid.import_limit_mw, 1),
            "export_limit_mw": round(grid.export_limit_mw, 1),
            "source": "measured from NETINTERCHANGE",
        },
        "dispatchable_headroom_mw": round(prepared["headroom"], 1),
        "cost_aud_per_window": {
            "wait_and_see": round(float(frame["wait_and_see_aud"].mean()), 2),
            "stochastic": round(float(frame["stochastic_aud"].mean()), 2),
            "expected_value": round(float(frame["expected_value_solution_aud"].mean()), 2),
        },
        "vss_aud_total": round(float(frame["vss_aud"].sum()), 2),
        "evpi_aud_total": round(float(frame["evpi_aud"].sum()), 2),
        # Annualised by simple scaling. The windows are sampled from across the holdout
        # rather than being a contiguous year, so this is an extrapolation and is labelled
        # as one; seasonal concentration of value would not show up in it.
        "vss_aud_per_year": round(float(frame["vss_aud"].sum()) * scale, 0),
        "evpi_aud_per_year": round(float(frame["evpi_aud"].sum()) * scale, 0),
        "windows_with_positive_vss": int((frame["vss_aud"] > 1.0).sum()),
        "decision_differed_in_hour_1": int(
            (frame["committed_action"] != frame["deterministic_committed_action"]).sum()
        ),
        "windows": rows,
    }

    log.info(
        "%s: VSS %s AUD over %d h (%s AUD/yr) | EVPI %s AUD/yr | hour-1 decision differed in "
        "%d of %d windows",
        region,
        f"{summary['vss_aud_total']:,.0f}",
        hours,
        f"{summary['vss_aud_per_year']:,.0f}",
        f"{summary['evpi_aud_per_year']:,.0f}",
        summary["decision_differed_in_hour_1"],
        len(rows),
    )
    return summary


def main(regions: list[str] | None = None, **kwargs) -> list[dict]:
    settings = get_settings()
    results = []
    for region in regions or ["SA1", "NSW1"]:
        try:
            results.append(evaluate(region, **kwargs))
        except (ValueError, FileNotFoundError, KeyError, RuntimeError) as exc:
            log.warning("%s: skipped (%s)", region, exc)

    path = settings.reports_dir / "vss.json"
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    log.info("wrote %s", path)
    return results


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Value of the stochastic solution")
    parser.add_argument("--region", action="append")
    parser.add_argument("--energy-mwh", type=float, default=200.0)
    parser.add_argument("--power-mw", type=float, default=100.0)
    parser.add_argument("--windows", type=int, default=N_WINDOWS)
    args = parser.parse_args()

    output = main(
        args.region,
        asset=StorageAsset(energy_mwh=args.energy_mwh, power_mw=args.power_mw),
        n_windows=args.windows,
    )
    for entry in output:
        print(
            f"{entry['region']}: VSS {entry['vss_aud_per_year']:,.0f} AUD/yr, "
            f"EVPI {entry['evpi_aud_per_year']:,.0f} AUD/yr"
        )
