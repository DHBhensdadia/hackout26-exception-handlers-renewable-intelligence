"""Verify the balance probabilities against what actually happened.

A probability that has not been reliability-checked is decoration. "70% chance of surplus"
is only worth printing if, across the hours where the platform said 70%, surplus occurred
about 70% of the time.

Two scores, because they answer different questions:

* **Brier score** - mean squared error of the probability. Lower is better, and it is
  scored against climatology, the base rate of the event. Beating climatology is the bar:
  a model that always predicts the long-run average is not forecasting.
* **Reliability diagram** - the probabilities bucketed, each bucket's predicted rate
  against its observed rate. Brier can look respectable while the probabilities are
  systematically over- or under-confident; the diagram shows which.
"""

from __future__ import annotations

import json
import logging

import numpy as np

from reip.balance import calibration
from reip.balance import residual as balance
from reip.config import get_settings
from reip.eval.scenarios import CALIB_FRACTION, WINDOW_H, _pivots, _windows
from reip.models.demand.predict import holdout_predictions, load_demand_model
from reip.portfolio import residuals as residual_store
from reip.portfolio.aggregate import generate_from_arrays, load_dispersion
from reip.schemas import Tech
from reip.sites.registry import SiteRegistry

log = logging.getLogger(__name__)

N_WINDOWS: int = 30
N_SCENARIOS: int = 200
RELIABILITY_BINS: int = 5


def _brier(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.mean((probabilities - outcomes) ** 2))


def _reliability(probabilities: np.ndarray, outcomes: np.ndarray, bins: int) -> list[dict]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (probabilities >= lo) & (probabilities < hi if hi < 1.0 else probabilities <= hi)
        if not mask.any():
            continue
        rows.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": int(mask.sum()),
                "predicted": round(float(probabilities[mask].mean()), 3),
                "observed": round(float(outcomes[mask].mean()), 3),
            }
        )
    return rows


def _score(region: str, *, n_windows: int, seed: int, calibrate: bool, scored_half: bool) -> dict:
    """Score surplus and shortage probabilities for one region against outcomes."""
    from reip.eval.report import build_holdout_frame

    registry = SiteRegistry.load()
    demand_model = load_demand_model()
    if region not in demand_model.metadata["regions"]:
        raise ValueError(f"no demand model for {region}")

    demand_frame = holdout_predictions(region).set_index("valid_time_utc").sort_index()
    demand_store = residual_store.load_demand()
    headroom = balance.dispatchable_headroom(region)
    peak = demand_model.peak_mw(region)

    # Per-technology holdout predictions and the residual stores behind them.
    tech_data = {}
    for tech in Tech:
        sites_in_region = {s.site_id for s in registry.by_region(region, tech)}
        if len(sites_in_region) < 4:
            continue
        _, holdout = build_holdout_frame(tech)
        block = holdout[holdout["site_id"].isin(sites_in_region)]
        if block.empty:
            continue
        lead = int(block["horizon_h"].value_counts().idxmax())
        block = block[block["horizon_h"] == lead]
        store = residual_store.load(tech)
        pivots = _pivots(block)
        sites = [
            s for s in pivots["p50"].columns
            if s in pivots["actual"].columns and s in store.columns
        ]
        if len(sites) < 4:
            continue
        tech_data[tech] = {
            "pivots": pivots,
            "sites": sites,
            "store": store,
            "caps": block.groupby("site_id")["capacity_mw"].first()[sites].to_numpy(),
            "dispersion": load_dispersion(tech),
        }

    if not tech_data:
        raise ValueError(f"{region}: no technology has enough sites to balance")

    # Hours where every input is present.
    common = None
    for data in tech_data.values():
        ok = (
            data["pivots"]["actual"][data["sites"]].notna().all(axis=1)
            & data["pivots"]["p50"][data["sites"]].notna().all(axis=1)
        )
        times = data["pivots"]["p50"].index[ok]
        common = times if common is None else common.intersection(times)
    common = common.intersection(demand_frame.index)
    # The earlier stretch fits the reliability map; the later one scores it.
    cut = int(len(common) * CALIB_FRACTION)
    common = common[cut:] if scored_half else common[:cut]
    if len(common) < WINDOW_H * 2:
        raise ValueError(f"{region}: only {len(common)} usable hours")

    p_surplus, p_shortage, was_surplus, was_shortage = [], [], [], []
    coupled_windows = 0

    for window in _windows(common, n_windows, seed):
        generation, block_starts = {}, None
        for tech, data in tech_data.items():
            scenarios = generate_from_arrays(
                p10=data["pivots"]["p10"].loc[window, data["sites"]].to_numpy(dtype="float64"),
                p50=data["pivots"]["p50"].loc[window, data["sites"]].to_numpy(dtype="float64"),
                p90=data["pivots"]["p90"].loc[window, data["sites"]].to_numpy(dtype="float64"),
                capacities=data["caps"],
                site_ids=data["sites"],
                valid_times=window,
                horizons=np.full(len(window), WINDOW_H, dtype="int16"),
                tech=tech,
                n_scenarios=N_SCENARIOS,
                seed=int(window[0].value % 2**31),
                store=data["store"],
                dispersion=data["dispersion"],
            )
            generation[tech] = scenarios
            # Every technology draws from the same historical hours as the first, so a
            # windless overcast afternoon stays one event across solar, wind and demand.
            if block_starts is None:
                block_starts = scenarios.block_starts

        result = balance.compute(
            region=region,
            generation=generation,
            demand_p50_mw=demand_frame.loc[window, "p50_mw"].to_numpy(dtype="float64"),
            demand_peak_mw=peak,
            valid_times=window,
            horizons=np.full(len(window), WINDOW_H, dtype="int16"),
            block_starts=block_starts,
            headroom_mw=headroom,
            demand_store=demand_store,
            calibrate=calibrate,
        )
        coupled_windows += 1

        actual_renewable = sum(
            data["pivots"]["actual"].loc[window, data["sites"]].to_numpy(dtype="float64").sum(axis=1)
            for data in tech_data.values()
        )
        actual_demand = demand_frame.loc[window, "actual_mw"].to_numpy(dtype="float64")
        actual_residual = actual_demand - actual_renewable

        p_surplus.append(result.frame["p_surplus"].to_numpy())
        p_shortage.append(result.frame["p_shortage"].to_numpy())
        was_surplus.append((actual_residual < 0.0).astype("float64"))
        was_shortage.append((actual_residual > headroom).astype("float64"))

    ps, pt = np.concatenate(p_surplus), np.concatenate(p_shortage)
    os_, ot = np.concatenate(was_surplus), np.concatenate(was_shortage)

    out = {
        "region": region,
        "calibrated": calibrate,
        "n_windows": coupled_windows,
        "n_hours": int(len(ps)),
        "headroom_mw": round(headroom, 1),
        "technologies": [t.value for t in tech_data],
    }
    for name, prob, outcome in (("surplus", ps, os_), ("shortage", pt, ot)):
        base_rate = float(outcome.mean())
        climatology = _brier(np.full_like(prob, base_rate), outcome)
        # An event that never occurred has a climatology Brier of zero, and skill against it
        # is 0/0. Reported as null rather than as a triumphant 100%: NSW1 simply never sees
        # renewable surplus at its current penetration, which is a fact about the region and
        # not a forecasting achievement.
        degenerate = climatology < 1e-9
        out[name] = {
            "base_rate": round(base_rate, 4),
            "brier": round(_brier(prob, outcome), 4),
            "brier_climatology": round(climatology, 4),
            "skill_vs_climatology": (
                None if degenerate else round(1 - _brier(prob, outcome) / climatology, 4)
            ),
            "note": "event never occurred in the scored window" if degenerate else None,
            "reliability": _reliability(prob, outcome, RELIABILITY_BINS),
            "_probabilities": prob,
            "_outcomes": outcome,
        }
        skill = out[name]["skill_vs_climatology"]
        log.info(
            "%s %s: base rate %.1f%% | Brier %.4f vs climatology %.4f (skill %s)",
            region, name, 100 * base_rate, out[name]["brier"],
            out[name]["brier_climatology"],
            "n/a - never occurred" if skill is None else f"{100 * skill:+.1f}%",
        )
    return out


def verify(region: str, *, n_windows: int = N_WINDOWS, seed: int = 11) -> dict:
    """Score the calibrated probabilities on the later stretch of the holdout."""
    return _score(region, n_windows=n_windows, seed=seed, calibrate=True, scored_half=True)


def fit_calibration(regions: list[str], *, n_windows: int = N_WINDOWS, seed: int = 5) -> dict:
    """Fit the reliability map on the EARLIER stretch, which verification never scores."""
    mappings: dict = {}
    for region in regions:
        try:
            raw = _score(region, n_windows=n_windows, seed=seed, calibrate=False, scored_half=False)
        except (ValueError, FileNotFoundError, KeyError) as exc:
            log.warning("%s: not calibrated (%s)", region, exc)
            continue
        mappings[region] = {
            event: calibration.fit(raw[event]["_probabilities"], raw[event]["_outcomes"])
            for event in ("surplus", "shortage")
        }
    calibration.save(mappings)
    return mappings


def main(regions: list[str] | None = None, *, fit: bool = True) -> list[dict]:
    settings = get_settings()
    regions = regions or ["SA1", "NSW1"]

    if fit:
        fit_calibration(regions)

    results = []
    for region in regions:
        try:
            entry = verify(region)
            for event in ("surplus", "shortage"):
                entry[event].pop("_probabilities", None)
                entry[event].pop("_outcomes", None)
            results.append(entry)
        except (ValueError, FileNotFoundError, KeyError) as exc:
            log.warning("%s: skipped (%s)", region, exc)

    path = settings.reports_dir / "balance_verification.json"
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    log.info("wrote %s", path)
    return results


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Verify surplus/shortage probabilities")
    parser.add_argument("--region", action="append")
    parser.add_argument("--no-fit", action="store_true")
    args = parser.parse_args()
    print(json.dumps(main(args.region, fit=not args.no_fit), indent=2, default=str)[:4000])
