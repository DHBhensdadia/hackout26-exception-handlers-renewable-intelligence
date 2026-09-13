"""Recurring seasonal patterns, mined from three years of measured history.

Spec module 3, and the bridge the spec calls its own USP (section 18): a platform that only
flags tomorrow's surplus tells an operator something they will learn anyway in a day. One
that recognises the surplus as the same surplus that happens every summer, and sizes the
asset that would absorb it, has said something about next year.

Everything here is measured, not forecast. The inputs are what actually happened - metered
regional demand, the intermittent fleet's available output, the spot price and what was
actually curtailed - over 2023-09 to 2026-08. No model runs in this module at all, which is
deliberate: a recurring pattern is a property of the record, and putting a forecast in front
of it would only add error to something already known.

Three questions, in the order a planner asks them:

1. **When does it recur?** Surplus and shortage by month and hour of day, which is the grid
   on which a duck curve is actually visible.
2. **How long does it last?** A renewable drought of two hours is absorbed by any battery; a
   drought of forty is a different kind of problem, and the distinction is duration rather
   than depth.
3. **What would fix it?** The storage energy that would have absorbed the recurring surplus,
   computed by simulating a battery against the real series rather than by dividing an
   average.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings

log = logging.getLogger(__name__)

# Local clock per region. Seasonal patterns are a human and solar phenomenon - the evening
# peak is at dinner time and the solar trough is at local noon - so binning by UTC would
# smear both across neighbouring hours and, in the eastern states, across two dates.
REGION_TZ: dict[str, str] = {
    "NSW1": "Australia/Sydney",
    "QLD1": "Australia/Brisbane",
    "SA1": "Australia/Adelaide",
    "TAS1": "Australia/Hobart",
    "VIC1": "Australia/Melbourne",
}

# A renewable drought is a run of DAYS where the intermittent fleet supplies less than this
# share of demand. Not zero output: what matters is whether the conventional fleet and
# storage have to carry the region, and 20% is where that becomes the case.
DROUGHT_THRESHOLD: float = 0.20

# Measured on whole days, which is the correction that makes this mean anything.
#
# Scored hour by hour, a solar-dominated region is "in drought" every single night by
# definition - QLD1 came out at 335 events a year, which is the diurnal cycle wearing a
# planning label. A drought is a sustained lull that storage cannot ride through, and that is
# a property of days, not hours. Daily aggregation also matches how the phenomenon is
# discussed: a Dunkelflaute is counted in days.
MIN_DROUGHT_DAYS: int = 2

# Round-trip efficiency assumed when sizing storage against the historical surplus. Matches
# `storage/asset.py` so the two modules cannot disagree about what a battery is.
STORAGE_EFFICIENCY: float = 0.88

# Share of recurring surplus energy the sizing question targets. Absorbing the last few
# percent needs a battery several times larger, because the extreme hours are rare and deep
# - so the honest answer is a curve, not a single number, and this is where it is read off.
CAPTURE_TARGETS: tuple[float, ...] = (0.50, 0.80, 0.95)


def _load(region: str, market: pd.DataFrame | None = None) -> pd.DataFrame:
    """Regional history on the local clock, with the derived balance columns."""
    if market is None:
        market = pd.read_parquet(get_settings().data_canonical / "aemo_market.parquet")

    block = market[market["region"] == region].drop_duplicates("valid_time_utc").copy()
    if block.empty:
        raise ValueError(f"no market history for {region}")

    tz = REGION_TZ.get(region, "UTC")
    local = pd.DatetimeIndex(block["valid_time_utc"]).tz_convert(tz)
    block["local_hour"] = local.hour
    block["month"] = local.month
    block["date"] = local.date

    # Available renewable output, not what was cleared. The difference is curtailment, and
    # counting cleared output would hide exactly the surplus this module is looking for -
    # the hours the fleet could have produced more and was not allowed to.
    block["renewable_mw"] = block["solar_uigf_mw"].fillna(0.0) + block["wind_uigf_mw"].fillna(0.0)
    block["residual_mw"] = block["demand_mw"] - block["renewable_mw"]
    block["surplus_mw"] = (-block["residual_mw"]).clip(lower=0.0)
    # Deliberately NOT stored as an hourly ratio. SA1's operational demand goes negative -
    # rooftop PV exceeding all consumption - so a per-hour renewable/demand ratio divides by
    # something near zero and averaging those ratios gave a "mean renewable share" of 1590%.
    # Share is an energy question and is computed as summed renewable over summed demand
    # wherever it is reported; see `_energy_share`.
    block["curtailed_mw"] = block["solar_curtailed_mw"].fillna(0.0) + block[
        "wind_curtailed_mw"
    ].fillna(0.0)
    return block.sort_values("valid_time_utc")


def _energy_share(renewable: pd.Series, demand: pd.Series) -> float:
    """Renewable energy as a share of demand energy over a period.

    A ratio of sums, never a mean of ratios. The two agree when demand is comfortably
    positive and diverge wildly when it is not, and in the region this platform cares about
    most it is not: SA1 spends 257 hours a year below zero.
    """
    total_demand = float(demand.sum())
    if total_demand <= 0:
        return float("nan")
    return float(renewable.sum()) / total_demand


def surplus_share_grid(block: pd.DataFrame) -> list[list[float]]:
    """Month x hour fraction of hours that were in surplus, 0 to 1.

    Distinct from the mean surplus MW in the same cell: an hour that is hugely in surplus
    one year in three reads as a large mean and a small frequency, and a planner wants to
    know which of those it is looking at.
    """
    grouped = (
        block.assign(is_surplus=(block["surplus_mw"] > 0).astype("float64"))
        .groupby(["month", "local_hour"])["is_surplus"]
        .mean()
        .unstack("local_hour")
        .reindex(index=range(1, 13), columns=range(24))
        .astype("float64")
    )
    return [[None if pd.isna(v) else round(float(v), 4) for v in row] for row in grouped.to_numpy()]


def share_grid(block: pd.DataFrame) -> list[list[float]]:
    """Month x hour renewable share, as an energy ratio per cell."""
    grouped = block.groupby(["month", "local_hour"]).agg(
        renewable=("renewable_mw", "sum"), demand=("demand_mw", "sum")
    )
    grouped["share"] = grouped["renewable"] / grouped["demand"].where(grouped["demand"] > 0)
    pivot = (
        grouped["share"]
        .unstack("local_hour")
        .reindex(index=range(1, 13), columns=range(24))
        .astype("float64")
    )
    return [[None if pd.isna(v) else round(float(v), 4) for v in row] for row in pivot.to_numpy()]


def month_hour_grid(block: pd.DataFrame, column: str, how: str = "mean") -> list[list[float]]:
    """A 12x24 grid, months down and local hours across.

    The natural shape for a recurring pattern: a duck curve is a horizontal band, a seasonal
    swing is a vertical one, and both are visible at once without reading a single number.
    """
    pivot = (
        block.pivot_table(index="month", columns="local_hour", values=column, aggfunc=how)
        .reindex(index=range(1, 13), columns=range(24))
        .astype("float64")
    )
    return [[None if pd.isna(v) else round(float(v), 2) for v in row] for row in pivot.to_numpy()]


def droughts(block: pd.DataFrame) -> dict:
    """Runs of days where renewables cover less than `DROUGHT_THRESHOLD` of demand.

    Duration is the planning variable. Two days is a battery question; six is a firm-capacity
    question, and no amount of storage sized for the first solves the second. The
    distribution is reported rather than an average, because the mean of a long-tailed
    duration is not a period that ever actually occurs.
    """
    # Daily totals, not hourly means: a day's renewable share is its energy over its demand,
    # which is what a planner is actually asking about.
    daily = block.groupby("date").agg(
        renewable_mwh=("renewable_mw", "sum"),
        demand_mwh=("demand_mw", "sum"),
        residual_mwh=("residual_mw", "sum"),
        month=("month", "first"),
    )
    # Energy ratio again, and guarded: a day whose total demand is not positive cannot have
    # a meaningful share and is not a drought candidate.
    daily["share"] = daily["renewable_mwh"] / daily["demand_mwh"].where(daily["demand_mwh"] > 0)
    daily["share"] = daily["share"].fillna(1.0)
    below = (daily["share"] < DROUGHT_THRESHOLD).to_numpy()
    dates = list(daily.index)

    runs: list[dict] = []
    start: int | None = None
    for i, flag in enumerate(below):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= MIN_DROUGHT_DAYS:
                runs.append(_run(daily, dates, start, i))
            start = None
    if start is not None and len(below) - start >= MIN_DROUGHT_DAYS:
        runs.append(_run(daily, dates, start, len(below)))

    years = (pd.DatetimeIndex(block["valid_time_utc"]).max()
             - pd.DatetimeIndex(block["valid_time_utc"]).min()).days / 365.25

    if not runs:
        return {
            "count": 0,
            "per_year": 0.0,
            "days_per_year": 0.0,
            "longest": None,
            "duration_quantiles": {},
            "threshold_share": DROUGHT_THRESHOLD,
            "note": f"no run of {MIN_DROUGHT_DAYS}+ days below {DROUGHT_THRESHOLD:.0%} in the record",
        }

    lengths = np.array([r["days"] for r in runs], dtype="float64")
    return {
        "count": len(runs),
        "per_year": round(len(runs) / years, 1),
        "days_per_year": round(float(lengths.sum()) / years, 1),
        "threshold_share": DROUGHT_THRESHOLD,
        "duration_quantiles": {
            "p50": round(float(np.quantile(lengths, 0.50)), 1),
            "p90": round(float(np.quantile(lengths, 0.90)), 1),
            "max": int(lengths.max()),
        },
        "longest": max(runs, key=lambda r: r["days"]),
        "by_month": _count_by_month(runs),
        "worst": sorted(runs, key=lambda r: -r["days"])[:5],
    }


def _run(daily: pd.DataFrame, dates: list, start: int, end: int) -> dict:
    window = daily.iloc[start:end]
    return {
        "from_date": str(dates[start]),
        "to_date": str(dates[end - 1]),
        "days": int(end - start),
        "month": int(window["month"].iloc[0]),
        "mean_renewable_share": round(
            float(window["renewable_mwh"].sum() / max(window["demand_mwh"].sum(), 1e-9)), 4
        ),
        "total_residual_mwh": round(float(window["residual_mwh"].sum()), 1),
    }


def _count_by_month(runs: list[dict]) -> dict[int, int]:
    counts = dict.fromkeys(range(1, 13), 0)
    for r in runs:
        counts[r["month"]] += 1
    return counts


def storage_adequacy(block: pd.DataFrame, power_mw: float | None = None) -> dict:
    """How much storage energy would have absorbed the recurring surplus.

    Simulated against the real hourly series rather than divided out of an annual total. The
    difference matters: surplus arrives in bursts of a few hours, so a battery sized on
    average energy is far too small, and one sized on the single worst burst is far too
    large. Running a state of charge through three years of actual data answers the question
    the average cannot.

    The answer is a curve. Absorbing half the surplus is cheap; the last few percent costs
    several times more, because those hours are rare and deep. `CAPTURE_TARGETS` is where a
    planner reads off the knee.
    """
    surplus = block["surplus_mw"].to_numpy(dtype="float64")
    total_surplus = float(surplus.sum())
    if total_surplus <= 0:
        return {"total_surplus_mwh_per_year": 0.0, "targets": {}, "note": "no surplus in the record"}

    years = max((pd.DatetimeIndex(block["valid_time_utc"]).max()
                 - pd.DatetimeIndex(block["valid_time_utc"]).min()).days / 365.25, 1e-9)

    # Charge power defaults to the 99th percentile of surplus: sizing to the maximum would
    # be set by a single hour in three years.
    power = power_mw if power_mw is not None else float(np.quantile(surplus[surplus > 0], 0.99))

    # Discharge whenever there is a deficit, which is what makes this a storage question and
    # not a curtailment-avoidance one - the energy has to leave the battery again.
    deficit = block["residual_mw"].clip(lower=0.0).to_numpy(dtype="float64")

    curve = []
    for energy_mwh in _candidate_sizes(total_surplus / years):
        captured = _simulate(surplus, deficit, energy_mwh, power)
        curve.append(
            {
                "energy_mwh": round(energy_mwh, 1),
                "duration_h": round(energy_mwh / power, 2) if power > 0 else None,
                "captured_share": round(captured / total_surplus, 4),
                "captured_mwh_per_year": round(captured / years, 1),
            }
        )

    targets = {}
    for target in CAPTURE_TARGETS:
        hit = next((c for c in curve if c["captured_share"] >= target), None)
        targets[f"{int(target * 100)}pct"] = hit

    return {
        "total_surplus_mwh_per_year": round(total_surplus / years, 1),
        "assumed_power_mw": round(power, 1),
        "round_trip_efficiency": STORAGE_EFFICIENCY,
        "curve": curve,
        "targets": targets,
    }


def _candidate_sizes(annual_surplus_mwh: float) -> list[float]:
    """Battery sizes to test, spanning well under and well over a day of surplus."""
    daily = max(annual_surplus_mwh / 365.25, 1.0)
    return [round(daily * f, 1) for f in (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0)]


def _simulate(surplus: np.ndarray, deficit: np.ndarray, energy_mwh: float, power_mw: float) -> float:
    """Run a battery through the series and return the surplus energy it absorbed."""
    eta = STORAGE_EFFICIENCY**0.5
    soc = 0.0
    captured = 0.0
    for s, d in zip(surplus, deficit, strict=True):
        if s > 0:
            room = (energy_mwh - soc) / eta
            charge = min(s, power_mw, max(room, 0.0))
            soc += charge * eta
            captured += charge
        elif d > 0 and soc > 0:
            discharge = min(d, power_mw, soc * eta)
            soc -= discharge / eta
    return captured


def analyse(region: str, market: pd.DataFrame | None = None) -> dict:
    """Every seasonal pattern for one region."""
    block = _load(region, market)
    times = pd.DatetimeIndex(block["valid_time_utc"])
    years = (times.max() - times.min()).days / 365.25

    surplus_hours = block["surplus_mw"] > 0
    by_month = (
        block.assign(is_surplus=surplus_hours)
        .groupby("month")
        .agg(
            surplus_hours=("is_surplus", "sum"),
            surplus_mwh=("surplus_mw", "sum"),
            curtailed_mwh=("curtailed_mw", "sum"),
            mean_demand_mw=("demand_mw", "mean"),
            renewable_mwh=("renewable_mw", "sum"),
            demand_mwh=("demand_mw", "sum"),
            mean_price=("rrp_aud_mwh", "mean"),
            negative_price_hours=("rrp_aud_mwh", lambda s: int((s < 0).sum())),
        )
        .reindex(range(1, 13))
    )

    monthly = [
        {
            "month": int(m),
            "surplus_hours_per_year": round(float(r.surplus_hours) / years, 1),
            "surplus_mwh_per_year": round(float(r.surplus_mwh) / years, 1),
            "curtailed_mwh_per_year": round(float(r.curtailed_mwh) / years, 1),
            "mean_demand_mw": round(float(r.mean_demand_mw), 1),
            "renewable_share": (
                None if r.demand_mwh <= 0 else round(float(r.renewable_mwh / r.demand_mwh), 4)
            ),
            "mean_price_aud_mwh": round(float(r.mean_price), 2),
            "negative_price_hours_per_year": round(float(r.negative_price_hours) / years, 1),
        }
        for m, r in by_month.iterrows()
        if pd.notna(r.surplus_hours)
    ]

    peak = max(monthly, key=lambda m: m["surplus_mwh_per_year"]) if monthly else None
    result = {
        "region": region,
        "timezone": REGION_TZ.get(region, "UTC"),
        "from_utc": times.min().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to_utc": times.max().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "years_of_history": round(years, 2),
        "data_mode": "measured",
        "data_note": (
            "Mined from measured history - metered demand, the intermittent fleet's available "
            "output, spot price and actual curtailment. No model output is involved."
        ),
        "grids": {
            "surplus_mw": month_hour_grid(block, "surplus_mw"),
            "residual_mw": month_hour_grid(block, "residual_mw"),
            "renewable_share": share_grid(block),
            "surplus_share": surplus_share_grid(block),
            "price_aud_mwh": month_hour_grid(block, "rrp_aud_mwh", "median"),
        },
        "by_month": monthly,
        "peak_surplus_month": peak["month"] if peak else None,
        "droughts": droughts(block),
        "storage": storage_adequacy(block),
    }

    log.info(
        "%s: %.1f yr | surplus %s MWh/yr | %s droughts/yr | peak month %s",
        region,
        years,
        f"{sum(m['surplus_mwh_per_year'] for m in monthly):,.0f}",
        result["droughts"].get("per_year", 0),
        result["peak_surplus_month"],
    )
    return result


def artifact_path(region: str, directory: Path | None = None) -> Path:
    return (directory or get_settings().data_canonical) / f"seasonal_{region}.json"


def main(regions: list[str] | None = None) -> dict[str, Path]:
    market = pd.read_parquet(get_settings().data_canonical / "aemo_market.parquet")
    written: dict[str, Path] = {}
    for region in regions or sorted(REGION_TZ):
        try:
            payload = analyse(region, market)
        except ValueError as exc:
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
    parser = argparse.ArgumentParser(description="Mine recurring seasonal patterns")
    parser.add_argument("--region", action="append")
    args = parser.parse_args()

    for region, path in main(args.region).items():
        print(f"{region}: {path}")
