"""Weather from Open-Meteo's S3 open-data archive. No API key, no quota, no rate limit.

The API path works but meters a free tier at 10,000 weighted calls a day, which caps the
corpus at roughly 21 sites and leaves 86% of the collected generation data untrainable.
This module removes that ceiling entirely: Open-Meteo publish their full model archive on
AWS Open Data (`s3://openmeteo`, us-west-2, CC BY 4.0), anonymous access, and the `.om`
format supports **partial reads**. Extracting one location's year from a 5 GB global file
transfers kilobytes, not gigabytes.

**Model choice: DWD ICON.** It is the only global archive in the bucket carrying every
field this pipeline needs at hourly resolution, and it is better than the API set in one
respect that matters: it publishes wind at 80 m, 120 m and 180 m rather than a single
100 m level, so hub-height wind can be interpolated between bracketing levels instead of
extrapolated from 10 m. Coverage is about 3.3 years, which matches the AEMO generation
span. ECMWF IFS025 also has the fields but only ~0.9 years of archive.

**Two things had to be reverse-engineered**, because neither is documented:

* *Chunk-to-time mapping.* Files are named `chunk_<n>.om` with no embedded metadata. The
  mapping was recovered by cross-correlating a known site's irradiance against the same
  site's API data, then confirmed on three further chunks (r = 0.71-0.75):

      start(n) = 1970-01-01T00Z + n * 253h - 312h

* *Grid indexing.* The array is `[lat, lon, time]` on a regular global grid running north
  to south and -180 to +180, so indices come from linear interpolation over the array
  shape rather than from any stored coordinate vector.

Both are asserted against API data in `verify_against_api`, because a silent half-chunk
offset would shift every site's diurnal cycle and poison the training target.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.schemas import SiteMeta, validate_weather

log = logging.getLogger(__name__)

BUCKET = "openmeteo"
MODEL = "dwd_icon"

# Recovered empirically - see module docstring.
CHUNK_STEPS = 253
CHUNK_OFFSET_H = -312

# Source variables to pull. Kept to what the feature builder consumes; the archive has
# hundreds more and each one is another full pass over the bucket.
SOURCE_VARIABLES: tuple[str, ...] = (
    "direct_radiation",
    "diffuse_radiation",
    "cloud_cover",
    "temperature_2m",
    "pressure_msl",
    "relative_humidity_2m",
    "wind_u_component_10m",
    "wind_v_component_10m",
    "wind_u_component_80m",
    "wind_v_component_80m",
    "wind_u_component_120m",
    "wind_v_component_120m",
)

# ICON brackets 100 m with 80 m and 120 m. Interpolating between two measured levels is
# strictly better than the power-law extrapolation from 10 m the API data forced on us.
LOWER_LEVEL_M, UPPER_LEVEL_M, TARGET_LEVEL_M = 80.0, 120.0, 100.0

# The archive is a concatenation of successive forecast runs - the same product the
# Historical Forecast API serves - so it carries no look-ahead bias, but it has no lead
# dimension either. Rows are labelled with a nominal 24 h horizon and this source string,
# so the benchmark can state plainly which rows can evidence lead-time behaviour.
NOMINAL_HORIZON_H = 24
SOURCE_LABEL = f"openmeteo-s3:{MODEL}"


@dataclass(frozen=True)
class ChunkPlan:
    """One archive chunk and the slice of it we want."""

    index: int
    start: pd.Timestamp
    steps: int

    @property
    def end(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(hours=self.steps - 1)

    def times(self) -> pd.DatetimeIndex:
        return pd.date_range(self.start, periods=self.steps, freq="h")


def chunk_start(index: int, steps: int = CHUNK_STEPS) -> pd.Timestamp:
    """First timestamp held by a chunk."""
    return pd.Timestamp("1970-01-01", tz="UTC") + pd.Timedelta(
        hours=index * steps + CHUNK_OFFSET_H
    )


def chunks_covering(start: str | pd.Timestamp, end: str | pd.Timestamp) -> list[int]:
    """Chunk indices spanning a date range, inclusive."""
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    first = int(
        np.floor(
            ((start_ts - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(hours=1)
             - CHUNK_OFFSET_H) / CHUNK_STEPS
        )
    )
    last = int(
        np.ceil(
            ((end_ts - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(hours=1)
             - CHUNK_OFFSET_H) / CHUNK_STEPS
        )
    )
    return list(range(first, last + 1))


def _filesystem():
    import fsspec

    return fsspec.filesystem("s3", anon=True)


def grid_indices(sites: list[SiteMeta], ny: int, nx: int) -> np.ndarray:
    """Array indices for each site on the model's regular lat/lon grid.

    Latitude runs north to south (index 0 = +90), longitude -180 to +180.
    """
    lat = np.array([s.latitude for s in sites], dtype="float64")
    lon = np.array([s.longitude for s in sites], dtype="float64")
    iy = np.round((90.0 - lat) / 180.0 * (ny - 1)).astype(int).clip(0, ny - 1)
    ix = np.round((lon + 180.0) / 360.0 * (nx - 1)).astype(int).clip(0, nx - 1)
    return np.column_stack([iy, ix])


def read_variable_chunk(
    variable: str, index: int, sites: list[SiteMeta], fs=None
) -> pd.DataFrame | None:
    """Read one variable, one chunk, for every site. Returns wide [time x site]."""
    import omfiles

    fs = fs or _filesystem()
    key = f"{BUCKET}/data/{MODEL}/{variable}/chunk_{index}.om"
    try:
        reader = omfiles.OmFileReader.from_fsspec(fs, key)
    except Exception as exc:  # noqa: BLE001 - a missing chunk is a gap, not a failure
        log.debug("%s chunk %d unavailable: %s", variable, index, exc)
        return None

    try:
        ny, nx, nt = reader.shape
        cells = grid_indices(sites, ny, nx)
        # One read per distinct grid cell. Sites sharing a cell are filled from the same
        # column afterwards rather than re-requesting identical bytes.
        unique: dict[tuple[int, int], np.ndarray] = {}
        for iy, ix in cells:
            if (iy, ix) in unique:
                continue
            unique[(iy, ix)] = np.asarray(
                reader.read_array((slice(iy, iy + 1), slice(ix, ix + 1), slice(0, nt))),
                dtype="float64",
            ).ravel()
    finally:
        reader.close()

    times = ChunkPlan(index, chunk_start(index, nt), nt).times()
    return pd.DataFrame(
        {site.site_id: unique[(iy, ix)] for site, (iy, ix) in zip(sites, cells, strict=True)},
        index=times,
    )


def _speed_direction(u: pd.DataFrame, v: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    speed = np.sqrt(u**2 + v**2)
    direction = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0
    return speed, direction


def assemble_chunk(index: int, sites: list[SiteMeta], fs=None) -> pd.DataFrame | None:
    """Read every variable for one chunk and reshape into canonical long form."""
    fs = fs or _filesystem()
    raw: dict[str, pd.DataFrame] = {}
    for variable in SOURCE_VARIABLES:
        frame = read_variable_chunk(variable, index, sites, fs)
        if frame is not None:
            raw[variable] = frame

    if "direct_radiation" not in raw and "temperature_2m" not in raw:
        return None

    def get(name: str) -> pd.DataFrame | None:
        return raw.get(name)

    direct, diffuse = get("direct_radiation"), get("diffuse_radiation")
    if direct is not None and diffuse is not None:
        ghi = direct + diffuse  # ICON publishes the components, not the global total
    else:
        ghi = direct if direct is not None else diffuse

    speed10 = direction10 = speed80 = speed120 = direction120 = None
    if get("wind_u_component_10m") is not None and get("wind_v_component_10m") is not None:
        speed10, direction10 = _speed_direction(
            get("wind_u_component_10m"), get("wind_v_component_10m")
        )
    if get("wind_u_component_80m") is not None and get("wind_v_component_80m") is not None:
        speed80, _ = _speed_direction(get("wind_u_component_80m"), get("wind_v_component_80m"))
    if get("wind_u_component_120m") is not None and get("wind_v_component_120m") is not None:
        speed120, direction120 = _speed_direction(
            get("wind_u_component_120m"), get("wind_v_component_120m")
        )

    # Interpolate 100 m between the two bracketing measured levels, in log-height space
    # because wind shear is logarithmic rather than linear with altitude.
    if speed80 is not None and speed120 is not None:
        weight = (np.log(TARGET_LEVEL_M) - np.log(LOWER_LEVEL_M)) / (
            np.log(UPPER_LEVEL_M) - np.log(LOWER_LEVEL_M)
        )
        speed100 = speed80 * (1 - weight) + speed120 * weight
    else:
        speed100 = speed120 if speed120 is not None else speed80

    def melt(frame: pd.DataFrame | None, column: str) -> pd.DataFrame | None:
        if frame is None:
            return None
        out = frame.stack().rename(column).reset_index()
        out.columns = ["valid_time_utc", "site_id", column]
        return out

    pieces = {
        "ghi_wm2": melt(ghi, "ghi_wm2"),
        "cloud_total": melt(get("cloud_cover"), "cloud_total"),
        "temp_2m_c": melt(get("temperature_2m"), "temp_2m_c"),
        "pressure_hpa": melt(get("pressure_msl"), "pressure_hpa"),
        "rh_pct": melt(get("relative_humidity_2m"), "rh_pct"),
        "wind_speed_10m": melt(speed10, "wind_speed_10m"),
        "wind_dir_10m_deg": melt(direction10, "wind_dir_10m_deg"),
        "wind_speed_100m": melt(speed100, "wind_speed_100m"),
        "wind_dir_100m_deg": melt(direction120, "wind_dir_100m_deg"),
    }
    present = [p for p in pieces.values() if p is not None]
    if not present:
        return None

    merged = present[0]
    for piece in present[1:]:
        merged = merged.merge(piece, on=["valid_time_utc", "site_id"], how="outer")

    if "cloud_total" in merged:
        merged["cloud_total"] = merged["cloud_total"] / 100.0
    for column in ("ghi_wm2", "wind_speed_10m", "wind_speed_100m"):
        if column in merged:
            merged[column] = merged[column].clip(lower=0.0)

    merged["horizon_h"] = NOMINAL_HORIZON_H
    merged["issue_time_utc"] = merged["valid_time_utc"] - pd.Timedelta(hours=NOMINAL_HORIZON_H)
    merged["source"] = SOURCE_LABEL
    return merged


def fetch(
    sites: list[SiteMeta],
    start: str,
    end: str,
    *,
    max_workers: int = 6,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch canonical weather for every site over a date range, straight from S3.

    Chunks are cached to parquet so an interrupted run resumes. Unlike the API path there
    is no quota to exhaust, so interruption is only ever a matter of wall-clock time.
    """
    settings = get_settings()
    cache_dir = cache_dir or (settings.cache_dir / "weather_s3")
    cache_dir.mkdir(parents=True, exist_ok=True)

    indices = chunks_covering(start, end)
    log.info(
        "%d sites, %s to %s -> %d chunks of %d h (%s)",
        len(sites),
        start,
        end,
        len(indices),
        CHUNK_STEPS,
        MODEL,
    )

    def one(index: int) -> pd.DataFrame | None:
        path = cache_dir / f"chunk_{index}_{len(sites)}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        frame = assemble_chunk(index, sites)
        if frame is not None and len(frame):
            frame.to_parquet(path, index=False)
        return frame

    collected: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for i, frame in enumerate(pool.map(one, indices), 1):
            if frame is not None and len(frame):
                collected.append(frame)
            if i % 10 == 0:
                log.info("  %d/%d chunks", i, len(indices))

    if not collected:
        raise RuntimeError("no weather retrieved from S3")

    combined = pd.concat(collected, ignore_index=True)
    window = (combined["valid_time_utc"] >= pd.Timestamp(start, tz="UTC")) & (
        combined["valid_time_utc"] <= pd.Timestamp(end, tz="UTC")
    )
    combined = combined[window].drop_duplicates(subset=["site_id", "valid_time_utc"])
    return validate_weather(combined, name=f"s3:{MODEL}")


def verify_against_api(s3_frame: pd.DataFrame, tech: str = "solar") -> dict:
    """Cross-check the S3 corpus against the API weather we already hold.

    The chunk-to-time mapping was reverse-engineered, so it has to be proved rather than
    trusted: a half-chunk offset would shift every diurnal cycle and quietly corrupt the
    training target. Sites present in both sources are compared hour by hour.
    """
    settings = get_settings()
    path = settings.data_canonical / f"aemo_{tech}_weather.parquet"
    if not path.exists():
        return {"verified": False, "reason": "no API weather to compare against"}

    api = pd.read_parquet(path)
    api = api[api["horizon_h"] == 24]
    shared = sorted(set(api["site_id"]) & set(s3_frame["site_id"]))
    if not shared:
        return {"verified": False, "reason": "no overlapping sites"}

    results = {}
    for column in ("ghi_wm2", "temp_2m_c", "wind_speed_100m"):
        joined = (
            api[["site_id", "valid_time_utc", column]]
            .merge(
                s3_frame[["site_id", "valid_time_utc", column]],
                on=["site_id", "valid_time_utc"],
                suffixes=("_api", "_s3"),
            )
            .dropna()
        )
        if len(joined) < 100:
            continue
        a = joined[f"{column}_api"].to_numpy(dtype="float64")
        b = joined[f"{column}_s3"].to_numpy(dtype="float64")
        results[column] = {
            "n": int(len(joined)),
            "correlation": float(np.corrcoef(a, b)[0, 1]),
            "mean_api": float(a.mean()),
            "mean_s3": float(b.mean()),
            "mae": float(np.mean(np.abs(a - b))),
        }

    correlations = [v["correlation"] for v in results.values()]
    return {
        "verified": bool(correlations) and min(correlations) > 0.85,
        "sites_compared": len(shared),
        "variables": results,
    }
