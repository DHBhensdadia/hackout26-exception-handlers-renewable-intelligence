"""Recover the coordinates of an anonymised solar site from its own generation record.

GEFCom2014 does not say where its plants are. The solar target is a clear-sky index, and
the clear-sky reference needs a location, so the location has to come from somewhere.
It is recoverable because a PV plant is an astronomical instrument: its output encodes
the sun's position over the site every hour of the year.

Two independent signals, exploited in order:

* **Longitude** from the timing of solar noon. The power-weighted centroid of each day's
  output falls at local solar noon, and the offset of that from 12:00 UTC is longitude
  divided by 15 degrees per hour. This is a direct calculation, not a search.

* **Latitude** from the seasonal envelope. Day length and peak elevation vary through the
  year by an amount that is a strong function of latitude - near the equator barely at
  all, at high latitude enormously. Searching latitude to match the observed seasonal
  swing pins it down, and the sign is unambiguous because the hemispheres are in
  opposite seasons.

The result is written back to the registry with `location_is_estimated: true`, and test
T4 checks the fitted clear-sky curve against the empirical envelope independently.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from reip.schemas import SiteMeta, Tech

log = logging.getLogger(__name__)

LAT_GRID_COARSE = np.arange(-60.0, 60.5, 2.0)
LAT_REFINE_HALFWIDTH = 2.0
LAT_REFINE_STEP = 0.25
# Sampling stride in days. The seasonal signal is slow, so every third day carries it
# just as well as every day and costs a third as much pvlib work per candidate.
DAY_STRIDE = 3


def estimate_longitude(power: pd.Series) -> float:
    """Longitude in degrees east, from the power-weighted timing of solar noon.

    Uses a circular mean over the 24-hour clock rather than an arithmetic one: a plant
    whose noon straddles 00:00 UTC would otherwise average to midday and land the site
    on the opposite side of the planet.
    """
    p = power.clip(lower=0.0).astype("float64")
    if p.sum() <= 0:
        raise ValueError("no positive generation; cannot locate site")

    hour = p.index.hour + p.index.minute / 60.0
    angle = 2.0 * np.pi * hour / 24.0
    mean_angle = np.arctan2(
        np.average(np.sin(angle), weights=p), np.average(np.cos(angle), weights=p)
    )
    noon_utc = (mean_angle % (2.0 * np.pi)) * 24.0 / (2.0 * np.pi)

    lon = (12.0 - noon_utc) * 15.0
    return float((lon + 180.0) % 360.0 - 180.0)


def _daylength_signature(series: pd.Series) -> np.ndarray:
    """Mean hours of generation per day, by day of year.

    Day length rather than daily energy, because only day length is *purely geometric*.
    Seasonal energy conflates two things: the sun's elevation, which depends on latitude,
    and seasonal cloud, which does not. On a monsoon or maritime climate the winter
    energy deficit is mostly weather, and fitting to it drives the estimate to an absurd
    latitude - as it did here, placing an Australian plant in the Southern Ocean.

    Cloud reduces how *hard* a plant runs but barely changes *whether* it runs at all, so
    counting generating hours isolates the geometry. Averaging per day-of-year and
    smoothing across the calendar suppresses the residual weather noise; the raw daily
    min and max are dominated by outliers.
    """
    threshold = 0.01 * float(series.max())
    if threshold <= 0:
        raise ValueError("no positive generation; cannot locate site")

    generating = (series.clip(lower=0.0) > threshold).resample("1D").sum()
    by_doy = generating.groupby(generating.index.dayofyear).mean()
    full = by_doy.reindex(range(1, 367)).interpolate(limit_direction="both")

    # Circular smoothing: 31 December and 1 January are adjacent, so tile before rolling.
    tiled = pd.concat([full, full, full])
    smoothed = tiled.rolling(15, min_periods=1, center=True).mean()
    return smoothed.iloc[366 : 2 * 366].to_numpy(dtype="float64")


def analytic_daylength(latitude: float) -> np.ndarray:
    """Hours between sunrise and sunset for each day of year, from spherical astronomy.

        cos(H0) = -tan(phi) * tan(delta)
        day length = 2 * H0 / 15

    Computed in closed form rather than by running a solar-position model over the year:
    it is exact, it is instant, and it lets the latitude sweep be dense.
    """
    doy = np.arange(1, 367, dtype="float64")
    declination = np.deg2rad(23.45 * np.sin(np.deg2rad(360.0 * (284.0 + doy) / 365.0)))
    phi = np.deg2rad(latitude)
    # Clamped for the polar cases, where the sun never rises or never sets.
    cos_h0 = np.clip(-np.tan(phi) * np.tan(declination), -1.0, 1.0)
    return 2.0 * np.degrees(np.arccos(cos_h0)) / 15.0


def _centred(curve: np.ndarray) -> np.ndarray:
    """Remove the mean, keeping only the seasonal swing.

    The observed curve counts hours where output clears a detection threshold, so it sits
    a fixed amount below true sunrise-to-sunset. That offset carries no information about
    latitude - the *amplitude and phase of the swing* carry all of it - and subtracting
    the mean removes the need to calibrate the threshold at all.
    """
    return curve - np.nanmean(curve)


def fit_latitude(
    power: pd.Series,
    longitude: float,
    template: SiteMeta,
    *,
    lat_grid: np.ndarray = LAT_GRID_COARSE,
) -> tuple[float, float]:
    """Search latitude to match the observed seasonal envelope. Returns (lat, rmse)."""
    observed = _centred(_daylength_signature(power))

    def score(lat: float) -> float:
        return float(np.sqrt(np.nanmean((_centred(analytic_daylength(lat)) - observed) ** 2)))

    coarse = {lat: score(lat) for lat in lat_grid}
    best_coarse = min(coarse, key=coarse.__getitem__)

    fine_grid = np.arange(
        best_coarse - LAT_REFINE_HALFWIDTH,
        best_coarse + LAT_REFINE_HALFWIDTH + LAT_REFINE_STEP,
        LAT_REFINE_STEP,
    )
    fine = {float(lat): score(float(lat)) for lat in fine_grid}
    best = min(fine, key=fine.__getitem__)
    return best, fine[best]


def fit_site(power: pd.Series, template: SiteMeta) -> tuple[SiteMeta, dict[str, float]]:
    """Recover coordinates for one anonymised solar site.

    `power` must be a UTC-indexed hourly series of that site's measured output.
    """
    if template.tech is not Tech.SOLAR:
        raise ValueError("location fitting uses the solar day cycle; wind carries no such signal")

    lon = estimate_longitude(power)
    lat, rmse = fit_latitude(power, lon, template)

    fitted = template.model_copy(
        update={
            "latitude": lat,
            "longitude": lon,
            "tilt_deg": min(abs(lat), 40.0),
            "azimuth_deg": 180.0 if lat >= 0 else 0.0,
            "location_is_estimated": True,
        }
    )
    diagnostics = {"latitude": lat, "longitude": lon, "daylength_rmse_h": rmse}
    log.info(
        "%s fitted to lat %.2f lon %.2f (day-length RMSE %.3f h)",
        template.site_id,
        lat,
        lon,
        rmse,
    )
    return fitted, diagnostics


# Above this, the day-length curve does not really match and the recovered coordinates
# should not be trusted; the caller falls back to an empirical clear-sky envelope.
MAX_ACCEPTABLE_DAYLENGTH_RMSE_H = 0.5


def fit_all_solar_sites(
    power_frame: pd.DataFrame, registry_path=None
) -> dict[str, dict[str, float]]:
    """Fit every GEFCom solar site and write the coordinates back to the registry."""
    import yaml

    from reip.config import get_settings
    from reip.sites.registry import SiteRegistry

    registry_path = registry_path or get_settings().sites_file
    registry = SiteRegistry.load(registry_path)
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    by_id = {entry["site_id"]: entry for entry in raw["sites"]}

    results: dict[str, dict[str, float]] = {}
    for site in registry.by_tech(Tech.SOLAR):
        if not site.location_is_estimated:
            continue  # a real site with known coordinates; nothing to recover
        series = (
            power_frame[power_frame["site_id"] == site.site_id]
            .set_index("valid_time_utc")
            .sort_index()["power_mw"]
            .astype("float64")
        )
        if series.empty:
            log.warning("%s: no power rows, skipping", site.site_id)
            continue

        fitted, diag = fit_site(series, site)
        results[site.site_id] = diag

        if diag["daylength_rmse_h"] > MAX_ACCEPTABLE_DAYLENGTH_RMSE_H:
            log.warning(
                "%s: day-length RMSE %.3f h exceeds %.2f h; keeping placeholder "
                "coordinates and flagging for the empirical clear-sky fallback",
                site.site_id,
                diag["daylength_rmse_h"],
                MAX_ACCEPTABLE_DAYLENGTH_RMSE_H,
            )
            continue

        entry = by_id[site.site_id]
        entry["latitude"] = round(fitted.latitude, 4)
        entry["longitude"] = round(fitted.longitude, 4)
        # Explicit None checks, not `or`. A southern-hemisphere array faces north, i.e.
        # azimuth 0.0 - which is falsy, so `fitted.azimuth_deg or 180.0` silently turns
        # every southern site around to face south. That points the modules away from the
        # winter sun and collapses the modelled clear-sky reference to near zero, which
        # in turn makes the clear-sky index explode. Nothing raises; the target just
        # quietly becomes noise.
        entry["tilt_deg"] = round(
            fitted.tilt_deg if fitted.tilt_deg is not None else min(abs(fitted.latitude), 40.0), 2
        )
        entry["azimuth_deg"] = round(
            fitted.azimuth_deg
            if fitted.azimuth_deg is not None
            else (180.0 if fitted.latitude >= 0 else 0.0),
            1,
        )
        entry["location_is_estimated"] = True

    registry_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return results


if __name__ == "__main__":
    from reip.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    frame = pd.read_parquet(get_settings().data_canonical / "gefcom_solar_power.parquet")
    for site_id, diag in fit_all_solar_sites(frame).items():
        print(
            f"{site_id:18s} lat {diag['latitude']:8.3f}  lon {diag['longitude']:9.3f}  "
            f"day-length RMSE {diag['daylength_rmse_h']:.3f} h"
        )
