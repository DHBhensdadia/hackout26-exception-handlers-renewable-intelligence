"""The residual store: historical forecast-error fields, resampled to build scenarios.

Phase 2 needs to know how forecast errors at different plants and different hours move
*together*. The models cannot say: each was fitted per site and emits a marginal
distribution for one hour in isolation. That answers "how much will this plant produce?"
and not "how much will this region produce?", because the second depends entirely on
whether the errors cancel or compound.

This records what they actually did - `(actual - p50) / capacity` for every site and hour
of the holdout. Dimensionless, so a 730 MW farm and a 15 MW one are on the same scale.

**Magnitudes as well as dependence.** An earlier design used only the *ranks* of this field
and took magnitudes from the models' own quantiles. That failed verification: three
quantiles cannot describe a tail, and solar's is heavy enough that the reconstruction
understated regional spread threefold. The field is now used directly, which carries shape,
variance and dependence together because all three are properties of the same historical
observation. See `portfolio/aggregate.py`.

**Residuals, not observations.** The classical Schaake shuffle draws its template from
historical *observations*. That would be wrong here: every solar plant in a region peaks at
local noon, so observed output is almost perfectly rank-correlated by the sun alone, and a
template built from it would imply forecast errors moving in lockstep - overstating
regional risk badly. Residuals strip out the deterministic diurnal component and leave the
thing being propagated: how wrong the forecast was, and whether it was wrong in the same
direction everywhere at once.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.schemas import Tech

log = logging.getLogger(__name__)

# The lead whose residual field supplies the template.
#
# One lead rather than a per-horizon mixture. Splicing sources at the 24 h and 48 h
# boundaries would inject a discontinuity into the error field at exactly those hours - an
# artefact of the corpus layout, not anything the atmosphere does.
#
# The cost is that a 72 h scenario carries 24 h-lead error magnitudes throughout, which
# understates the far end of the horizon. That is a known limitation, and part of what the
# fitted `dispersion` factor absorbs.
TEMPLATE_HORIZON_H: int = 24

# Minimum sites a template block must cover to be usable. A block with most sites missing
# would contribute a rank pattern dominated by whatever handful happened to report.
MIN_SITE_COVERAGE = 0.80


def store_path(tech: Tech, directory: Path | None = None) -> Path:
    directory = directory or get_settings().data_canonical
    return directory / f"residuals_{tech.value}.parquet"


def build(tech: Tech, *, out_path: Path | None = None) -> pd.DataFrame:
    """Compute the historical residual field and persist it.

    Returns a wide frame: rows are hours, columns are sites, values are
    `(actual - p50) / capacity` - dimensionless, so a 730 MW farm and a 15 MW one contribute
    on the same scale and neither dominates the ordering.
    """
    from reip.eval.report import build_holdout_frame

    _, holdout = build_holdout_frame(tech)
    block = holdout[holdout["horizon_h"] == TEMPLATE_HORIZON_H]
    if block.empty:
        # A single-lead corpus may carry a different nominal horizon; fall back to whichever
        # lead is most populated rather than returning nothing.
        fallback = int(holdout["horizon_h"].value_counts().idxmax())
        log.warning(
            "no rows at the %dh template horizon; falling back to %dh",
            TEMPLATE_HORIZON_H,
            fallback,
        )
        block = holdout[holdout["horizon_h"] == fallback]

    block = block.assign(
        residual=(block["actual_mw"] - block["p50_mw"]) / block["capacity_mw"].clip(lower=1e-6)
    )
    wide = block.pivot_table(
        index="valid_time_utc", columns="site_id", values="residual", aggfunc="mean"
    ).sort_index()

    out_path = out_path or store_path(tech)
    wide.to_parquet(out_path)
    log.info(
        "%s residual store: %s hours x %d sites, %s to %s (mean |r| %.4f)",
        tech.value,
        f"{len(wide):,}",
        wide.shape[1],
        wide.index.min(),
        wide.index.max(),
        float(np.nanmean(np.abs(wide.to_numpy()))),
    )
    return wide


def load(tech: Tech, path: Path | None = None) -> pd.DataFrame:
    path = path or store_path(tech)
    if not path.exists():
        raise FileNotFoundError(
            f"no residual store at {path}; run `python -m reip.portfolio.residuals`"
        )
    return pd.read_parquet(path)


def template_blocks(
    store: pd.DataFrame,
    sites: list[str],
    hours: int,
    *,
    min_coverage: float = MIN_SITE_COVERAGE,
    start_hour: int | None = None,
) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """Usable contiguous windows of the residual field, plus the hour each one starts at.

    Returns `(blocks, starts)` where blocks is `(block, hour, site)`. The start timestamps
    matter as much as the values: another ensemble drawn from a *different* store - demand,
    which covers a longer period - can only be aligned to the same historical hours by
    timestamp. Sharing integer indices across two differently-indexed stores would silently
    pair unrelated hours.

    Contiguity is checked against the clock rather than assumed from row order: the holdout
    has gaps where a plant was offline or an archive month was short, and splicing across
    one would fabricate a jump in the dependence structure.

    `start_hour` aligns each block to the same hour of day as the window it will be applied
    to, and for solar it is not optional. A residual field is strongly diurnal - identically
    zero at night, largest around noon - so a block beginning at 03:00 laid over a window
    beginning at 12:00 puts night-time zeros on the midday hours and midday errors on the
    night. The result is a daytime spread far narrower than reality, which is exactly the
    shape of failure that is hardest to notice: every scenario still looks like a plausible
    day.
    """
    available = [s for s in sites if s in store.columns]
    if not available:
        raise ValueError("none of the requested sites appear in the residual store")
    if len(available) < len(sites):
        log.info(
            "%d of %d sites absent from the residual store; template built from the rest",
            len(sites) - len(available),
            len(sites),
        )

    frame = store[available]
    values = frame.to_numpy(dtype="float64")
    times = pd.DatetimeIndex(frame.index)

    # A window is usable only if its hours are consecutive.
    #
    # Compared as timedeltas rather than as raw int64. A DatetimeIndex reports int64 in
    # whatever resolution it happens to carry - nanoseconds when read back from parquet,
    # microseconds when built by `date_range` - so a hardcoded nanosecond constant silently
    # matches nothing on the other unit, and every window looks discontiguous.
    step_ok = np.diff(times.to_numpy()) == np.timedelta64(1, "h")
    hour_of_day = times.hour.to_numpy()
    blocks: list[np.ndarray] = []
    starts: list[pd.Timestamp] = []
    start = 0
    while start + hours <= len(times):
        if not step_ok[start : start + hours - 1].all():
            # Jump past the break rather than sliding one hour at a time through it.
            gap = int(np.argmin(step_ok[start : start + hours - 1]))
            start += gap + 1
            continue
        if start_hour is not None and hour_of_day[start] != start_hour:
            start += 1
            continue
        window = values[start : start + hours]
        coverage = float(np.isfinite(window).all(axis=0).mean())
        if coverage >= min_coverage:
            blocks.append(np.nan_to_num(window, nan=0.0))
            starts.append(times[start])
        start += 1

    if not blocks:
        raise ValueError(
            f"no contiguous {hours}-hour window"
            + (f" starting at {start_hour:02d}:00 UTC" if start_hour is not None else "")
            + f" covers at least {min_coverage:.0%} of sites"
        )
    log.debug(
        "%d usable template blocks of %d hours x %d sites%s",
        len(blocks), hours, len(available),
        f", aligned to {start_hour:02d}:00 UTC" if start_hour is not None else "",
    )
    return np.stack(blocks), pd.DatetimeIndex(starts)


def main(techs: list[Tech] | None = None) -> dict[str, tuple[int, int]]:
    shapes = {}
    for tech in techs or list(Tech):
        wide = build(tech)
        shapes[tech.value] = wide.shape
    return shapes


DEMAND_STORE = "residuals_demand.parquet"


def demand_store_path(directory: Path | None = None) -> Path:
    return (directory or get_settings().data_canonical) / DEMAND_STORE


def build_demand(*, out_path: Path | None = None) -> pd.DataFrame:
    """Demand forecast errors, normalised by regional peak, one column per region.

    Kept on the same hourly index as the generation stores on purpose. Drawing a demand
    block and a generation block from the *same* historical hours reproduces whatever
    relationship the two errors really have - a hot still afternoon that pushes demand up
    and wind down is one event, and sampling them independently would break it apart.
    Nothing needs to be assumed about the coupling because nothing is modelling it.
    """
    from reip.models.demand.features import LOAD_CENTRES
    from reip.models.demand.predict import holdout_predictions, load_demand_model

    model = load_demand_model()
    columns = {}
    for region in sorted(LOAD_CENTRES):
        if region not in model.metadata["regions"]:
            continue
        frame = holdout_predictions(region)
        peak = model.peak_mw(region)
        series = pd.Series(
            (frame["actual_mw"] - frame["p50_mw"]).to_numpy() / peak,
            index=pd.DatetimeIndex(frame["valid_time_utc"]),
        )
        columns[region] = series[~series.index.duplicated()].sort_index()

    if not columns:
        raise RuntimeError("no demand regions available to build a residual store")

    wide = pd.DataFrame(columns).sort_index()
    out_path = out_path or demand_store_path()
    wide.to_parquet(out_path)
    log.info(
        "demand residual store: %s hours x %d regions, %s to %s",
        f"{len(wide):,}", wide.shape[1], wide.index.min(), wide.index.max(),
    )
    return wide


def load_demand(path: Path | None = None) -> pd.DataFrame:
    path = path or demand_store_path()
    if not path.exists():
        raise FileNotFoundError(
            f"no demand residual store at {path}; run `python -m reip.portfolio.residuals --demand`"
        )
    return pd.read_parquet(path)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Build the historical residual store")
    parser.add_argument("--tech", action="append", choices=[t.value for t in Tech])
    parser.add_argument("--demand", action="store_true", help="also build the demand store")
    args = parser.parse_args()

    for name, shape in main([Tech(t) for t in args.tech] if args.tech else None).items():
        print(f"{name}: {shape[0]:,} hours x {shape[1]} sites")
    if args.demand:
        wide = build_demand()
        print(f"demand: {len(wide):,} hours x {wide.shape[1]} regions")
