"""AEMO NEMWEB ingest: plant-level generation for the Australian National Electricity Market.

This is the training corpus that replaces GEFCom2014. AEMO publishes the actual metered
output of every registered generator every five minutes, free and without registration,
back to 2009. Filtered to utility solar and wind with known coordinates that is
**177 plants (98 solar, 79 wind)** against GEFCom's 13 - and unlike GEFCom the sites are
not anonymised, so weather can be joined at the true latitude and longitude instead of one
recovered by fitting.

Why site count matters more than row count: a model that overfits does so by memorising the
plants it trained on. Adding more hours from the same three plants teaches it those plants
in finer detail; adding a hundred more plants across seven climate zones is what forces it
to learn the underlying weather-to-power relationship. That is the change this module
exists to make.

Three source-specific traps are handled, each of which silently corrupts the data rather
than raising:

1. **Market time is not UTC.** AEMO timestamps everything in Australian Eastern Standard
   Time, UTC+10, and never applies daylight saving - even for South Australian and Western
   Australian plants. Read as UTC, every site's solar noon lands ten hours out and the
   entire diurnal cycle inverts.

2. **Settlement timestamps are interval-ending.** `00:05:00` labels the interval covering
   00:00 to 00:05. Aggregating without accounting for that shifts every hour by one slot.

3. **Negative SCADA values are real.** A solar farm at night draws auxiliary load and
   reports a small negative. That is genuine, not an error, but as a generation target it
   is meaningless and is floored at zero.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.schemas import SiteMeta, Tech, validate_power

log = logging.getLogger(__name__)

NEMWEB_MMSDM = "https://nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM"
OPENNEM_FACILITIES = "https://data.opennem.org.au/v3/geo/au_facilities.json"

# AEMO market time: UTC+10, fixed, no daylight saving anywhere in the NEM.
MARKET_TZ_OFFSET_H = 10

# OpenNEM fuel_tech values we want.
SOLAR_TECHS = frozenset({"solar_utility"})
WIND_TECHS = frozenset({"wind"})

# A site needs enough history for the model to see a full seasonal cycle. Below this it
# contributes noise and an unreliable capacity estimate.
MIN_HOURS_PER_SITE = 24 * 180

# Behavioural sanity bounds, applied per unit after aggregation. These reject machines the
# station registry mislabels - most often a grid battery sharing a solar farm's connection
# point, whose DUID inherits the station's `solar_utility` tag.
MIN_MEAN_CF = 0.03
MAX_MEAN_CF = {Tech.SOLAR: 0.45, Tech.WIND: 0.65}
# A real PV plant generates essentially all its energy while the sun is above the horizon.
MIN_DAYLIGHT_SHARE = 0.95

# How far the observed peak may sit from the registered nameplate before the observed
# value is preferred. Wide, because a plant legitimately never reaching nameplate in three
# years is normal; only a gross mismatch signals the registry figure is the wrong quantity.
CAPACITY_AGREEMENT_RANGE = (0.80, 1.10)

# Fraction of registered capacity below which an hour is treated as offline rather than
# as a genuine near-zero generation reading.
CURTAILMENT_NOTE = """\
AEMO SCADA reports metered output, which includes economic curtailment: a solar farm told
by the market to back off reads low even under clear skies. That is indistinguishable from
cloud in this data without the dispatch-target tables, so some 'forecast error' at the top
of the range is really curtailment the weather could never have predicted. It sets a floor
on achievable accuracy and is noted in the benchmark rather than hidden.
"""


@dataclass(frozen=True)
class ResolvedUnit:
    """A dispatchable unit matched to a physical location."""

    duid: str
    station_code: str
    name: str
    tech: Tech
    capacity_mw: float
    latitude: float
    longitude: float
    state: str

    def to_site(self) -> SiteMeta:
        return SiteMeta(
            site_id=f"AEMO-{self.duid}",
            name=f"{self.name} ({self.state})",
            tech=self.tech,
            capacity_mw=self.capacity_mw,
            latitude=self.latitude,
            longitude=self.longitude,
            timezone="Australia/Brisbane",
            market_region=STATE_TO_REGION.get(self.state.upper()),
            hub_height_m=None,
            rotor_diameter_m=None,
        ).defaulted


# NEM pricing regions, which are not quite states: the ACT sits inside NSW1 and has no
# region of its own. Everything downstream nets generation against demand within a region,
# so a plant filed under the wrong one would be balanced against load it cannot reach.
STATE_TO_REGION: dict[str, str] = {
    "NSW": "NSW1",
    "ACT": "NSW1",
    "QLD": "QLD1",
    "SA": "SA1",
    "TAS": "TAS1",
    "VIC": "VIC1",
}


# --------------------------------------------------------------------------------------
# Download helpers
# --------------------------------------------------------------------------------------


def _cached_download(url: str, dest: Path, *, min_bytes: int = 1000) -> Path:
    """Download once, reuse thereafter. Ingest is re-run often; the network is the slow part."""
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
        tmp.replace(dest)
    return dest


def _data_dir(year: int, month: int) -> str:
    return (
        f"{NEMWEB_MMSDM}/{year}/MMSDM_{year}_{month:02d}/MMSDM_Historical_Data_SQLLoader/DATA"
    )


def table_urls(table: str, year: int, month: int) -> list[str]:
    """Candidate URLs for one monthly table.

    AEMO changed convention partway through the archive: older months are
    `PUBLIC_DVD_<TABLE>_<YYYYMM>010000.zip`, newer ones are
    `PUBLIC_ARCHIVE#<TABLE>#FILE01#<YYYYMM>010000.zip` with the hashes percent-encoded.
    Neither is documented as superseding the other and both appear live, so both are tried
    rather than switching on a date that could move.
    """
    stamp = f"{year}{month:02d}010000"
    base = _data_dir(year, month)
    return [
        f"{base}/PUBLIC_DVD_{table}_{stamp}.zip",
        f"{base}/PUBLIC_ARCHIVE%23{table}%23FILE01%23{stamp}.zip",
    ]


def _download_first(urls: list[str], dest: Path, *, min_bytes: int = 1000) -> Path:
    """Try each candidate URL until one yields a file."""
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return dest
    errors = []
    for url in urls:
        try:
            return _cached_download(url, dest, min_bytes=min_bytes)
        except Exception as exc:  # noqa: BLE001 - fall through to the next naming scheme
            errors.append(f"{url.rsplit('/', 1)[-1]}: {type(exc).__name__}")
    raise FileNotFoundError("; ".join(errors))


# --------------------------------------------------------------------------------------
# Site resolution: DUID -> physical location
# --------------------------------------------------------------------------------------


def _load_facilities(raw_dir: Path) -> dict[str, dict]:
    """OpenNEM station registry: station_code -> coordinates, technologies, capacity."""
    path = _cached_download(OPENNEM_FACILITIES, raw_dir / "facilities.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    stations: dict[str, dict] = {}
    for feature in payload["features"]:
        props = feature["properties"]
        code = props.get("station_code")
        coords = (feature.get("geometry") or {}).get("coordinates")
        if coords and isinstance(coords[0], list):  # MultiPoint - take the first vertex
            coords = coords[0]
        if not code or not coords:
            continue

        units = props.get("duid_data") or []
        stations[code] = {
            "longitude": float(coords[0]),
            "latitude": float(coords[1]),
            "name": props.get("name") or code,
            "state": props.get("state") or "",
            "techs": {u.get("fuel_tech") for u in units},
            "capacity_mw": sum(u.get("capacity_registered") or 0.0 for u in units),
            "operating": any(u.get("status") == "operating" for u in units),
        }
    return stations


def _load_duid_station_map(raw_dir: Path, year: int, month: int) -> dict[str, str]:
    """AEMO's authoritative DUID -> STATIONID allocation."""
    path = _download_first(
        table_urls("STADUALLOC", year, month), raw_dir / f"stadualloc_{year}{month:02d}.zip"
    )
    mapping: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as fh:
        for row in csv.reader(io.TextIOWrapper(fh, "utf-8", errors="replace")):
            if row and row[0] == "D" and len(row) > 6:
                mapping[row[4]] = row[6]
    return mapping


def resolve_units(duids: set[str], raw_dir: Path, ref: tuple[int, int]) -> dict[str, ResolvedUnit]:
    """Match observed DUIDs to physical sites, solar and wind only.

    Two matching strategies, in order of trust. AEMO's own STATIONID allocation is
    authoritative but uses a different code vocabulary from OpenNEM's, so it resolves only
    part of the set; DUID-prefix matching against the station code covers most of the rest
    (`AVLSF1` belongs to station `AVLSF`). Longest codes are tried first so `ARWF1` cannot
    be mis-attributed to a shorter code that happens to be a prefix.
    """
    stations = _load_facilities(raw_dir)
    duid_to_station = _load_duid_station_map(raw_dir, *ref)
    by_length = sorted(stations, key=len, reverse=True)

    resolved: dict[str, ResolvedUnit] = {}
    for duid in sorted(duids):
        code = duid_to_station.get(duid)
        if code not in stations:
            code = next((c for c in by_length if duid.startswith(c)), None)
        if code is None:
            continue

        station = stations[code]
        techs = station["techs"]
        if techs & SOLAR_TECHS:
            tech = Tech.SOLAR
        elif techs & WIND_TECHS:
            tech = Tech.WIND
        else:
            continue
        if not station["operating"] or station["capacity_mw"] <= 0:
            continue

        resolved[duid] = ResolvedUnit(
            duid=duid,
            station_code=code,
            name=station["name"],
            tech=tech,
            capacity_mw=float(station["capacity_mw"]),
            latitude=station["latitude"],
            longitude=station["longitude"],
            state=station["state"],
        )
    return resolved


# --------------------------------------------------------------------------------------
# SCADA parsing
# --------------------------------------------------------------------------------------


def _read_month(path: Path, keep: set[str] | None) -> pd.DataFrame:
    """Parse one monthly SCADA bundle into (duid, market_time, mw).

    Streamed line by line rather than through `pd.read_csv`: the file is ~245 MB
    uncompressed and mostly units we discard, so filtering during the scan keeps peak
    memory to the fraction we actually want.
    """
    records: list[tuple[str, str, float]] = []
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as fh:
        for row in csv.reader(io.TextIOWrapper(fh, "utf-8", errors="replace")):
            if not row or row[0] != "D" or len(row) < 7:
                continue
            duid = row[5]
            if keep is not None and duid not in keep:
                continue
            try:
                records.append((duid, row[4], float(row[6])))
            except ValueError:
                continue  # a malformed SCADAVALUE is one interval, not a reason to abort

    return pd.DataFrame(records, columns=["duid", "market_time", "mw"])


def scan_duids(path: Path) -> set[str]:
    """Every DUID present in a monthly bundle."""
    return set(_read_month(path, None)["duid"].unique())


def empirical_capacity_mw(power_mw: pd.Series, registered_mw: float) -> tuple[float, str]:
    """Estimate a unit's real achievable output from what it has actually produced.

    The registry's `capacity_registered` turns out not to be the number this pipeline
    needs. It is a station-level figure and often a DC rating, while SCADA meters AC at the
    connection point. Avonlie is the clear case: registered at 245 MW, it never exceeds
    about 40% of that, so every capacity factor computed from the nameplate is compressed
    to nonsense and the clear-sky index saturates against its cap.

    Because both regression targets are normalised by this number, an inflated capacity is
    not a cosmetic error - it destroys the target. The observed high quantile is the honest
    denominator: it is what the plant demonstrably delivers.

    The 99.5th percentile rather than the maximum, so one bad meter reading or a brief
    over-delivery cannot set the scale for three years of data.
    """
    observed = float(power_mw.quantile(0.995))
    if observed <= 0:
        return registered_mw, "no output; keeping registered capacity"

    ratio = observed / registered_mw if registered_mw > 0 else float("inf")
    if CAPACITY_AGREEMENT_RANGE[0] <= ratio <= CAPACITY_AGREEMENT_RANGE[1]:
        return registered_mw, f"registered agrees with observed (ratio {ratio:.2f})"
    return observed, f"registered {registered_mw:.0f} MW vs observed {observed:.0f} MW"


def profile_matches_technology(
    power_mw: pd.Series, times: pd.DatetimeIndex, unit: ResolvedUnit
) -> tuple[bool, str]:
    """Check a unit's generation profile against the technology it was labelled with.

    Necessary because DUIDs are matched to *stations*, and a station is not one machine.
    Many solar farms share a connection point with a grid battery, and the battery's DUID
    inherits the station's `solar_utility` label. Its output is then anti-correlated with
    sunlight - it charges by day and discharges at night - so left in the corpus it
    actively teaches the model the opposite of the physics.

    The test is behavioural rather than nominal: a real PV plant generates essentially
    only while the sun is up. Anything that produces a meaningful share of its energy in
    darkness is not a PV plant, whatever the registry calls it.
    """
    capacity = unit.capacity_mw
    cf = (power_mw.to_numpy(dtype="float64") / capacity) if capacity > 0 else np.zeros(len(power_mw))
    mean_cf = float(np.mean(cf))

    if not MIN_MEAN_CF <= mean_cf <= MAX_MEAN_CF[unit.tech]:
        return False, f"mean capacity factor {mean_cf:.3f} outside plausible range"

    if unit.tech is Tech.SOLAR:
        import pvlib

        position = pvlib.solarposition.get_solarposition(times, unit.latitude, unit.longitude)
        daylight = (position["apparent_elevation"] > 5.0).to_numpy()
        total = float(cf.sum())
        if total <= 0:
            return False, "no generation recorded"
        share = float(cf[daylight].sum() / total)
        if share < MIN_DAYLIGHT_SHARE:
            return False, f"only {share:.1%} of energy generated in daylight (battery or load?)"

    return True, "ok"


MARKET_TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def market_to_utc(stamps: pd.Series, *, interval_minutes: int) -> pd.Series:
    """Market-time interval-ENDING stamps to UTC interval-STARTING timestamps.

    Two corrections, both of which are silent when wrong, which is why they live in one
    function that every AEMO table goes through rather than being repeated per caller.

    Market time is UTC+10 year-round with no daylight saving - not the local time of any
    particular state for half the year. And every settlement stamp labels the END of its
    interval, so 00:05 describes 00:00-00:05. Miss either and the data still parses, still
    aggregates, and simply describes the wrong hour; downstream that becomes a plant whose
    sun rises an hour late, or demand that peaks before the load that caused it.

    Unparseable stamps come back as NaT rather than raising, so the caller can decide
    whether a few bad rows are worth losing the month over.
    """
    market = pd.to_datetime(stamps, format=MARKET_TIME_FORMAT, errors="coerce")
    starts = market - pd.Timedelta(minutes=interval_minutes)
    return (starts - pd.Timedelta(hours=MARKET_TZ_OFFSET_H)).dt.tz_localize(UTC)


def to_hourly_utc(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert 5-minute market-time SCADA to hourly UTC means.

    Hourly *mean* is the right aggregation: it matches how both weather providers publish
    irradiance and wind, so target and features describe the same hour in the same way.
    """
    converted = market_to_utc(frame["market_time"], interval_minutes=5)
    valid = converted.notna()
    if not valid.all():
        log.warning("dropping %d rows with unparseable settlement stamps", int((~valid).sum()))

    out = frame[valid].copy()
    out["valid_time_utc"] = converted[valid]

    out["mw"] = out["mw"].clip(lower=0.0)  # auxiliary draw is real but is not generation
    hourly = (
        out.set_index("valid_time_utc")
        .groupby([pd.Grouper(freq="h"), "duid"])["mw"]
        .mean()
        .reset_index()
    )
    return hourly


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def month_range(years: float, end: datetime | None = None) -> list[tuple[int, int]]:
    """The (year, month) pairs covering the requested span, oldest first."""
    end = end or datetime.now(UTC)
    # The current month is still being written; start from the last complete one.
    # Drop the timezone before converting: a period has no offset, and pandas warns.
    anchor = pd.Timestamp(end).tz_localize(None).to_period("M") - 1
    count = int(round(years * 12))
    return [((anchor - i).year, (anchor - i).month) for i in reversed(range(count))]


def ingest(
    years: float = 3.0,
    *,
    out_dir: Path | None = None,
    raw_dir: Path | None = None,
    max_workers: int = 4,
) -> dict[str, object]:
    """Download, resolve, aggregate and write canonical power parquet for solar and wind."""
    settings = get_settings()
    settings.ensure_dirs()
    out_dir = out_dir or settings.data_canonical
    raw_dir = raw_dir or settings.data_raw / "aemo"
    raw_dir.mkdir(parents=True, exist_ok=True)

    months = month_range(years)
    log.info("AEMO ingest: %d months, %s to %s", len(months), months[0], months[-1])

    log.info("downloading %d monthly SCADA bundles (~26 MB each)", len(months))
    paths: list[Path] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _download_first,
                table_urls("DISPATCH_UNIT_SCADA", y, m),
                raw_dir / f"scada_{y}{m:02d}.zip",
                min_bytes=10**6,
            ): (y, m)
            for y, m in months
        }
        for future in futures:
            try:
                paths.append(future.result())
            except Exception as exc:  # noqa: BLE001 - one missing month must not sink the run
                log.warning("month %s unavailable: %s", futures[future], exc)

    if not paths:
        raise RuntimeError("no AEMO months could be downloaded")
    paths.sort()

    log.info("resolving DUIDs to physical sites")
    # Registry tables lag the SCADA tables by a month or two, so walk back until one loads.
    units = {}
    for ref in reversed(months):
        try:
            units = resolve_units(scan_duids(paths[-1]), raw_dir, ref)
            break
        except Exception as exc:  # noqa: BLE001
            log.debug("registry unavailable for %s (%s)", ref, exc)
    if not units:
        raise RuntimeError("could not load the DUID registry for any month in range")
    keep = set(units)
    log.info(
        "resolved %d sites (%d solar, %d wind)",
        len(units),
        sum(1 for u in units.values() if u.tech is Tech.SOLAR),
        sum(1 for u in units.values() if u.tech is Tech.WIND),
    )

    log.info("parsing %d months", len(paths))
    frames = []
    for i, path in enumerate(paths, 1):
        hourly = to_hourly_utc(_read_month(path, keep))
        frames.append(hourly)
        log.info("  [%2d/%d] %s -> %d hourly rows", i, len(paths), path.name, len(hourly))

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["duid", "valid_time_utc"], keep="last")

    written: dict[str, object] = {}
    site_records: list[SiteMeta] = []

    for tech in Tech:
        tech_units = {d: u for d, u in units.items() if u.tech is tech}
        block = combined[combined["duid"].isin(tech_units)].copy()
        if block.empty:
            continue

        counts = block.groupby("duid")["mw"].size()
        thin = counts[counts < MIN_HOURS_PER_SITE].index
        if len(thin):
            log.info("  %s: dropping %d sites with under 180 days of data", tech.value, len(thin))
            block = block[~block["duid"].isin(thin)]

        # Replace registered capacity with the observed achievable maximum where the two
        # disagree. This runs before the technology check, which is itself expressed in
        # capacity factors and would otherwise judge units against the wrong scale.
        effective_capacity: dict[str, float] = {}
        rescaled = 0
        for duid, unit_block in block.groupby("duid"):
            capacity, note = empirical_capacity_mw(unit_block["mw"], tech_units[duid].capacity_mw)
            effective_capacity[duid] = capacity
            if capacity != tech_units[duid].capacity_mw:
                rescaled += 1
                if rescaled <= 5:
                    log.info("  %s: %-12s %s", tech.value, duid, note)
        if rescaled:
            log.info("  %s: rescaled capacity for %d of %d units", tech.value, rescaled, len(effective_capacity))
        tech_units = {
            d: replace(u, capacity_mw=effective_capacity[d])
            for d, u in tech_units.items()
            if d in effective_capacity
        }

        rejected: dict[str, str] = {}
        for duid, unit_block in block.groupby("duid"):
            ok, reason = profile_matches_technology(
                unit_block["mw"], pd.DatetimeIndex(unit_block["valid_time_utc"]), tech_units[duid]
            )
            if not ok:
                rejected[duid] = reason
        if rejected:
            log.info("  %s: rejecting %d mislabelled units", tech.value, len(rejected))
            for duid, reason in sorted(rejected.items())[:8]:
                log.info("      %-12s %s", duid, reason)
            block = block[~block["duid"].isin(rejected)]

        capacity = block["duid"].map({d: u.capacity_mw for d, u in tech_units.items()})
        power = pd.DataFrame(
            {
                "site_id": "AEMO-" + block["duid"],
                "valid_time_utc": block["valid_time_utc"],
                "tech": tech.value,
                # A plant occasionally meters slightly above nameplate; clip so capacity
                # factor stays a genuine fraction.
                "power_mw": np.minimum(block["mw"].to_numpy(dtype="float64"), capacity.to_numpy()),
                "capacity_mw": capacity.to_numpy(dtype="float64"),
                "is_valid": True,
            }
        ).sort_values(["site_id", "valid_time_utc"])

        validated = validate_power(power, name=f"aemo-{tech.value}")
        path = out_dir / f"aemo_{tech.value}_power.parquet"
        validated.to_parquet(path, index=False)
        written[f"{tech.value}_power"] = path

        surviving = set(block["duid"].unique())
        site_records.extend(tech_units[d].to_site() for d in sorted(surviving))
        log.info(
            "  %s: %s rows, %d sites, %s to %s",
            tech.value,
            f"{len(validated):,}",
            validated["site_id"].nunique(),
            validated["valid_time_utc"].min().date(),
            validated["valid_time_utc"].max().date(),
        )

    written["sites"] = site_records
    if site_records:
        merge_sites_into_registry(site_records)
    return written


def merge_sites_into_registry(sites: list[SiteMeta], registry_path: Path | None = None) -> int:
    """Add or update AEMO sites in the registry, leaving every other entry untouched.

    Merged rather than overwritten so the Gujarat demo sites and any GEFCom zones survive
    a re-ingest: the registry is the lookup the API serves from, and silently dropping the
    cold-start demo sites would break the thing this platform is meant to show.
    """
    import yaml

    registry_path = registry_path or get_settings().sites_file
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {"sites": []}
    existing = {entry["site_id"]: entry for entry in raw.get("sites", [])}

    for site in sites:
        record = site.model_dump(mode="json", exclude_none=True)
        record["tech"] = site.tech.value
        # Merge into the existing record rather than replacing it. `exclude_none=True`
        # means `record` holds only what this ingest actually determined, so anything it
        # left unset - a hub height fitted separately, a mount type recovered by
        # `physics/fit_plant.py` - survives instead of being silently dropped on re-run.
        existing[site.site_id] = {**existing.get(site.site_id, {}), **record}

    raw["sites"] = [existing[k] for k in sorted(existing)]
    registry_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    log.info("registry now holds %d sites", len(raw["sites"]))
    return len(raw["sites"])


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ingest AEMO NEMWEB generation data")
    parser.add_argument("--years", type=float, default=3.0)
    args = parser.parse_args()

    result = ingest(years=args.years)
    sites = result.pop("sites")
    for key, path in result.items():
        print(f"{key:16s} -> {path}")
    print(f"{'sites':16s} -> {len(sites)} resolved")
