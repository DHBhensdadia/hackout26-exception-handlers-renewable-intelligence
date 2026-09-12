"""Feature construction. Shared by training and serving - this is the skew boundary.

Nothing else in the codebase may build a feature vector. The trainer calls
`build_features`; the API calls `build_features`; test T1 pushes one raw row through both
call sites and asserts the outputs are byte-identical. That is the entire defence against
train/serve skew, which is the failure mode that silently destroys ML systems: the model
scores well offline, then quietly mispredicts in production because some transform
differed by a unit, an ordering, or a fill value.

Three rules hold throughout:

**Ordering is part of the contract.** Gradient-boosted trees index features positionally.
`FEATURE_ORDER` is written into the model artifact at fit time and asserted at predict
time, so a reordered column raises instead of silently scoring the wrong feature.

**Leading NWP is legal; leading power is not.** A numerical weather prediction covers the
whole horizon at issue time, so looking at the forecast three hours *ahead* of the target
hour uses only information genuinely in hand. Looking at measured power after issue time
does not, and no feature here touches the target series.

**Absence stays absent.** Missing inputs propagate as NaN. LightGBM handles NaN natively
by learning a default split direction, which is strictly better than imputing a fake
value the model cannot distinguish from a real one.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.physics.clearsky import PvlibClearSky, clearsky_index
from reip.physics.solar import solar_physics_frame
from reip.physics.wind import direction_components, wind_physics_frame
from reip.schemas import (
    CLEARSKY_INDEX_MAX,
    SOLAR_REQUIRED_WEATHER,
    WIND_REQUIRED_WEATHER,
    SiteMeta,
    Tech,
    require_columns,
)

log = logging.getLogger(__name__)

# Hours ahead and behind used for rolling/shifted NWP features. Symmetric on purpose:
# what matters for a ramp is the gradient across the target hour, not just its history.
LAG_LEADS: Final[tuple[int, ...]] = (-3, -2, -1, 1, 2, 3)
ROLLING_WINDOW: Final[int] = 7  # +/- 3 hours, centred

# Below this clear-sky AC output the site is in night or deep twilight. The clear-sky
# index there is a ratio of two near-zero numbers, i.e. pure noise, so those rows are
# excluded from training and forced to zero at serve time.
NIGHT_CLEARSKY_FLOOR_MW: Final[float] = 1e-3

TARGET_COLUMN: Final[str] = "target"


# --------------------------------------------------------------------------------------
# Shared temporal features
# --------------------------------------------------------------------------------------


def _temporal_features(times: pd.DatetimeIndex, horizon_h: pd.Series) -> pd.DataFrame:
    """Calendar and lead-time features.

    Cyclical quantities are encoded as sin/cos pairs rather than raw integers: hour 23 and
    hour 0 are adjacent in time but maximally distant as integers, and a tree would have
    to burn splits rediscovering that they are neighbours.
    """
    hour = times.hour.to_numpy(dtype="float64")
    doy = times.dayofyear.to_numpy(dtype="float64")

    return pd.DataFrame(
        {
            "horizon_h": horizon_h.to_numpy(dtype="float64"),
            "lead_day": np.ceil(horizon_h.to_numpy(dtype="float64") / 24.0),
            "hour_sin": np.sin(2 * np.pi * hour / 24.0),
            "hour_cos": np.cos(2 * np.pi * hour / 24.0),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        },
        index=times,
    )


def _shifted_and_rolled(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Neighbouring-hour NWP values and local variability.

    The rolling **standard deviation** is the important one here. It measures how fast the
    forecast is changing around the target hour, which is the best available proxy for how
    uncertain that hour is - a steady overcast afternoon is predictable, a broken-cloud
    ramp is not. The quantile models lean on it to widen the p10-p90 band exactly where
    the atmosphere is unsettled, rather than applying a constant-width interval.
    """
    out: dict[str, np.ndarray] = {}
    for col in columns:
        if col not in frame.columns:
            continue
        series = frame[col].astype("float64")
        for shift in LAG_LEADS:
            suffix = f"lead{shift}" if shift > 0 else f"lag{abs(shift)}"
            out[f"{col}_{suffix}"] = series.shift(-shift).to_numpy()
        rolling = series.rolling(ROLLING_WINDOW, center=True, min_periods=1)
        out[f"{col}_roll_mean"] = rolling.mean().to_numpy()
        out[f"{col}_roll_std"] = rolling.std().fillna(0.0).to_numpy()
        out[f"{col}_delta"] = series.diff().to_numpy()
    return pd.DataFrame(out, index=frame.index)


# --------------------------------------------------------------------------------------
# Per-technology feature builders
# --------------------------------------------------------------------------------------


def _solar_features(weather: pd.DataFrame, site: SiteMeta) -> pd.DataFrame:
    require_columns(weather, SOLAR_REQUIRED_WEATHER, context=f"solar features for {site.site_id}")
    times = pd.DatetimeIndex(weather["valid_time_utc"])

    physics = solar_physics_frame(
        times,
        site,
        ghi=pd.Series(weather["ghi_wm2"].to_numpy(dtype="float64"), index=times),
        temp_air=pd.Series(weather["temp_2m_c"].to_numpy(dtype="float64"), index=times),
        wind_speed=pd.Series(weather["wind_speed_10m"].to_numpy(dtype="float64"), index=times),
        dni=pd.Series(weather["dni_wm2"].to_numpy(dtype="float64"), index=times),
        dhi=pd.Series(weather["dhi_wm2"].to_numpy(dtype="float64"), index=times),
    )

    raw = pd.DataFrame(
        {
            "ghi_wm2": weather["ghi_wm2"].to_numpy(dtype="float64"),
            "cloud_total": weather["cloud_total"].to_numpy(dtype="float64"),
            "cloud_low": weather["cloud_low"].to_numpy(dtype="float64"),
            "cloud_mid": weather["cloud_mid"].to_numpy(dtype="float64"),
            "cloud_high": weather["cloud_high"].to_numpy(dtype="float64"),
            "temp_2m_c": weather["temp_2m_c"].to_numpy(dtype="float64"),
            "rh_pct": weather["rh_pct"].to_numpy(dtype="float64"),
            "precip_mm": weather["precip_mm"].to_numpy(dtype="float64"),
            "wind_speed_10m": weather["wind_speed_10m"].to_numpy(dtype="float64"),
        },
        index=times,
    )

    # Site geometry. Constant within a site, but the model is trained across sites, so
    # these are what let it condition its correction on the kind of plant it is looking at.
    meta = pd.DataFrame(
        {
            # Explicit None checks throughout: a flat array has tilt 0.0 and a
            # southern-hemisphere array has azimuth 0.0, both of which are falsy, so the
            # `x or default` idiom silently substitutes a default for a real value.
            "site_latitude": site.latitude,
            "site_tilt": site.tilt_deg if site.tilt_deg is not None else 0.0,
            "site_azimuth_sin": np.sin(np.deg2rad(site.azimuth_deg or 0.0)),
            "site_azimuth_cos": np.cos(np.deg2rad(site.azimuth_deg or 0.0)),
            "site_capacity_mw": site.capacity_mw,
        },
        index=times,
    )

    # Physics output normalised by capacity. The raw MW figure scales with plant size, so
    # feeding it directly would make the model's correction size-dependent and destroy
    # transfer between a 1 MW zone and a 730 MW park.
    normalised = pd.DataFrame(
        {
            "physics_cf": (physics["physics_ac_mw"] / site.capacity_mw).to_numpy(),
            "clearsky_cf": (physics["clearsky_ac_mw"] / site.capacity_mw).to_numpy(),
            "physics_over_clearsky": np.divide(
                physics["physics_ac_mw"].to_numpy(),
                physics["clearsky_ac_mw"].to_numpy(),
                out=np.zeros(len(physics)),
                where=physics["clearsky_ac_mw"].to_numpy() > NIGHT_CLEARSKY_FLOOR_MW,
            ),
        },
        index=times,
    )

    variability = _shifted_and_rolled(raw, ("ghi_wm2", "cloud_total"))

    return pd.concat(
        [
            _temporal_features(times, weather["horizon_h"]),
            raw,
            physics.drop(columns=["physics_ac_mw", "clearsky_ac_mw"]),
            normalised,
            variability,
            meta,
        ],
        axis=1,
    )


def _wind_features(weather: pd.DataFrame, site: SiteMeta) -> pd.DataFrame:
    require_columns(weather, WIND_REQUIRED_WEATHER, context=f"wind features for {site.site_id}")
    times = pd.DatetimeIndex(weather["valid_time_utc"])

    def col(name: str, default: float) -> pd.Series:
        if name not in weather.columns or weather[name].isna().all():
            return pd.Series(default, index=times, dtype="float64")
        return pd.Series(weather[name].to_numpy(dtype="float64"), index=times).fillna(default)

    # The GEFCom wind track carries no temperature or pressure, so density falls back to
    # standard. That makes the density term inert during training and active at serve
    # time, where it is a small, physically-correct refinement of hub-height wind speed
    # rather than a learned effect. The trainer drops any feature that is constant.
    physics = wind_physics_frame(
        times,
        site,
        ws_10m=pd.Series(weather["wind_speed_10m"].to_numpy(dtype="float64"), index=times),
        ws_100m=pd.Series(weather["wind_speed_100m"].to_numpy(dtype="float64"), index=times),
        temp_c=col("temp_2m_c", 15.0),
        pressure_hpa=col("pressure_hpa", 1013.25),
    )

    raw = pd.DataFrame(
        {
            "wind_speed_10m": weather["wind_speed_10m"].to_numpy(dtype="float64"),
            "wind_speed_100m": weather["wind_speed_100m"].to_numpy(dtype="float64"),
            "temp_2m_c": col("temp_2m_c", np.nan).to_numpy(),
            "pressure_hpa": col("pressure_hpa", np.nan).to_numpy(),
        },
        index=times,
    )

    directions = pd.concat(
        [
            direction_components(
                pd.Series(weather["wind_dir_10m_deg"].to_numpy(dtype="float64"), index=times),
                "wdir10",
            ),
            direction_components(
                pd.Series(weather["wind_dir_100m_deg"].to_numpy(dtype="float64"), index=times),
                "wdir100",
            ),
        ],
        axis=1,
    )

    hub = site.hub_height_m if site.hub_height_m is not None else 100.0
    rotor = site.rotor_diameter_m if site.rotor_diameter_m is not None else 90.0
    meta = pd.DataFrame(
        {
            "site_hub_height": hub,
            "site_rotor_diameter": rotor,
            "site_rated_ws": site.rated_ws_ms,
            "site_capacity_mw": site.capacity_mw,
            # Swept area sets how much wind a turbine can capture, and specific power
            # (W per square metre of rotor) separates a machine built for a windy site
            # from one built for a calm one. Two farms with identical nameplate behave
            # very differently if their specific power differs, so this is the feature
            # that lets one pooled model span both.
            "site_swept_area_m2": np.pi * (rotor / 2.0) ** 2,
            "site_specific_power": site.capacity_mw * 1e6 / (np.pi * (rotor / 2.0) ** 2),
        },
        index=times,
    )

    # Wind-specific extras. Wind is the weaker of the two models, and its errors are
    # concentrated in ramps - periods when speed is changing fast - so these describe the
    # shape of the ramp the plant is about to experience rather than just its level.
    corrected = physics["ws_corrected"]
    extras = pd.DataFrame(
        {
            # Where the plant sits on its own power curve. Near cut-in and near rated the
            # curve is flat and errors are small; through the cubic ramp a 1 m/s error
            # becomes a large power error, and the model needs to know which regime it is
            # in to widen or narrow its interval accordingly.
            "ws_over_rated": corrected / site.rated_ws_ms,
            "in_cubic_ramp": (
                (corrected > site.cut_in_ws_ms) & (corrected < site.rated_ws_ms)
            ).astype("float64"),
            "near_cutout": (corrected > 0.85 * site.cut_out_ws_ms).astype("float64"),
            # Turbulence intensity proxy: variability relative to the mean. A gusty 8 m/s
            # yields differently from a steady 8 m/s, and the ratio captures that where a
            # bare standard deviation would conflate it with high wind speed.
            "turbulence_intensity": (
                corrected.rolling(ROLLING_WINDOW, center=True, min_periods=2).std()
                / corrected.rolling(ROLLING_WINDOW, center=True, min_periods=1).mean().clip(lower=0.5)
            ).fillna(0.0),
            # Ramp magnitude over a longer window than the +/-3 h lags, which is the
            # timescale weather fronts actually move on.
            "ws_range_6h": (
                corrected.rolling(13, center=True, min_periods=2).max()
                - corrected.rolling(13, center=True, min_periods=2).min()
            ).fillna(0.0),
            "ws_lead6": corrected.shift(-6),
            "ws_lag6": corrected.shift(6),
            # Directional persistence: a veering wind usually means a frontal passage and
            # a less predictable few hours than a steady direction.
            "wdir_change_3h": (
                np.abs(
                    (
                        pd.Series(weather["wind_dir_100m_deg"].to_numpy(dtype="float64"), index=times)
                        .diff(3)
                        + 180.0
                    )
                    % 360.0
                    - 180.0
                )
            ).fillna(0.0),
        },
        index=times,
    )

    variability = _shifted_and_rolled(
        pd.concat([raw[["wind_speed_100m"]], physics[["ws_corrected"]]], axis=1),
        ("wind_speed_100m", "ws_corrected"),
    )

    return pd.concat(
        [
            _temporal_features(times, weather["horizon_h"]),
            raw,
            physics,
            directions,
            variability,
            extras,
            meta,
        ],
        axis=1,
    )


# --------------------------------------------------------------------------------------
# Public entry point - the one function both training and serving call
# --------------------------------------------------------------------------------------


def build_features(weather: pd.DataFrame, site: SiteMeta) -> pd.DataFrame:
    """Build the model input matrix for one site from a canonical weather frame.

    Rows are sorted by valid time before any shift or rolling operation: those are
    position-based, so an unsorted frame would compute a lag against the wrong hour and
    produce a subtly, unfalsifiably wrong feature.
    """
    if weather.empty:
        raise ValueError(f"no weather rows for {site.site_id}")

    ordered = weather.sort_values("valid_time_utc").reset_index(drop=True)
    builder = _solar_features if site.tech is Tech.SOLAR else _wind_features
    features = builder(ordered, site)

    features.index = pd.DatetimeIndex(ordered["valid_time_utc"])
    features.index.name = "valid_time_utc"
    return features.astype("float64").sort_index(axis=1)


def build_target(
    power: pd.DataFrame, site: SiteMeta, times: pd.DatetimeIndex
) -> tuple[pd.Series, pd.Series]:
    """Build the dimensionless regression target, aligned to `times`.

    Solar is normalised by clear-sky AC power, wind by installed capacity. Both are
    dimensionless, which is what allows one model to span a 1 MW anonymised zone and a
    730 MW Gujarat park, and to forecast a site whose history does not exist.

    Returns `(target, denominator)`. The denominator is handed back because prediction has
    to multiply by exactly the same quantity to recover MW.
    """
    aligned = (
        power.set_index("valid_time_utc").sort_index().reindex(times)["power_mw"].astype("float64")
    )

    if site.tech is Tech.WIND or get_settings().solar_target == "capacity_factor":
        denominator = pd.Series(site.capacity_mw, index=times)
        return (aligned / site.capacity_mw).clip(0.0, 1.0), denominator

    denominator = PvlibClearSky()(times, site)
    target = clearsky_index(
        aligned, denominator, floor_mw=NIGHT_CLEARSKY_FLOOR_MW, cap=CLEARSKY_INDEX_MAX
    )
    return target, denominator
