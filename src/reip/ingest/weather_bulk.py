"""Bulk historical weather for many sites, at genuine forecast lead times.

This module exists to fix the single biggest weakness in the first training corpus: we
could only ever measure skill at 1-24 h, because GEFCom2014 published one day-ahead run
per day. Open-Meteo's **Previous Runs API** solves it directly. For any past timestamp it
returns what the forecast said 1, 2 or 3 days beforehand, so every hour of generation can
be paired with the forecast a real operator would have had at 24 h, 48 h and 72 h notice.

That turns `horizon_h` from a nearly-constant column into a real variable, and it lets the
p10-p90 band widen with lead time because the model can finally observe that forecasts
three days out are worse than forecasts one day out.

Two operational realities shape the design:

**Quota.** The free tier allows 10,000 calls/day, 5,000/hour, and weights each request by
roughly `(days / 14) x (variables / 10)`. A three-year, 24-variable pull across 177 sites
costs about 33,000 calls - three days of quota. So every response is cached to parquet the
moment it arrives and the whole job is resumable: interrupted by a 429, it picks up at the
next uncached site rather than starting over.

**Batching.** Open-Meteo accepts comma-separated coordinates and returns one block per
location. Where that is cheaper than separate calls it is a large saving, so the fetcher
batches by default and falls back to single-site requests if a batch is rejected.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd

from reip.config import get_settings
from reip.schemas import SiteMeta, validate_weather

log = logging.getLogger(__name__)

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Two sources, and the choice is a real trade-off rather than a preference.
#
# `previous_runs` is the better one: it returns what the forecast said 1, 2 and 3 days
# before each hour, which is the only way to learn genuine 24/48/72 h behaviour and the
# thing that lets the uncertainty band widen with lead time.
#
# `historical_forecast` returns the best forecast available for each hour - roughly
# 0-24 h lead. Still a forecast, so it carries no look-ahead bias and remains a valid
# training source, but it cannot teach lead-time decay.
#
# They live on different subdomains and, usefully, meter their free quota separately. When
# Previous Runs is exhausted for the day the historical archive is still reachable, so a
# complete single-lead corpus can be built immediately and upgraded to multi-lead later.
SOURCES = ("previous_runs", "historical_forecast")

# Seven variables, not fifteen. Two reasons, and the quota is only the second.
#
# Quota cost scales directly with variable count, so each one has to earn its place across
# 150+ sites and three lead times. Direct normal irradiance is dropped because the physics
# module already derives it from GHI with the Erbs correlation when a provider omits it -
# paying for a field we can compute is the easiest saving available. Relative humidity is
# dropped because its effect on output is second-order next to cloud and temperature.
#
# The deeper reason is that every extra column is another opportunity to fit noise. With
# 150 sites and millions of rows the binding constraint on accuracy is site diversity, not
# feature count, so the trade favours more plants over wider rows.
BASE_VARIABLES: dict[str, str] = {
    "shortwave_radiation": "ghi_wm2",
    "cloud_cover": "cloud_total",
    "temperature_2m": "temp_2m_c",
    "surface_pressure": "pressure_hpa",
    "wind_speed_10m": "wind_speed_10m",
    "wind_speed_100m": "wind_speed_100m",
    "wind_direction_100m": "wind_dir_100m_deg",
}

# Lead days to request. 1/2/3 map onto the 24 h / 48 h / 72 h buckets the platform reports.
LEAD_DAYS: tuple[int, ...] = (1, 2, 3)

PERCENT_TO_FRACTION = ("cloud_total",)

MAX_RETRIES = 4
BACKOFF_BASE_S = 20.0


class QuotaExhausted(RuntimeError):
    """Raised when the API quota is spent and no further progress is possible this run."""


@dataclass
class FetchProgress:
    """Outcome of a bulk fetch, so a caller can report honestly on partial coverage."""

    completed: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    quota_hit: bool = False

    @property
    def total(self) -> int:
        return len(self.completed) + len(self.cached)


def estimate_calls(n_sites: int, days: int, n_variables: int) -> float:
    """Approximate quota cost, from Open-Meteo's published weighting."""
    return n_sites * (days / 14.0) * max(1.0, n_variables / 10.0)


def _hourly_fields(leads: tuple[int, ...], source: str) -> list[str]:
    """The hourly field names to request from a given source.

    For Previous Runs only the lead-specific `<variable>_previous_dayN` fields are asked
    for, never the base analysis field: the analysis is what actually happened, and
    training on it would reintroduce the look-ahead bias this module exists to remove.
    """
    if source == "previous_runs":
        return [f"{var}_previous_day{d}" for d in leads for var in BASE_VARIABLES]
    return list(BASE_VARIABLES)


# Quantities that cannot physically be negative. Open-Meteo occasionally returns a small
# negative (-1.0 is the observed sentinel) for irradiance in twilight hours; left alone it
# trips the ingest invariant that guards against a de-accumulation bug, masking the real
# check with a rounding artefact.
NON_NEGATIVE = ("ghi_wm2", "dni_wm2", "dhi_wm2", "cloud_total", "wind_speed_10m", "wind_speed_100m")


def _clip_nonnegative(frame: pd.DataFrame) -> None:
    for column in NON_NEGATIVE:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").clip(lower=0.0)


# Weather-grid resolution used to deduplicate requests, in degrees. Matched to ICON's
# ~11 km native grid: two plants inside one cell are served the identical forecast, so
# asking for it twice spends quota on a byte-for-byte duplicate.
GRID_RESOLUTION_DEG = 0.10


def grid_cell(site: SiteMeta, resolution: float = GRID_RESOLUTION_DEG) -> tuple[float, float]:
    """The weather-model cell a site falls in."""
    return (
        round(site.latitude / resolution) * resolution,
        round(site.longitude / resolution) * resolution,
    )


def deduplicate_by_cell(
    sites: list[SiteMeta], resolution: float = GRID_RESOLUTION_DEG
) -> dict[tuple[float, float], list[SiteMeta]]:
    """Group sites by weather cell, so each cell is fetched once and shared.

    On the AEMO fleet this collapses 155 sites to 125 cells - a 19% quota saving for no
    loss of information, because the duplicates are genuinely co-located. Several are the
    same physical station: Dundonnell's three wind DUIDs sit at identical coordinates, as
    do Bangaroo 1 and 2.
    """
    groups: dict[tuple[float, float], list[SiteMeta]] = {}
    for site in sites:
        groups.setdefault(grid_cell(site, resolution), []).append(site)
    return groups


def _cache_path(cache_dir: Path, site: SiteMeta, start: str, end: str) -> Path:
    return cache_dir / f"{site.site_id}_{start}_{end}.parquet"


def _request(params: dict, timeout: float, url: str = PREVIOUS_RUNS_URL) -> list[dict]:
    """One API call, with backoff. Always returns a list of location blocks."""
    for attempt in range(MAX_RETRIES):
        response = httpx.get(url, params=params, timeout=timeout)

        if response.status_code == 429:
            payload = response.json() if response.content else {}
            reason = str(payload.get("reason", "rate limited"))
            if "daily" in reason.lower():
                raise QuotaExhausted(reason)
            wait = BACKOFF_BASE_S * (2**attempt)
            log.warning("rate limited (%s); waiting %.0fs", reason, wait)
            time.sleep(wait)
            continue

        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else [payload]

    raise QuotaExhausted("still rate limited after retries")


def _to_canonical(
    block: dict, site: SiteMeta, leads: tuple[int, ...], source: str = "previous_runs"
) -> pd.DataFrame:
    """Reshape one location's response into canonical weather rows, one per (time, lead).

    Each lead becomes its own set of rows with its own `issue_time_utc` and `horizon_h`, so
    a single valid hour contributes three training examples: what was forecast for it 24,
    48 and 72 hours ahead.
    """
    hourly = block.get("hourly") or {}
    if "time" not in hourly:
        raise ValueError(f"{site.site_id}: response carried no hourly block")

    times = pd.to_datetime(pd.Series(hourly["time"]), utc=True)
    frames: list[pd.DataFrame] = []

    if source != "previous_runs":
        # Best-available forecast: a single series with no lead dimension. It is labelled
        # with a nominal 24 h horizon so it slots into the same schema, and the source
        # string records what it really is so the benchmark can say so plainly.
        frame = pd.DataFrame({"valid_time_utc": times})
        for api_name, column in BASE_VARIABLES.items():
            values = hourly.get(api_name)
            frame[column] = pd.Series(values, dtype="float64") if values is not None else pd.NA
        for column in PERCENT_TO_FRACTION:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce") / 100.0
        _clip_nonnegative(frame)
        frame["site_id"] = site.site_id
        frame["horizon_h"] = 24
        frame["issue_time_utc"] = frame["valid_time_utc"] - pd.Timedelta(hours=24)
        frame["source"] = "openmeteo-histfc:best"
        frame = frame[frame[list(BASE_VARIABLES.values())].notna().any(axis=1)]
        return validate_weather(frame, name=f"histfc:{site.site_id}")

    for lead in leads:
        horizon_h = 24 * lead
        frame = pd.DataFrame({"valid_time_utc": times})
        for api_name, column in BASE_VARIABLES.items():
            values = hourly.get(f"{api_name}_previous_day{lead}")
            frame[column] = pd.Series(values, dtype="float64") if values is not None else pd.NA

        for column in PERCENT_TO_FRACTION:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce") / 100.0
        _clip_nonnegative(frame)

        frame["site_id"] = site.site_id
        frame["horizon_h"] = horizon_h
        frame["issue_time_utc"] = frame["valid_time_utc"] - pd.Timedelta(hours=horizon_h)
        frame["source"] = f"openmeteo-prevrun:lead{lead}d"

        # An hour with no forecast at this lead is a gap in the archive, not a zero.
        frame = frame[frame[list(BASE_VARIABLES.values())].notna().any(axis=1)]
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    return validate_weather(combined, name=f"prevrun:{site.site_id}")


def fetch_sites(
    sites: list[SiteMeta],
    start_date: str,
    end_date: str,
    *,
    leads: tuple[int, ...] = LEAD_DAYS,
    batch_size: int = 1,
    cache_dir: Path | None = None,
    pause_s: float = 0.4,
    source: str = "previous_runs",
) -> tuple[pd.DataFrame, FetchProgress]:
    """Fetch lead-resolved weather for many sites, resumably.

    Sites already cached are skipped, so re-running after a quota stop continues where it
    left off. Returns everything available, plus a progress record naming what is missing -
    a partial corpus is usable, a silently partial one is not.
    """
    settings = get_settings()
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; choose from {SOURCES}")
    cache_dir = cache_dir or (settings.cache_dir / f"weather_{source}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = PREVIOUS_RUNS_URL if source == "previous_runs" else HISTORICAL_FORECAST_URL

    fields = _hourly_fields(leads, source)
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
    log.info(
        "%d sites x %d days x %d fields -> approx %.0f API calls (10k/day free quota)",
        len(sites),
        days,
        len(fields),
        estimate_calls(len(sites), days, len(fields)),
    )

    progress = FetchProgress()
    collected: list[pd.DataFrame] = []
    pending: list[SiteMeta] = []

    for site in sites:
        path = _cache_path(cache_dir, site, start_date, end_date)
        if path.exists():
            collected.append(pd.read_parquet(path))
            progress.cached.append(site.site_id)
        else:
            pending.append(site)

    if progress.cached:
        log.info("%d sites already cached; %d to fetch", len(progress.cached), len(pending))

    # Fetch one site per weather cell and share the result with its neighbours. Purely a
    # quota optimisation: co-located plants receive byte-identical forecasts anyway.
    cells = deduplicate_by_cell(pending)
    shared: dict[str, list[SiteMeta]] = {}
    representatives: list[SiteMeta] = []
    for members in cells.values():
        representatives.append(members[0])
        if len(members) > 1:
            shared[members[0].site_id] = members[1:]
    if len(representatives) < len(pending):
        log.info(
            "deduplicated %d sites to %d weather cells (%.0f%% fewer calls)",
            len(pending),
            len(representatives),
            100 * (1 - len(representatives) / len(pending)),
        )
    pending = representatives

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        params = {
            "latitude": ",".join(f"{s.latitude:.4f}" for s in batch),
            "longitude": ",".join(f"{s.longitude:.4f}" for s in batch),
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ",".join(fields),
            "models": "best_match",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }

        try:
            blocks = _request(params, settings.openmeteo_timeout_s * 6, url)
        except QuotaExhausted as exc:
            log.warning("quota exhausted after %d sites: %s", progress.total, exc)
            progress.quota_hit = True
            break
        except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the run
            log.warning("batch of %d failed (%s); falling back to single requests", len(batch), exc)
            blocks = []

        if blocks and len(blocks) != len(batch):
            # A mismatch means the blocks cannot be trusted to line up with the sites that
            # requested them, and mis-pairing weather with the wrong plant is far worse
            # than refetching. Discard and redo one at a time.
            log.warning("expected %d blocks, got %d; refetching singly", len(batch), len(blocks))
            blocks = []

        if not blocks:
            for site in batch:
                single = dict(params)
                single["latitude"] = f"{site.latitude:.4f}"
                single["longitude"] = f"{site.longitude:.4f}"
                try:
                    blocks.extend(_request(single, settings.openmeteo_timeout_s * 6, url))
                except QuotaExhausted:
                    progress.quota_hit = True
                    break
                except Exception as exc:  # noqa: BLE001
                    progress.failed[site.site_id] = str(exc)
                    blocks.append({})
            if progress.quota_hit:
                break

        for site, block in zip(batch, blocks, strict=False):
            if not block:
                continue
            try:
                frame = _to_canonical(block, site, leads, source)
            except Exception as exc:  # noqa: BLE001
                progress.failed[site.site_id] = str(exc)
                continue
            # Persist immediately: quota spent on a response we then lose is unrecoverable.
            frame.to_parquet(_cache_path(cache_dir, site, start_date, end_date), index=False)
            collected.append(frame)
            progress.completed.append(site.site_id)

            # Re-label the same weather for every other site in this cell.
            for twin in shared.get(site.site_id, []):
                copy = frame.copy()
                copy["site_id"] = twin.site_id
                copy.to_parquet(_cache_path(cache_dir, twin, start_date, end_date), index=False)
                collected.append(copy)
                progress.completed.append(twin.site_id)

        if progress.total and progress.total % 20 == 0:
            log.info("  %d/%d sites", progress.total, len(sites))
        time.sleep(pause_s)

    if not collected:
        raise RuntimeError("no weather retrieved for any site")

    return pd.concat(collected, ignore_index=True), progress
