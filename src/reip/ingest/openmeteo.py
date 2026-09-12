"""Open-Meteo client: the serving-side weather source.

Produces exactly the same canonical frame as `ingest/gefcom.py`, which is what allows one
feature module to serve both training and inference.

Three endpoints, three jobs:

* **forecast** - the live 1-72 h run. This is what `/forecast` calls.
* **historical forecast** - the archive of past live runs. Same models, same variables,
  same alignment as the live endpoint, which is precisely why it is the right source for
  training a correction on top of it.
* **archive (ERA5)** - reanalysis. Verification ground truth only. It is deliberately
  never used as a model feature: reanalysis is the weather that *happened*, assimilated
  after the fact, and it does not exist at forecast time. Training on it would produce a
  model that cannot be served.

Units are pinned explicitly on every request. Open-Meteo defaults wind speed to km/h, and
silently training on km/h then serving m/s would scale every wind feature by 3.6.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from reip.config import get_settings
from reip.schemas import MAX_HORIZON_H, SiteMeta, validate_weather

log = logging.getLogger(__name__)

# Open-Meteo variable name -> canonical column name.
HOURLY_VARIABLES: dict[str, str] = {
    "shortwave_radiation": "ghi_wm2",
    "direct_normal_irradiance": "dni_wm2",
    "diffuse_radiation": "dhi_wm2",
    "cloud_cover": "cloud_total",
    "cloud_cover_low": "cloud_low",
    "cloud_cover_mid": "cloud_mid",
    "cloud_cover_high": "cloud_high",
    "temperature_2m": "temp_2m_c",
    "relative_humidity_2m": "rh_pct",
    "surface_pressure": "pressure_hpa",
    "precipitation": "precip_mm",
    "wind_speed_10m": "wind_speed_10m",
    "wind_speed_100m": "wind_speed_100m",
    "wind_direction_10m": "wind_dir_10m_deg",
    "wind_direction_100m": "wind_dir_100m_deg",
}

# Cloud cover arrives as a percentage; the canonical contract carries a 0-1 fraction to
# match GEFCom's total cloud cover.
PERCENT_TO_FRACTION = ("cloud_total", "cloud_low", "cloud_mid", "cloud_high")

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "openmeteo_sample.json"


class WeatherUnavailable(RuntimeError):
    """Raised when no weather could be obtained from any source, including the fixture."""


def _cache_key(url: str, params: dict[str, Any]) -> str:
    blob = json.dumps({"url": url, "params": params}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _fetch(url: str, params: dict[str, Any], *, use_cache: bool = True) -> dict[str, Any]:
    """GET with an on-disk TTL cache.

    The cache keeps repeated demo calls instant and keeps us inside the free tier's
    10k requests/day, which one enthusiastic dashboard refresh loop could otherwise burn
    through in an afternoon.
    """
    settings = get_settings()
    settings.ensure_dirs()
    path = settings.cache_dir / f"om_{_cache_key(url, params)}.json"

    if use_cache and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < settings.weather_cache_ttl_s:
            return json.loads(path.read_text(encoding="utf-8"))

    response = httpx.get(url, params=params, timeout=settings.openmeteo_timeout_s)
    response.raise_for_status()
    payload = response.json()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _to_canonical(
    payload: dict[str, Any],
    *,
    site_id: str,
    issue_time: pd.Timestamp,
    source: str,
) -> pd.DataFrame:
    """Map an Open-Meteo hourly block onto the canonical weather contract."""
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        raise WeatherUnavailable(f"response carried no hourly block: {list(payload)[:6]}")

    times = pd.to_datetime(pd.Series(hourly["time"]), utc=True)
    frame = pd.DataFrame({"valid_time_utc": times})

    for api_name, column in HOURLY_VARIABLES.items():
        values = hourly.get(api_name)
        frame[column] = pd.Series(values, dtype="float64") if values is not None else pd.NA

    for column in PERCENT_TO_FRACTION:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce") / 100.0

    frame["site_id"] = site_id
    frame["issue_time_utc"] = issue_time
    frame["horizon_h"] = (
        ((frame["valid_time_utc"] - issue_time).dt.total_seconds() / 3600.0).round().astype("int16")
    )
    frame["source"] = source

    return frame


def fetch_forecast(
    site: SiteMeta,
    *,
    horizon_h: int = MAX_HORIZON_H,
    issue_time: pd.Timestamp | None = None,
    allow_fixture: bool = True,
) -> pd.DataFrame:
    """Live 1..horizon_h forecast for a site. Works for any coordinates on earth.

    Falls back to a bundled fixture if the network is unavailable, tagging the frame
    `source="fixture"` so a demo running on cached weather can never be mistaken for one
    running on live weather.
    """
    settings = get_settings()
    issue_time = issue_time or pd.Timestamp.now(tz=UTC).floor("h")

    params: dict[str, Any] = {
        "latitude": round(site.latitude, 4),
        "longitude": round(site.longitude, 4),
        "hourly": ",".join(HOURLY_VARIABLES),
        "models": settings.openmeteo_model,
        "wind_speed_unit": "ms",  # pinned: the API default is km/h
        "timezone": "UTC",
        "forecast_days": min(16, max(2, (horizon_h // 24) + 2)),
    }
    source = f"openmeteo:{settings.openmeteo_model}"

    try:
        payload = _fetch(settings.openmeteo_forecast_url, params)
    except Exception as exc:  # noqa: BLE001 - any upstream failure should degrade, not crash
        if not (allow_fixture and FIXTURE_PATH.exists()):
            raise WeatherUnavailable(f"Open-Meteo unreachable and no fixture: {exc}") from exc
        log.warning("Open-Meteo unreachable (%s); falling back to bundled fixture", exc)
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        source = "fixture"
        # Re-base the fixture's timeline onto the requested issue time so horizons stay
        # meaningful; the weather itself is stale but the shape is right for a demo.
        fixture_start = pd.to_datetime(payload["hourly"]["time"][0], utc=True)
        shift = issue_time + pd.Timedelta(hours=1) - fixture_start
        payload["hourly"]["time"] = [
            (pd.to_datetime(t, utc=True) + shift).isoformat() for t in payload["hourly"]["time"]
        ]

    frame = _to_canonical(payload, site_id=site.site_id, issue_time=issue_time, source=source)
    frame = frame[(frame["horizon_h"] >= 1) & (frame["horizon_h"] <= horizon_h)]

    if frame.empty:
        raise WeatherUnavailable(f"no forecast hours in 1..{horizon_h} for {site.site_id}")

    return validate_weather(frame, name=f"openmeteo:{site.site_id}")


def fetch_historical_forecast(
    site: SiteMeta,
    start_date: str,
    end_date: str,
    *,
    issue_time: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Archived past runs of the live forecast models.

    The correct training source for a bias-correction model: same models, same variables
    and same time alignment as the live endpoint, so a correction learned here transfers
    to what `/forecast` will actually see.
    """
    settings = get_settings()
    params: dict[str, Any] = {
        "latitude": round(site.latitude, 4),
        "longitude": round(site.longitude, 4),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARIABLES),
        "models": settings.openmeteo_model,
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    payload = _fetch(settings.openmeteo_historical_forecast_url, params)

    frame = _to_canonical(
        payload,
        site_id=site.site_id,
        issue_time=issue_time or pd.to_datetime(f"{start_date}T00:00:00Z"),
        source=f"openmeteo-archive:{settings.openmeteo_model}",
    )
    return validate_weather(frame, name=f"openmeteo-archive:{site.site_id}")


def save_fixture(site: SiteMeta, path: Path | None = None) -> Path:
    """Capture one live response as the offline fallback fixture."""
    settings = get_settings()
    path = path or FIXTURE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    params = {
        "latitude": round(site.latitude, 4),
        "longitude": round(site.longitude, 4),
        "hourly": ",".join(HOURLY_VARIABLES),
        "models": settings.openmeteo_model,
        "wind_speed_unit": "ms",
        "timezone": "UTC",
        "forecast_days": 4,
    }
    payload = _fetch(settings.openmeteo_forecast_url, params, use_cache=False)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


if __name__ == "__main__":
    import argparse

    from reip.sites.registry import SiteRegistry

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Fetch an Open-Meteo forecast")
    parser.add_argument("--site", default="GJ-SOLAR-CHARANKA")
    parser.add_argument("--hours", type=int, default=MAX_HORIZON_H)
    parser.add_argument("--save-fixture", action="store_true")
    args = parser.parse_args()

    target = SiteRegistry.load().get(args.site)
    if args.save_fixture:
        print("fixture written to", save_fixture(target))
    else:
        df = fetch_forecast(target, horizon_h=args.hours)
        print(f"{len(df)} rows, source={df['source'].iloc[0]}")
        print(
            df[
                [
                    "valid_time_utc",
                    "horizon_h",
                    "ghi_wm2",
                    "cloud_total",
                    "temp_2m_c",
                    "wind_speed_100m",
                ]
            ]
            .head(12)
            .to_string(index=False)
        )
