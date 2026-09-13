"""Load-centre weather: the demand model's other half.

Five cells, one per NEM region, at the population centre rather than at the generation
fleet. Fetched through the same `weather_bulk` machinery as the plant weather so the
canonical schema, the caching and the resumability all come for free.

Two deliberate choices:

**Forecasts, not reanalysis.** The obvious source for three years of city temperature is
the ERA5 archive, and it would be wrong. ERA5 is what the weather *was*; at serve time the
model will be handed what the weather is *predicted to be*, and a model trained on truth
and served on forecasts degrades silently. `historical_forecast` returns the archived
output of the live forecast models - same variables, same biases, no look-ahead.

**A separate endpoint from the multi-lead plant fetch.** Previous Runs and Historical
Forecast live on different subdomains and meter their free quota separately, so these 391
calls do not compete with the 9,000-call plant extraction running alongside them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from reip.config import get_settings
from reip.ingest.weather_bulk import fetch_sites
from reip.models.demand.features import LOAD_CENTRES
from reip.schemas import SiteMeta, Tech

log = logging.getLogger(__name__)

CORPUS_NAME = "load_centres"


def load_centre_sites() -> list[SiteMeta]:
    """Transient `SiteMeta` for each load centre.

    Not added to the registry: these are weather sampling points, not generators, and
    putting them in the site list would make them appear in `/sites` and in any capacity
    roll-up. `fetch_sites` only reads id, latitude and longitude, so the technology and
    capacity here are placeholders that nothing consumes.
    """
    return [
        SiteMeta(
            site_id=f"LOAD-{region}",
            name=f"{city} load centre ({region})",
            tech=Tech.SOLAR,
            capacity_mw=1.0,
            latitude=lat,
            longitude=lon,
            timezone=tz,
            market_region=region,
        ).defaulted
        for region, (city, lat, lon, tz) in LOAD_CENTRES.items()
    ]


def fetch(start_date: str, end_date: str, *, out_path: Path | None = None) -> pd.DataFrame:
    """Fetch and cache load-centre weather for every region."""
    settings = get_settings()
    settings.ensure_dirs()
    out_path = out_path or (settings.data_canonical / f"{CORPUS_NAME}_weather.parquet")

    sites = load_centre_sites()
    log.info("fetching load-centre weather for %d regions, %s to %s", len(sites), start_date, end_date)

    weather, progress = fetch_sites(
        sites, start_date, end_date, source="historical_forecast", batch_size=1
    )
    if progress.failed:
        log.warning("failed regions: %s", progress.failed)
    if progress.quota_hit:
        log.warning("stopped on quota with %d/%d regions; re-run to resume", progress.total, len(sites))

    weather.to_parquet(out_path, index=False)
    log.info(
        "wrote %s rows to %s (%s to %s)",
        f"{len(weather):,}",
        out_path,
        weather["valid_time_utc"].min(),
        weather["valid_time_utc"].max(),
    )
    return weather


def load(path: Path | None = None) -> pd.DataFrame:
    settings = get_settings()
    path = path or (settings.data_canonical / f"{CORPUS_NAME}_weather.parquet")
    if not path.exists():
        raise FileNotFoundError(
            f"no load-centre weather at {path}; run `python -m reip.models.demand.weather`"
        )
    return pd.read_parquet(path)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Fetch weather at each region's load centre")
    parser.add_argument("--start", default="2023-09-01")
    parser.add_argument("--end", default="2026-08-31")
    args = parser.parse_args()

    frame = fetch(args.start, args.end)
    print(frame.groupby("site_id")["temp_2m_c"].describe().to_string())
