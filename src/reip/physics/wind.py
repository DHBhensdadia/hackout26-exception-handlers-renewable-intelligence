"""Wind physics: shear extrapolation, air density correction, reference power curve.

The wind analogue of `physics/solar.py`. The chain is:

    NWP wind at 10 m and 100 m
      -> shear exponent (measured, not assumed)
      -> hub-height wind speed
      -> air-density correction
      -> reference power curve
      -> capacity factor prior

The density correction matters more than it looks. Turbine power goes as rho * v^3, so
the same 8 m/s produces materially different output on a cold winter night than on a
45 C Kutch afternoon. Folding density into an equivalent wind speed - rather than
scaling power - keeps the correction inside the power curve where it belongs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from reip.schemas import SiteMeta

R_SPECIFIC_DRY_AIR: float = 287.05  # J/(kg K)
RHO_STANDARD: float = 1.225  # kg/m3 at 15 C, sea level
KELVIN: float = 273.15

# Fallback shear exponent when the two NWP heights give a nonsensical ratio.
# 1/7 is the classic open-terrain value.
DEFAULT_SHEAR: float = 1.0 / 7.0
SHEAR_BOUNDS: tuple[float, float] = (-0.10, 0.60)


def air_density(pressure_hpa: pd.Series, temp_c: pd.Series) -> pd.Series:
    """Dry-air density from the ideal gas law, kg/m3."""
    pressure_pa = pressure_hpa.astype("float64") * 100.0
    temp_k = temp_c.astype("float64") + KELVIN
    rho = pressure_pa / (R_SPECIFIC_DRY_AIR * temp_k)
    # Clip to physically reachable values; anything outside means bad input, and an
    # unclipped rho would propagate silently into every wind feature.
    return rho.clip(lower=0.9, upper=1.4).fillna(RHO_STANDARD)


def shear_exponent(ws_10m: pd.Series, ws_100m: pd.Series) -> pd.Series:
    """Power-law shear exponent measured from the two forecast heights.

    alpha = ln(v100 / v10) / ln(100 / 10)

    Measuring this rather than assuming 1/7 captures atmospheric stability: a stable
    nocturnal boundary layer shears far more strongly than a well-mixed afternoon, and
    that difference is worth several percent of hub-height wind speed.
    """
    lo = ws_10m.astype("float64").clip(lower=0.25)
    hi = ws_100m.astype("float64").clip(lower=0.25)
    alpha = np.log(hi / lo) / np.log(10.0)
    return pd.Series(alpha, index=ws_10m.index).clip(*SHEAR_BOUNDS).fillna(DEFAULT_SHEAR)


def wind_at_hub(ws_100m: pd.Series, alpha: pd.Series, hub_height_m: float) -> pd.Series:
    """Extrapolate the 100 m forecast wind to hub height by the power law."""
    ratio = (hub_height_m / 100.0) ** alpha
    return (ws_100m.astype("float64") * ratio).clip(lower=0.0)


def density_corrected_speed(ws: pd.Series, rho: pd.Series) -> pd.Series:
    """Equivalent standard-density wind speed: v_eq = v * (rho / rho_0)^(1/3).

    The cube root is what makes this the right place for the correction - it maps a
    density change onto the speed axis such that the resulting power is exactly the
    density-adjusted power.
    """
    return ws * (rho / RHO_STANDARD) ** (1.0 / 3.0)


def reference_power_curve(ws: pd.Series, site: SiteMeta) -> pd.Series:
    """Idealised IEC-style capacity factor curve.

        0                                    below cut-in
        (v^3 - vin^3) / (vr^3 - vin^3)       cut-in -> rated  (cubic, the physical law)
        1                                    rated -> cut-out
        0                                    above cut-out    (storm shutdown)

    This is a *prior*, not a prediction. Real turbines deviate from it through control
    strategy, wake losses, blade soiling and availability - and learning that deviation
    is precisely the job we hand to the GBDT.
    """
    v = ws.astype("float64").to_numpy()
    vin, vr, vout = site.cut_in_ws_ms, site.rated_ws_ms, site.cut_out_ws_ms

    ramp = (np.clip(v, vin, vr) ** 3 - vin**3) / (vr**3 - vin**3)
    cf = np.where(v < vin, 0.0, np.where(v <= vr, ramp, 1.0))
    cf = np.where(v > vout, 0.0, cf)
    return pd.Series(np.clip(cf, 0.0, 1.0), index=ws.index)


def wind_physics_frame(
    times: pd.DatetimeIndex,
    site: SiteMeta,
    *,
    ws_10m: pd.Series,
    ws_100m: pd.Series,
    temp_c: pd.Series,
    pressure_hpa: pd.Series,
) -> pd.DataFrame:
    """Every wind physics quantity the feature builder needs, in one pass."""
    hub = site.hub_height_m if site.hub_height_m is not None else 100.0

    rho = air_density(pressure_hpa, temp_c)
    alpha = shear_exponent(ws_10m, ws_100m)
    ws_hub = wind_at_hub(ws_100m, alpha, hub)
    ws_eq = density_corrected_speed(ws_hub, rho)
    cf = reference_power_curve(ws_eq, site)

    return pd.DataFrame(
        {
            "air_density": rho.to_numpy(),
            "shear_exponent": alpha.to_numpy(),
            "ws_hub": ws_hub.to_numpy(),
            "ws_corrected": ws_eq.to_numpy(),
            "ws_corrected_sq": (ws_eq**2).to_numpy(),
            "ws_corrected_cube": (ws_eq**3).to_numpy(),
            "cf_powercurve": cf.to_numpy(),
        },
        index=times,
    )


def direction_components(dir_deg: pd.Series, prefix: str) -> pd.DataFrame:
    """Encode a compass direction as sin/cos.

    Raw degrees are unusable as a tree feature: 359 and 1 are one degree apart but sit at
    opposite ends of the split space, so a tree would have to spend many splits to learn
    that they are the same wind.
    """
    rad = np.deg2rad(dir_deg.astype("float64"))
    return pd.DataFrame(
        {f"{prefix}_sin": np.sin(rad), f"{prefix}_cos": np.cos(rad)},
        index=dir_deg.index,
    )
