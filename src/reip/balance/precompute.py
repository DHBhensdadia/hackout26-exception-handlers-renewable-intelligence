"""Precompute regional balance windows for the API to serve.

The balance chain is not something that can run inside an HTTP request. Producing one
region-hour means forecasting every plant in the region, drawing a coherent scenario
ensemble across all of them, forecasting demand, and counting outcomes - minutes of work,
not milliseconds.

It is also, today, not a *live* chain. The demand model reads load at the issue time and at
24 and 168 hours before it, and the market corpus ends 2026-08-31 while the calendar does
not. Until the AEMO ingest runs to the present, there is no honest way to produce a demand
forecast for tomorrow.

So the served balance is a **replay**: a real 72-hour window, real metered demand, real spot
prices, real forecasts as they stood at that issue time. Every number in it happened. The
payload says which window it is and the dashboard shows that, rather than implying a
forecast for tonight.

Extending the ingest to the present is what makes this live, and nothing else in the chain
has to change when it does.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from reip.balance import residual as balance
from reip.config import MODEL_VERSION, get_settings
from reip.schemas import Tech

log = logging.getLogger(__name__)

# Scenarios per window. Matches what the verification in `eval/balance.py` scored, so the
# reliability figures quoted in the API contract describe what is actually served.
N_SCENARIOS: int = 200

# Hours per window - the horizon the platform promises.
WINDOW_H: int = 72


def artifact_path(region: str, directory: Path | None = None) -> Path:
    directory = directory or get_settings().data_canonical
    return directory / f"balance_{region}.json"


def ensemble_path(region: str, directory: Path | None = None) -> Path:
    """Where the raw scenario ensembles are kept, for the dispatch optimiser.

    Saved separately and compressed rather than inlined in the JSON: 200 scenarios x 72
    hours x two series is a quarter of a megabyte of numbers nobody reading the balance
    payload wants, and the optimiser wants them as arrays rather than as parsed text.
    """
    directory = directory or get_settings().data_canonical
    return directory / f"ensemble_{region}.npz"


def build(region: str, *, n_scenarios: int = N_SCENARIOS, seed: int = 3) -> dict:
    """Compute one balance window for a region and return the API payload."""
    from reip.eval.balance import prepare_region
    from reip.eval.scenarios import _windows
    from reip.portfolio.aggregate import generate_from_arrays, load_dispersion

    prepared = prepare_region(region)
    usable = prepared["common"]
    if len(usable) < WINDOW_H:
        raise ValueError(f"{region}: only {len(usable)} usable hours, need {WINDOW_H}")

    # The most recent complete window, not a random one: a dashboard showing "the latest
    # analysis" should show the latest, and a sampled window would move on every rebuild.
    window = usable[-WINDOW_H:]
    if (np.diff(window.to_numpy()) != np.timedelta64(1, "h")).any():
        candidates = _windows(usable, 20, seed)
        if not candidates:
            raise ValueError(f"{region}: no contiguous {WINDOW_H}-hour window")
        window = max(candidates, key=lambda w: w[0])
        log.info("%s: latest hours are not contiguous; using %s", region, window[0])

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
            seed=seed,
            store=data["store"],
            dispersion=load_dispersion(tech),
        )
        generation[tech] = scenarios
        if block_starts is None:
            block_starts = scenarios.block_starts

    result = balance.compute(
        region=region,
        generation=generation,
        demand_p50_mw=prepared["demand_frame"].loc[window, "p50_mw"].to_numpy(dtype="float64"),
        demand_peak_mw=prepared["peak"],
        valid_times=window,
        # Horizons run 1..72 across the window: this is what a forecast issued at the start
        # of it would have covered.
        horizons=np.arange(1, len(window) + 1, dtype="int16"),
        block_starts=block_starts,
        headroom_mw=prepared["headroom"],
        demand_store=prepared["demand_store"],
    )

    frame = result.frame.copy()
    frame["valid_time_utc"] = pd.DatetimeIndex(frame["valid_time_utc"]).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    # Probabilities keep four decimals so expected = probability x conditional stays visibly
    # true in the payload; two decimals breaks the identity on small probabilities.
    probability_columns = [c for c in frame.columns if c.startswith("p_")]
    other = [c for c in frame.select_dtypes("number").columns if c not in probability_columns]
    frame[probability_columns] = frame[probability_columns].round(4)
    frame[other] = frame[other].round(2)

    actual = _actual_series(prepared, window)

    # Keep the raw ensembles and the price series. The dispatch optimiser needs the joint
    # trajectories, not the marginal quantiles the payload carries - a battery is dispatched
    # against a path, and a per-hour quantile is not one.
    renewable_ensemble = np.sum([s.regional_total() for s in generation.values()], axis=0)
    demand_ensemble = balance.demand_scenarios(
        region,
        prepared["demand_frame"].loc[window, "p50_mw"].to_numpy(dtype="float64"),
        window,
        n_scenarios=n_scenarios,
        block_starts=block_starts,
        peak_mw=prepared["peak"],
        store=prepared["demand_store"],
    )
    market = pd.read_parquet(get_settings().data_canonical / "aemo_market.parquet")
    prices = (
        market[market["region"] == region]
        .drop_duplicates("valid_time_utc")
        .set_index("valid_time_utc")["rrp_aud_mwh"]
        .reindex(window)
        .ffill()
        .bfill()
        .to_numpy(dtype="float64")
    )
    np.savez_compressed(
        ensemble_path(region),
        renewable_mw=renewable_ensemble,
        demand_mw=demand_ensemble,
        price_aud_mwh=prices,
        headroom_mw=np.array([prepared["headroom"]]),
    )

    # Demand quantiles recovered from the ensemble, so the demand endpoint and the balance
    # describe the same draws rather than two independent ones.
    demand_quantiles = {
        f"p{int(q * 100):02d}_mw": np.quantile(demand_ensemble, q, axis=0).round(2).tolist()
        for q in (0.10, 0.50, 0.90)
    }

    payload = {
        "region": region,
        "issue_time_utc": pd.Timestamp(window[0]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": MODEL_VERSION,
        "n_scenarios": result.n_scenarios,
        "dispatchable_headroom_mw": round(result.headroom_mw, 1),
        "technologies": [t.value for t in generation],
        # Stated plainly in the payload, so a UI cannot present a replay as tonight's
        # forecast without ignoring a field that says otherwise.
        "data_mode": "replay",
        "data_note": (
            "A real 72-hour window replayed from held-out history: real forecasts as they "
            "stood at the issue time, against real metered demand. Live operation needs the "
            "AEMO market ingest run to the present."
        ),
        "demand": {
            "valid_time_utc": frame["valid_time_utc"].tolist(),
            **demand_quantiles,
            "peak_mw": round(float(prepared["peak"]), 1),
        },
        "points": frame.to_dict("records"),
        "events": (
            balance.event_runs(result.frame, "p_surplus")
            + balance.event_runs(result.frame, "p_shortage")
        ),
        "actual": actual,
    }
    log.info(
        "%s: %s to %s | %d events | headroom %.0f MW",
        region,
        payload["issue_time_utc"],
        frame["valid_time_utc"].iloc[-1],
        len(payload["events"]),
        result.headroom_mw,
    )
    return payload


def _actual_series(prepared: dict, window: pd.DatetimeIndex) -> list[dict]:
    """What actually happened over the window.

    Included because this is a replay, and a replay that hides the outcome wastes its one
    advantage over a live forecast: the reader can see whether the band contained the truth.
    """
    renewable = np.zeros(len(window))
    for data in prepared["tech_data"].values():
        renewable = renewable + (
            data["pivots"]["actual"].loc[window, data["sites"]].to_numpy(dtype="float64").sum(axis=1)
        )
    demand = prepared["demand_frame"].loc[window, "actual_mw"].to_numpy(dtype="float64")
    return [
        {
            "valid_time_utc": pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "renewable_mw": round(float(r), 2),
            "demand_mw": round(float(d), 2),
            "residual_mw": round(float(d - r), 2),
        }
        for t, r, d in zip(window, renewable, demand, strict=True)
    ]


def main(regions: list[str] | None = None) -> dict[str, Path]:
    from reip.sites.registry import SiteRegistry

    registry = SiteRegistry.load()
    written: dict[str, Path] = {}
    for region in regions or registry.regions():
        if sum(len(registry.by_region(region, t)) for t in Tech) < 4:
            continue
        try:
            payload = build(region)
        except (ValueError, FileNotFoundError, KeyError) as exc:
            log.warning("%s: skipped (%s)", region, exc)
            continue
        path = artifact_path(region)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written[region] = path
    log.info("wrote %d region files", len(written))
    return written


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Precompute regional balance windows")
    parser.add_argument("--region", action="append")
    args = parser.parse_args()

    for region, path in main(args.region).items():
        print(f"{region}: {path}")
