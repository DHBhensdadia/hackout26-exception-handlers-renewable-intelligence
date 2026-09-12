"""Regional energy balance: residual load, surplus and shortage, as probabilities.

Spec module 2. The forecast alone is not a decision - this is the step that asks whether
tomorrow's generation is actually wanted.

    residual_load = demand - renewable generation

Negative residual load is surplus: more renewable output than the region can absorb, which
ends as storage charging, export, or curtailment. Residual load above the dispatchable
headroom is shortage: the non-renewable fleet cannot cover the gap.

**Everything is computed per scenario, then counted.** A p50 forecast can only say whether
the expected case is short; an operator needs to know how likely a shortage is, which
cannot be read off a median. Every quantity here is an empirical frequency or expectation
over the ensemble, not a transformation of a point forecast.

**Demand and generation errors are drawn from the same historical hours.** Both residual
stores are indexed on the same clock, and a scenario takes block *i* from each. A hot still
afternoon that lifts demand while dropping wind output is one event in the record, and
sampling the two independently would tear it in half - understating exactly the joint
condition that causes shortages. Nothing models the coupling; it survives because the
sample is never broken apart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from reip.balance import calibration
from reip.config import get_settings
from reip.portfolio import residuals as residual_store
from reip.portfolio.aggregate import ScenarioSet
from reip.schemas import Tech

log = logging.getLogger(__name__)

# Quantile of historical dispatchable headroom used as the shortage threshold.
#
# `AVAILABLEGENERATION` minus the intermittent fleet's unconstrained forecast is what the
# dispatchable plant could have delivered. A low quantile rather than the mean, because a
# shortage call should assume the fleet is in a normal-to-tight state rather than an
# unusually generous one.
HEADROOM_QUANTILE: float = 0.25

# Minimum run length, in hours, for a surplus or shortage to be worth reporting as an
# event. A single hour above threshold is noise in an ensemble; two consecutive hours is a
# period someone would act on.
MIN_EVENT_HOURS: int = 2


@dataclass(frozen=True)
class BalanceResult:
    """Hourly balance for one region, with everything derived from the ensemble."""

    frame: pd.DataFrame
    region: str
    n_scenarios: int
    headroom_mw: float

    def surplus_hours(self, threshold: float = 0.5) -> pd.DataFrame:
        return self.frame[self.frame["p_surplus"] >= threshold]

    def shortage_hours(self, threshold: float = 0.5) -> pd.DataFrame:
        return self.frame[self.frame["p_shortage"] >= threshold]


def dispatchable_headroom(region: str, market: pd.DataFrame | None = None) -> float:
    """Measured dispatchable capacity above the intermittent fleet, in MW.

    Taken from the market corpus rather than configured. `AVAILABLEGENERATION` is what the
    region could have dispatched in total; subtracting the solar and wind unconstrained
    forecasts leaves what the dispatchable plant offered. Where those columns are absent
    the function returns 0.0 and the shortage test reduces to "renewables alone cannot meet
    demand", which is a weaker but still meaningful statement - and one the caller can see
    in the returned value rather than having to infer.
    """
    if market is None:
        market = pd.read_parquet(get_settings().data_canonical / "aemo_market.parquet")

    block = market[market["region"] == region]
    needed = {"available_generation_mw", "solar_uigf_mw", "wind_uigf_mw"}
    if block.empty or not needed.issubset(block.columns):
        log.warning("%s: no dispatchable headroom available; shortage threshold set to 0", region)
        return 0.0

    headroom = (
        block["available_generation_mw"]
        - block["solar_uigf_mw"].fillna(0.0)
        - block["wind_uigf_mw"].fillna(0.0)
    ).dropna()
    if headroom.empty:
        return 0.0
    return float(max(headroom.quantile(HEADROOM_QUANTILE), 0.0))


def demand_scenarios(
    region: str,
    p50_mw: np.ndarray,
    valid_times: pd.DatetimeIndex,
    *,
    n_scenarios: int,
    block_starts: pd.DatetimeIndex,
    peak_mw: float,
    dispersion: float = 1.0,
    store: pd.DataFrame | None = None,
) -> np.ndarray:
    """Demand ensemble, `(scenario, hour)`, using caller-supplied historical blocks.

    `block_starts` comes from the generation ensemble. Reusing the same indices is what
    keeps demand error and generation error on the same historical hours.
    """
    store = residual_store.load_demand() if store is None else store
    if region not in store.columns:
        log.warning("%s absent from the demand residual store; demand carried at p50", region)
        return np.repeat(p50_mw[None, :], n_scenarios, axis=0)

    series = store[region].dropna().sort_index()
    n_hours = len(valid_times)

    # Look each generation block's start hour up in the demand store by timestamp, and keep
    # only those where the full window is present. Any that are missing fall back to the
    # nearest available block rather than to zero error, so the ensemble keeps its spread.
    positions = series.index.get_indexer(pd.DatetimeIndex(block_starts))
    valid = (positions >= 0) & (positions + n_hours <= len(series))
    if not valid.any():
        log.warning(
            "%s: no generation block start falls inside the demand store; demand held at p50",
            region,
        )
        return np.repeat(p50_mw[None, :], n_scenarios, axis=0)
    if not valid.all():
        log.info(
            "%s: %d of %d blocks absent from the demand store, resampled from those present",
            region, int((~valid).sum()), len(valid),
        )
        positions = np.where(valid, positions, np.resize(positions[valid], len(positions)))

    values = series.to_numpy(dtype="float64")
    blocks = np.stack([values[p : p + n_hours] for p in positions])
    return p50_mw[None, :] + dispersion * blocks * peak_mw


def compute(
    *,
    region: str,
    generation: dict[Tech, ScenarioSet],
    demand_p50_mw: np.ndarray,
    demand_peak_mw: float,
    valid_times: pd.DatetimeIndex,
    horizons: np.ndarray,
    block_starts: np.ndarray | None = None,
    headroom_mw: float | None = None,
    demand_store: pd.DataFrame | None = None,
    calibrate: bool = True,
) -> BalanceResult:
    """Combine generation and demand ensembles into an hourly balance."""
    if not generation:
        raise ValueError("no generation scenarios supplied")

    totals = [s.regional_total() for s in generation.values()]
    n_scenarios, n_hours = totals[0].shape
    for total in totals:
        if total.shape != (n_scenarios, n_hours):
            raise ValueError("generation ensembles disagree on shape")
    renewable = np.sum(totals, axis=0)

    if block_starts is None:
        # Independent draw. Acceptable, but it severs the demand-generation coupling, so
        # the caller is told rather than left to discover the difference in the numbers.
        raise ValueError(
            "block_starts is required: without the generation ensemble's historical hours "
            "the demand draw cannot be aligned to it, and the coupling that causes "
            "shortages would be sampled away"
        )

    demand = demand_scenarios(
        region,
        demand_p50_mw,
        valid_times,
        n_scenarios=n_scenarios,
        block_starts=block_starts,
        peak_mw=demand_peak_mw,
        # Demand has no fitted dispersion of its own yet. Its residuals already carry the
        # model's real error distribution, and unlike generation there is no evidence of
        # systematic under-spread, so 1.0 is the honest default rather than a placeholder.
        dispersion=1.0,
        store=demand_store,
    )

    residual = demand - renewable
    headroom = dispatchable_headroom(region) if headroom_mw is None else headroom_mw

    is_surplus = residual < 0.0
    is_shortage = residual > headroom

    # Expected magnitudes are unconditional: averaged over ALL scenarios, counting zero
    # where the condition does not occur. That makes them directly additive into energy,
    # and stops a 5%-likely 900 MW shortage reading like a 900 MW shortage.
    surplus_mw = np.where(is_surplus, -residual, 0.0)
    shortage_mw = np.where(is_shortage, residual - headroom, 0.0)

    p_surplus = is_surplus.mean(axis=0)
    p_shortage = is_shortage.mean(axis=0)
    if calibrate:
        # Raw ensemble frequencies are sharp but not reliable; see balance/calibration.py.
        p_surplus = calibration.apply(p_surplus, calibration.load(region, "surplus"))
        p_shortage = calibration.apply(p_shortage, calibration.load(region, "shortage"))

    frame = pd.DataFrame(
        {
            "valid_time_utc": valid_times,
            "horizon_h": np.asarray(horizons, dtype="int16"),
            "region": region,
            "demand_p50_mw": np.median(demand, axis=0),
            "renewable_p10_mw": np.quantile(renewable, 0.10, axis=0),
            "renewable_p50_mw": np.quantile(renewable, 0.50, axis=0),
            "renewable_p90_mw": np.quantile(renewable, 0.90, axis=0),
            "residual_p10_mw": np.quantile(residual, 0.10, axis=0),
            "residual_p50_mw": np.quantile(residual, 0.50, axis=0),
            "residual_p90_mw": np.quantile(residual, 0.90, axis=0),
            "p_surplus": p_surplus,
            "p_shortage": p_shortage,
            "expected_surplus_mw": surplus_mw.mean(axis=0),
            "expected_shortage_mw": shortage_mw.mean(axis=0),
        }
    )
    # Hourly resolution, so MW averaged over an hour is MWh.
    frame["expected_surplus_mwh"] = frame["expected_surplus_mw"]
    frame["expected_shortage_mwh"] = frame["expected_shortage_mw"]
    frame["recommended_action"] = _actions(frame)

    log.info(
        "%s: %d h | surplus P>=50%% in %d h (%.0f MWh) | shortage P>=50%% in %d h (%.0f MWh) "
        "| headroom %.0f MW",
        region,
        n_hours,
        int((frame["p_surplus"] >= 0.5).sum()),
        frame["expected_surplus_mwh"].sum(),
        int((frame["p_shortage"] >= 0.5).sum()),
        frame["expected_shortage_mwh"].sum(),
        headroom,
    )
    return BalanceResult(
        frame=frame, region=region, n_scenarios=n_scenarios, headroom_mw=headroom
    )


def _actions(frame: pd.DataFrame) -> list[str]:
    """A recommended action per hour, from the probabilities rather than the median.

    Deliberately coarse. The optimiser in `storage/dispatch.py` decides *how much*; this
    says *what kind of hour it is*, which is what an operations view needs at a glance.
    Thresholds are the ones the API contract publishes so the dashboard's colours and this
    logic cannot drift apart.
    """
    actions = []
    for surplus, shortage in zip(frame["p_surplus"], frame["p_shortage"], strict=True):
        if shortage >= 0.5:
            actions.append("cover_shortage")
        elif shortage >= 0.2:
            actions.append("hold_reserve")
        elif surplus >= 0.5:
            actions.append("absorb_surplus")
        elif surplus >= 0.2:
            actions.append("prepare_to_absorb")
        else:
            actions.append("normal")
    return actions


def event_runs(frame: pd.DataFrame, column: str, threshold: float = 0.5) -> list[dict]:
    """Contiguous runs where a probability stays above threshold.

    Duration is what makes a balance actionable: an hour of surplus is absorbed by any
    battery, six consecutive hours is a storage sizing question.
    """
    flags = (frame[column] >= threshold).to_numpy()
    runs, start = [], None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= MIN_EVENT_HOURS:
                runs.append(_run(frame, start, i, column))
            start = None
    if start is not None and len(flags) - start >= MIN_EVENT_HOURS:
        runs.append(_run(frame, start, len(flags), column))
    return runs


def _run(frame: pd.DataFrame, start: int, end: int, column: str) -> dict:
    kind = "surplus" if "surplus" in column else "shortage"
    block = frame.iloc[start:end]
    # ISO-8601 with a Z suffix, matching every other timestamp the API emits. Consistency
    # here is not cosmetic: a consumer parsing two formats from one payload will get one of
    # them wrong eventually.
    stamps = pd.DatetimeIndex(block["valid_time_utc"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "kind": kind,
        "from_utc": stamps[0],
        "to_utc": stamps[-1],
        "hours": int(end - start),
        "peak_probability": round(float(block[column].max()), 3),
        "energy_mwh": round(float(block[f"expected_{kind}_mwh"].sum()), 1),
    }
