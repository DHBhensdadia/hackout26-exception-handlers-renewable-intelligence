"""Solar physics: sun geometry, clear-sky irradiance, plane-of-array transposition, PV output.

Two distinct uses, both essential to the design:

1. **Clear-sky AC power** is the denominator of the regression target. Dividing measured
   power by it strips out the fully deterministic part of generation - diurnal cycle,
   season, latitude - leaving only the stochastic part driven by cloud. That is what
   lets one model serve every site.

2. **Physics AC power** (the same chain run on forecast irradiance rather than clear-sky
   irradiance) is fed to the model as an input feature. The model then learns a
   correction to physics rather than a mapping from scratch, which is what makes it
   degrade gracefully instead of absurdly on a site unlike anything in training.

Everything here is a pure function of (timestamps, weather, site). No state, no I/O.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd
import pvlib

from reip.schemas import SiteMeta

# PVWatts defaults. Deliberately generic: the model corrects the residual, so chasing
# module-level fidelity here would buy accuracy the GBDT already recovers.
GAMMA_PDC: float = -0.004  # power temperature coefficient, 1/degC (c-Si)
INVERTER_EFF: float = 0.96
REF_IRRADIANCE: float = 1000.0  # W/m2, STC


def solar_position(times: pd.DatetimeIndex, site: SiteMeta) -> pd.DataFrame:
    """Apparent solar position. Index matches `times`.

    Returns zenith/apparent_zenith/azimuth/elevation in degrees.
    """
    return pvlib.solarposition.get_solarposition(
        times,
        latitude=site.latitude,
        longitude=site.longitude,
        altitude=site.altitude_m,
    )


def clearsky_irradiance(times: pd.DatetimeIndex, site: SiteMeta) -> pd.DataFrame:
    """Ineichen-Perez clear-sky GHI/DNI/DHI.

    This is the reference the target is normalised against, so it must be reproducible
    from site metadata alone - no measured data, no fitted parameters beyond location.
    """
    loc = pvlib.location.Location(
        latitude=site.latitude,
        longitude=site.longitude,
        altitude=site.altitude_m,
        tz="UTC",
    )
    return loc.get_clearsky(times, model="ineichen")


def decompose_ghi(
    ghi: pd.Series, zenith: pd.Series, times: pd.DatetimeIndex
) -> tuple[pd.Series, pd.Series]:
    """Split GHI into DNI and DHI with the Erbs correlation.

    Needed because some NWP sources publish only global horizontal irradiance. When the
    source does give DNI/DHI natively we prefer those; this is the fallback so that the
    downstream transposition has the same inputs regardless of provider.
    """
    out = pvlib.irradiance.erbs(ghi.clip(lower=0.0), zenith, times)
    return out["dni"].fillna(0.0), out["dhi"].fillna(0.0)


def plane_of_array(
    site: SiteMeta,
    solpos: pd.DataFrame,
    ghi: pd.Series,
    dni: pd.Series,
    dhi: pd.Series,
    times: pd.DatetimeIndex,
) -> pd.Series:
    """Transpose horizontal irradiance onto the tilted module plane (Hay-Davies)."""
    tilt = site.tilt_deg if site.tilt_deg is not None else min(abs(site.latitude), 40.0)
    azim = (
        site.azimuth_deg if site.azimuth_deg is not None else (180.0 if site.latitude >= 0 else 0.0)
    )

    total = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azim,
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        dni_extra=pvlib.irradiance.get_extra_radiation(times),
        model="haydavies",
    )
    return total["poa_global"].fillna(0.0).clip(lower=0.0)


def cell_temperature(poa: pd.Series, temp_air: pd.Series, wind_speed: pd.Series) -> pd.Series:
    """Module cell temperature (Faiman). Drives the efficiency derate in hot conditions.

    This matters in Gujarat specifically: at 45 C ambient a panel runs well above 60 C
    and loses several percent of output that irradiance alone would not predict.
    """
    return pvlib.temperature.faiman(
        poa_global=poa.clip(lower=0.0),
        temp_air=temp_air,
        wind_speed=wind_speed.clip(lower=0.0),
    )


def ac_power_mw(poa: pd.Series, cell_temp: pd.Series, site: SiteMeta) -> pd.Series:
    """PVWatts DC -> clipped AC, in MW.

    DC capacity is `capacity_mw * dc_ac_ratio`; output is clipped at the AC rating, which
    is what produces the flat-topped midday profile of a real oversized array.
    """
    pdc0 = site.capacity_mw * site.dc_ac_ratio
    pdc = pvlib.pvsystem.pvwatts_dc(
        effective_irradiance=poa.clip(lower=0.0),
        temp_cell=cell_temp,
        pdc0=pdc0,
        gamma_pdc=GAMMA_PDC,
        temp_ref=25.0,
    )
    pac = (pdc * INVERTER_EFF).clip(lower=0.0, upper=site.capacity_mw)
    return pac.fillna(0.0)


# Sub-hourly resolution used to average the clear-sky reference over each hour.
# Six samples per hour is enough: within one hour the clear-sky curve is smooth, and the
# residual quadrature error is far below the noise in any weather forecast.
CLEARSKY_SUBSTEPS: Final[int] = 6


def clearsky_ac_mw(
    times: pd.DatetimeIndex, site: SiteMeta, temp_air: pd.Series | None = None
) -> pd.Series:
    """Clear-sky AC power averaged over the hour *ending* at each timestamp.

    The averaging is not a refinement, it is a units fix. Both weather sources publish
    hourly-mean irradiance for the preceding hour - Open-Meteo by definition, GEFCom
    because de-accumulating a J/m2 field over an hour yields exactly that mean. Evaluating
    the clear-sky reference at the single instant on the hour boundary compares a mean
    against a sample.

    Mid-morning the two barely differ. At sunrise and sunset they differ enormously: the
    instant on the boundary can be after the sun has set while the hour before it was
    still producing. That inflates the clear-sky index, and because the same reference is
    the denominator of the training target, it injects noise into exactly the hours where
    forecasting is hardest.

    `temp_air` is optional. When NWP temperature is available the reference reflects the
    real thermal derate; otherwise it falls back to 25 C so the reference stays computable
    from site metadata alone - which is what lets a site with no history be normalised.
    """
    step = pd.Timedelta(hours=1) / CLEARSKY_SUBSTEPS
    # Sample the midpoint of each sub-interval within (t-1h, t]: the midpoint rule
    # integrates a smooth curve more accurately than sampling the endpoints.
    offsets = [-pd.Timedelta(hours=1) + step * (i + 0.5) for i in range(CLEARSKY_SUBSTEPS)]

    accumulated = np.zeros(len(times), dtype="float64")
    for offset in offsets:
        shifted = times + offset
        solpos = solar_position(shifted, site)
        cs = clearsky_irradiance(shifted, site)
        poa = plane_of_array(site, solpos, cs["ghi"], cs["dni"], cs["dhi"], shifted)

        ta = (
            pd.Series(temp_air.to_numpy(dtype="float64"), index=shifted)
            if temp_air is not None
            else pd.Series(25.0, index=shifted)
        )
        wind = pd.Series(1.0, index=shifted)  # calm reference; wind cooling is second order
        tcell = cell_temperature(poa, ta, wind)
        accumulated += ac_power_mw(poa, tcell, site).to_numpy(dtype="float64")

    return pd.Series(accumulated / CLEARSKY_SUBSTEPS, index=times)


def solar_physics_frame(
    times: pd.DatetimeIndex,
    site: SiteMeta,
    *,
    ghi: pd.Series,
    temp_air: pd.Series,
    wind_speed: pd.Series,
    dni: pd.Series | None = None,
    dhi: pd.Series | None = None,
) -> pd.DataFrame:
    """Every solar physics quantity the feature builder needs, in one pass.

    Computing these together avoids recomputing solar position four times, which is the
    dominant cost when this runs over years of hourly data.
    """
    solpos = solar_position(times, site)
    cs = clearsky_irradiance(times, site)

    ghi = ghi.clip(lower=0.0)
    if dni is None or dni.isna().all() or dhi is None or dhi.isna().all():
        dni_use, dhi_use = decompose_ghi(ghi, solpos["apparent_zenith"], times)
    else:
        dni_use, dhi_use = dni.fillna(0.0).clip(lower=0.0), dhi.fillna(0.0).clip(lower=0.0)

    poa_nwp = plane_of_array(site, solpos, ghi, dni_use, dhi_use, times)
    poa_cs = plane_of_array(site, solpos, cs["ghi"], cs["dni"], cs["dhi"], times)

    tcell_nwp = cell_temperature(poa_nwp, temp_air, wind_speed)

    physics_ac = ac_power_mw(poa_nwp, tcell_nwp, site)
    # Reuse the hour-averaged reference rather than recomputing it instantaneously here:
    # this column is the target's denominator, and the two must be the same quantity.
    clearsky_ac = clearsky_ac_mw(times, site, temp_air=temp_air)

    # NWP clear-sky index: how cloudy the forecast thinks it will be. Bounded rather than
    # left unbounded because clear-sky GHI approaches zero at sunrise/sunset and the raw
    # ratio explodes there.
    with np.errstate(divide="ignore", invalid="ignore"):
        kt = np.where(cs["ghi"] > 1.0, ghi / cs["ghi"], 0.0)

    return pd.DataFrame(
        {
            "solar_zenith": solpos["apparent_zenith"].to_numpy(),
            "solar_azimuth": solpos["azimuth"].to_numpy(),
            "solar_elevation": solpos["apparent_elevation"].to_numpy(),
            "clearsky_ghi": cs["ghi"].to_numpy(),
            "clearsky_dni": cs["dni"].to_numpy(),
            "poa_nwp": poa_nwp.to_numpy(),
            "poa_clearsky": poa_cs.to_numpy(),
            "cell_temp_c": tcell_nwp.to_numpy(),
            "kt_nwp": np.clip(kt, 0.0, 1.5),
            "physics_ac_mw": physics_ac.to_numpy(),
            "clearsky_ac_mw": clearsky_ac.to_numpy(),
        },
        index=times,
    )
