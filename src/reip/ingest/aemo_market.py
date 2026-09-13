"""Regional demand, price and rooftop PV from the AEMO MMSDM archive.

The forecast alone is not a decision. To say whether tomorrow's generation is *useful* the
platform needs what it is being measured against - demand - and what it is worth - price.
Both live in the same monthly MMSDM bundles as the SCADA already ingested by `aemo.py`,
cover the same 36 months, and align to the same 151 plants, so the whole balance loop runs
on measured data rather than a constructed load curve.

Three tables, and the third is the one that is easy to miss:

* `DISPATCHREGIONSUM` - regional demand, 5-minute. Also carries several fields worth more
  than the demand itself; see `REGIONSUM_FIELDS`.
* `DISPATCHPRICE` - regional spot price, 5-minute. Turns "curtail 200 MW" into a number of
  dollars, and makes negative-price hours - when exporting actively costs money - visible
  as the distinct operating state they are.
* `ROOFTOP_PV_ACTUAL` - AEMO's estimate of behind-the-meter rooftop solar, 30-minute.
  `TOTALDEMAND` is *operational* demand, already net of rooftop output, so on a mild sunny
  day it collapses at midday for reasons no calendar or temperature feature can explain.
  Without this column a demand model systematically misses the midday trough, which is
  precisely the hour the surplus logic cares about most.

**Two traps, both silent.**

Dispatch tables carry intervention runs alongside normal ones. During a market
intervention the same interval appears twice, once with `INTERVENTION=1`, and taking both
double-counts that interval and corrupts any aggregate over it. Only `INTERVENTION=0` is
kept.

`ROOFTOP_PV_ACTUAL` publishes both `MEASUREMENT` and `SATELLITE` estimates, again two rows
per interval and region. `MEASUREMENT` is the one AEMO settles on.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from reip.config import get_settings
from reip.ingest.aemo import _download_first, market_to_utc, month_range, table_urls

log = logging.getLogger(__name__)

# Fields kept from DISPATCHREGIONSUM, mapped to canonical names.
#
# TOTALDEMAND is the target. The rest are here because they replace guesses with
# measurements:
#
#   AVAILABLEGENERATION - what the region could actually have dispatched. The balance
#     module needs a dispatchable headroom figure to call a shortage, and this is the
#     measured one rather than a configured constant.
#   DEMANDFORECAST      - AEMO's own demand forecast. A free, strong baseline: beating
#     seasonal-naive is table stakes, beating the market operator is a claim.
#   SS_SOLAR_UIGF/SS_WIND_UIGF - unconstrained intermittent generation forecast, i.e. what
#     solar and wind could have produced. Against SS_*_CLEAREDMW, what they were allowed
#     to produce. The difference is *measured curtailment* - the very quantity the surplus
#     logic exists to predict, available as ground truth instead of a modelled proxy.
#   NETINTERCHANGE      - interconnector flow. A region is not an island; surplus that
#     leaves over a wire is not curtailed.
#   BDU_INITIAL_ENERGY_STORAGE - aggregate battery state of charge. No per-plant storage
#     data is public, but the regional total anchors the storage model to reality.
REGIONSUM_FIELDS: dict[str, str] = {
    "TOTALDEMAND": "demand_mw",
    "AVAILABLEGENERATION": "available_generation_mw",
    "DEMANDFORECAST": "aemo_demand_forecast_mw",
    "NETINTERCHANGE": "net_interchange_mw",
    "SS_SOLAR_UIGF": "solar_uigf_mw",
    "SS_WIND_UIGF": "wind_uigf_mw",
    "SS_SOLAR_CLEAREDMW": "solar_cleared_mw",
    "SS_WIND_CLEAREDMW": "wind_cleared_mw",
    "BDU_INITIAL_ENERGY_STORAGE": "battery_energy_mwh",
}

PRICE_FIELDS: dict[str, str] = {"RRP": "rrp_aud_mwh"}
ROOFTOP_FIELDS: dict[str, str] = {"POWER": "rooftop_pv_mw"}

NEM_REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")

# Plausibility bounds, asserted rather than assumed.
#
# The floor is negative on purpose. Operational demand is net of rooftop PV, and in South
# Australia rooftop output now exceeds total state consumption on mild sunny days when
# industrial load is low: the measured minimum over these three years is -280 MW, on
# Christmas Day 2025 at 13:30 local with 1,780 MW of rooftop PV and a spot price of
# -$251/MWh. That is not an outlier to be filtered - it is precisely the condition the
# surplus and curtailment logic exists to anticipate.
#
# -1000 MW is therefore chosen well below any observed value while still being far above
# what a mis-read column would produce.
DEMAND_BOUNDS_MW = (-1000.0, 20000.0)

# Negative demand is real but rare. A sign error or a wrong column would make it common, so
# the *rate* is the check that a flat bound cannot make.
MAX_NEGATIVE_DEMAND_SHARE = 0.01
# The market price cap and floor. RRP genuinely reaches both, so these are hard limits and
# not outlier filters.
RRP_BOUNDS = (-1000.0, 20000.0)


def _read_table(
    path: Path,
    fields: dict[str, str],
    *,
    time_column: str,
    filters: dict[str, str] | None = None,
    required: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Parse one monthly MMSDM bundle, driven by the header row rather than by position.

    MMSDM files declare their own schema: an `I` row naming every column, then `D` rows of
    data. Columns are read by name from that header because AEMO appends fields between
    releases - DISPATCHREGIONSUM has grown past 130 - so any hardcoded index is a silent
    mis-read waiting for the next schema change.

    That evolution is the reason for `required`. Columns appear over time:
    `BDU_INITIAL_ENERGY_STORAGE` arrived with bidirectional dispatch units in mid-2025 and
    simply does not exist in 2023 files. Treating every requested field as mandatory
    discards two years of demand over a storage column, so only `required` fields raise;
    the rest come back as NaN when the archive of the day did not have them yet.

    Streamed rather than loaded through `pd.read_csv`: the useful columns are a handful out
    of 130, and filtering during the scan keeps peak memory to what is actually wanted.
    """
    filters = filters or {}
    records: list[tuple] = []
    present: dict[str, str] = {}

    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as fh:
        reader = csv.reader(io.TextIOWrapper(fh, "utf-8", errors="replace"))
        index: dict[str, int] | None = None
        wanted: list[int] = []
        filter_idx: list[tuple[int, str]] = []

        for row in reader:
            if not row:
                continue

            if row[0] == "I":
                index = {name: i for i, name in enumerate(row)}
                structural = [c for c in (time_column, "REGIONID", *filters) if c not in index]
                if structural:
                    raise ValueError(f"{path.name}: header lacks {structural}")
                missing_required = [c for c in required if c not in index]
                if missing_required:
                    raise ValueError(f"{path.name}: header lacks required {missing_required}")

                present = {src: dst for src, dst in fields.items() if src in index}
                absent = sorted(set(fields) - set(present))
                if absent:
                    log.debug("%s: columns absent in this vintage: %s", path.name, absent)
                wanted = [index[time_column], index["REGIONID"], *(index[c] for c in present)]
                filter_idx = [(index[k], v) for k, v in filters.items()]
                continue

            if row[0] != "D" or index is None:
                continue
            if any(len(row) <= i or row[i] != v for i, v in filter_idx):
                continue
            if len(row) <= max(wanted):
                continue
            records.append(tuple(row[i] for i in wanted))

    if not records:
        raise ValueError(f"{path.name}: no data rows survived filtering")

    frame = pd.DataFrame(records, columns=["market_time", "region", *present.values()])
    for column in present.values():
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # Absent columns still appear, as NaN, so every month has the same shape and a later
    # concat does not produce a ragged frame.
    for column in fields.values():
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame


def _to_hourly(frame: pd.DataFrame, *, interval_minutes: int) -> pd.DataFrame:
    """Interval-ending market time to hourly UTC means, per region."""
    converted = market_to_utc(frame["market_time"], interval_minutes=interval_minutes)
    valid = converted.notna()
    if not valid.all():
        log.warning("dropping %d rows with unparseable stamps", int((~valid).sum()))

    out = frame[valid].copy()
    out["valid_time_utc"] = converted[valid]
    value_columns = [c for c in out.columns if c not in ("market_time", "region", "valid_time_utc")]
    return (
        out.set_index("valid_time_utc")
        .groupby([pd.Grouper(freq="h"), "region"])[value_columns]
        .mean()
        .reset_index()
    )


def ingest(
    years: float = 3.0,
    *,
    end: datetime | None = None,
    raw_dir: Path | None = None,
    out_path: Path | None = None,
) -> pd.DataFrame:
    """Download, parse and join the three market tables into one canonical frame."""
    settings = get_settings()
    settings.ensure_dirs()
    raw_dir = raw_dir or (settings.data_raw / "aemo_market")
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (settings.data_canonical / "aemo_market.parquet")

    months = month_range(years, end)
    log.info("market ingest: %d months, %s to %s", len(months), months[0], months[-1])

    monthly: list[pd.DataFrame] = []
    for year, month in months:
        tag = f"{year}{month:02d}"
        try:
            regionsum = _read_table(
                _download_first(
                    table_urls("DISPATCHREGIONSUM", year, month), raw_dir / f"regionsum_{tag}.zip"
                ),
                REGIONSUM_FIELDS,
                time_column="SETTLEMENTDATE",
                filters={"INTERVENTION": "0"},
                required=("TOTALDEMAND",),
            )
            price = _read_table(
                _download_first(
                    table_urls("DISPATCHPRICE", year, month), raw_dir / f"price_{tag}.zip"
                ),
                PRICE_FIELDS,
                time_column="SETTLEMENTDATE",
                filters={"INTERVENTION": "0"},
                required=("RRP",),
            )
            rooftop = _read_table(
                _download_first(
                    table_urls("ROOFTOP_PV_ACTUAL", year, month), raw_dir / f"rooftop_{tag}.zip"
                ),
                ROOFTOP_FIELDS,
                time_column="INTERVAL_DATETIME",
                filters={"TYPE": "MEASUREMENT"},
                required=("POWER",),
            )
        except Exception as exc:  # noqa: BLE001 - one bad month must not lose the run
            log.warning("%s: skipped (%s)", tag, exc)
            continue

        joined = _to_hourly(regionsum, interval_minutes=5)
        joined = joined.merge(
            _to_hourly(price, interval_minutes=5), on=["valid_time_utc", "region"], how="left"
        )
        # Rooftop is published at 30 minutes against dispatch's 5, so a month can end with
        # a half-hour that dispatch has and rooftop does not. Left join keeps the demand
        # row and leaves rooftop null rather than silently dropping the hour.
        joined = joined.merge(
            _to_hourly(rooftop, interval_minutes=30), on=["valid_time_utc", "region"], how="left"
        )
        monthly.append(joined)
        log.info("  %s: %s rows", tag, f"{len(joined):,}")

    if not monthly:
        raise RuntimeError("no market data ingested")

    market = pd.concat(monthly, ignore_index=True)
    market = market[market["region"].isin(NEM_REGIONS)]
    market = (
        market.drop_duplicates(subset=["valid_time_utc", "region"], keep="last")
        .sort_values(["region", "valid_time_utc"])
        .reset_index(drop=True)
    )

    # Curtailment, computed once here rather than by every consumer. UIGF is what the
    # intermittent fleet could have produced; cleared is what it was allowed to. Clipped at
    # zero because the two are separate AEMO estimates and can disagree by a rounding
    # margin, which would otherwise read as negative curtailment.
    for tech in ("solar", "wind"):
        market[f"{tech}_curtailed_mw"] = (
            market[f"{tech}_uigf_mw"] - market[f"{tech}_cleared_mw"]
        ).clip(lower=0.0)

    validate_market(market)
    market.to_parquet(out_path, index=False)
    log.info(
        "wrote %s rows to %s (%s to %s, %d regions)",
        f"{len(market):,}",
        out_path,
        market["valid_time_utc"].min(),
        market["valid_time_utc"].max(),
        market["region"].nunique(),
    )
    return market


def validate_market(frame: pd.DataFrame) -> pd.DataFrame:
    """Assert the invariants that would otherwise fail silently downstream."""
    duplicated = frame.duplicated(subset=["valid_time_utc", "region"]).sum()
    if duplicated:
        raise ValueError(f"{duplicated} duplicate (region, valid_time_utc) rows")

    if frame["valid_time_utc"].dt.tz is None:
        raise ValueError("valid_time_utc must be timezone-aware UTC")

    demand = frame["demand_mw"].dropna()
    lo, hi = DEMAND_BOUNDS_MW
    if not demand.between(lo, hi).all():
        raise ValueError(
            f"demand outside [{lo}, {hi}] MW: min {demand.min():.0f}, max {demand.max():.0f}"
        )

    negative_share = float((demand < 0).mean())
    if negative_share > MAX_NEGATIVE_DEMAND_SHARE:
        raise ValueError(
            f"{negative_share:.1%} of hours have negative demand, above the "
            f"{MAX_NEGATIVE_DEMAND_SHARE:.0%} ceiling - a sign error or a mis-read column, "
            "not a genuinely solar-saturated grid"
        )

    rrp = frame["rrp_aud_mwh"].dropna()
    lo, hi = RRP_BOUNDS
    if len(rrp) and not rrp.between(lo, hi).all():
        raise ValueError(f"RRP outside [{lo}, {hi}]: min {rrp.min():.0f}, max {rrp.max():.0f}")

    return frame


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ingest AEMO regional demand, price and rooftop PV")
    parser.add_argument("--years", type=float, default=3.0)
    args = parser.parse_args()

    result = ingest(args.years)
    print(result.groupby("region")["demand_mw"].describe().to_string())
