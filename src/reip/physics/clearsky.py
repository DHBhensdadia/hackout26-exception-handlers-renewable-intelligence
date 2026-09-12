"""The clear-sky reference: the denominator of the solar target.

One interface, two implementations, and a deliberate rule about which is used where.

`PvlibClearSky` is the production path and is used on **both** sides - training and
serving. That is the whole point: if training normalised by an empirical envelope and
serving denormalised by a pvlib curve, the two would differ by an unknown scale factor
and every served forecast would carry that bias. One implementation, no skew.

`EmpiricalClearSky` exists for two narrower jobs:
  * a fallback when a site's coordinates cannot be recovered at all, and
  * the independent cross-check that validates the recovered coordinates (test T4).

It derives the envelope from the measured power itself - a high quantile of output per
(day-of-year, hour) cell - so it needs no location, but it also cannot extrapolate to a
site with no history, which is exactly why it cannot be the production path.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

from reip.physics.solar import clearsky_ac_mw
from reip.schemas import SiteMeta

# Quantile used for the empirical envelope. Not 1.0: the maximum of a noisy series picks
# up sensor spikes and cloud-enhancement outliers, both of which would inflate the
# denominator and depress every clear-sky index computed from it.
ENVELOPE_QUANTILE: float = 0.95
DOY_BIN_DAYS: int = 5
MIN_SAMPLES_PER_CELL: int = 3


class ClearSkyReference(Protocol):
    """Maps timestamps to the AC power the site would produce under a cloudless sky."""

    def __call__(self, times: pd.DatetimeIndex, site: SiteMeta) -> pd.Series: ...


class PvlibClearSky:
    """Physical clear-sky reference (Ineichen-Perez -> POA -> PVWatts AC).

    Computable from site metadata alone, which is what allows a never-seen site to be
    normalised and therefore forecast.
    """

    name = "pvlib"

    def __call__(
        self,
        times: pd.DatetimeIndex,
        site: SiteMeta,
        temp_air: pd.Series | None = None,
    ) -> pd.Series:
        return clearsky_ac_mw(times, site, temp_air=temp_air)


class EmpiricalClearSky:
    """Data-driven clear-sky envelope: a high quantile of observed power per (doy, hour).

    Fitted from a site's own history. Used as a fallback and as the cross-check on
    fitted coordinates.
    """

    name = "empirical"

    def __init__(self, envelope: pd.DataFrame, capacity_mw: float) -> None:
        self._envelope = envelope  # index (doy_bin, hour) -> power_mw
        self._capacity_mw = capacity_mw

    @classmethod
    def fit(cls, power: pd.Series, capacity_mw: float) -> EmpiricalClearSky:
        """Fit from a UTC-indexed series of measured power in MW."""
        if not isinstance(power.index, pd.DatetimeIndex):
            raise TypeError("power must be indexed by a DatetimeIndex")

        df = pd.DataFrame({"power_mw": power.astype("float64")})
        df["doy_bin"] = (df.index.dayofyear - 1) // DOY_BIN_DAYS
        df["hour"] = df.index.hour

        grouped = df.groupby(["doy_bin", "hour"])["power_mw"]
        envelope = grouped.quantile(ENVELOPE_QUANTILE).to_frame("power_mw")
        envelope["n"] = grouped.size()
        # Sparse cells produce an unreliable quantile; blank them and let the smoothing
        # pass below interpolate across neighbours instead.
        envelope.loc[envelope["n"] < MIN_SAMPLES_PER_CELL, "power_mw"] = np.nan

        wide = envelope["power_mw"].unstack("hour")
        # Smooth around the calendar: December and January are adjacent seasons, so a
        # plain rolling mean would leave a discontinuity at the year boundary.
        wide = pd.concat([wide, wide, wide]).rolling(3, min_periods=1, center=True).mean()
        wide = wide.iloc[len(envelope.index.levels[0]) : 2 * len(envelope.index.levels[0])]
        wide = wide.interpolate(axis=1, limit_direction="both").fillna(0.0)

        return cls(wide.stack().to_frame("power_mw"), capacity_mw)

    def __call__(
        self,
        times: pd.DatetimeIndex,
        site: SiteMeta,
        temp_air: pd.Series | None = None,
    ) -> pd.Series:
        doy_bin = (times.dayofyear - 1) // DOY_BIN_DAYS
        keys = pd.MultiIndex.from_arrays([doy_bin, times.hour], names=["doy_bin", "hour"])
        vals = self._envelope["power_mw"].reindex(keys).to_numpy()
        return pd.Series(np.nan_to_num(vals, nan=0.0), index=times)


def clearsky_index(
    power_mw: pd.Series,
    clearsky_mw: pd.Series,
    *,
    floor_mw: float,
    cap: float,
) -> pd.Series:
    """The solar regression target: measured power as a fraction of clear-sky power.

    Rows where the clear-sky reference is below `floor_mw` are night or deep twilight.
    Their ratio is meaningless (a tiny denominator makes noise look like signal), so they
    are returned as NaN and dropped from training; at serve time they are forced to zero.
    """
    denom = clearsky_mw.astype("float64")
    ratio = power_mw.astype("float64") / denom.where(denom >= floor_mw)
    return ratio.clip(lower=0.0, upper=cap)
