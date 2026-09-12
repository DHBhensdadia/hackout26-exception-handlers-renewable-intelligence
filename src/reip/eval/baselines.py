"""Reference forecasts the model has to beat.

A model reported without baselines has made no claim. These four are the ones that matter,
in ascending order of how hard they are to beat:

* **Persistence** - tomorrow looks like the moment the forecast was issued. Trivial, and
  for solar it is genuinely terrible, but it is the floor everything is measured from.

* **Smart persistence** - hold the *clear-sky index* constant instead of the power. This
  keeps the sun's known trajectory and freezes only the cloud, so it reproduces the whole
  diurnal and seasonal shape for free. It is the standard reference in the solar
  forecasting literature and it is a genuinely strong opponent. Beating plain persistence
  proves nothing; beating this one is the claim worth making.

* **Climatology** - the historical average for this time of year and hour. Carries no
  weather information at all, so any weather-driven model that loses to it is broken.

* **Physics only** - the pvlib chain or the turbine power curve run on the same NWP, with
  no machine learning. This is the load-bearing baseline for *this* design specifically:
  the model receives the physics estimate as an input feature, so the physics-only column
  measures exactly how much the learned correction adds. If the ML cannot beat it, the ML
  is not earning its place.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from reip.schemas import Tech


def persistence(frame: pd.DataFrame) -> np.ndarray:
    """Power at the forecast issue time, held flat across the horizon."""
    return frame["power_at_issue_mw"].to_numpy(dtype="float64")


def smart_persistence(frame: pd.DataFrame, tech: Tech) -> np.ndarray:
    """Hold the normalised state constant and let the deterministic component evolve.

    Solar: freeze the clear-sky index at issue time and ride the clear-sky curve. Wind has
    no equivalent deterministic trajectory, so it degenerates to persistence - which is
    itself the honest answer, and part of why wind is the harder forecasting problem.

    The reference is the CLEAR-SKY curve, explicitly, and not whatever the training target
    happened to normalise by. Those were the same thing under the clear-sky-index target
    and stopped being the same thing when solar moved to capacity factor: the denominator
    became a constant, so dividing by it and multiplying straight back returned
    `power_at_issue` unchanged. Smart persistence silently became plain persistence, and
    the benchmark went on reporting it under the stronger name - beating it meant less
    than the report claimed.
    """
    if tech is Tech.WIND:
        return persistence(frame)

    clearsky_at_issue = frame["clearsky_at_issue_mw"].to_numpy(dtype="float64")
    index_at_issue = np.divide(
        frame["power_at_issue_mw"].to_numpy(dtype="float64"),
        clearsky_at_issue,
        out=np.zeros(len(frame)),
        where=clearsky_at_issue > 1e-6,
    )
    return np.clip(index_at_issue, 0.0, 1.3) * frame["clearsky_mw"].to_numpy(dtype="float64")


def climatology(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Mean observed output for this (site, day-of-year block, hour), fitted on train only.

    Fitted on the training split alone. Fitting it on the full record would let it see the
    holdout it is being scored against, and a baseline with a leak is not a baseline.
    """

    def key(df: pd.DataFrame) -> pd.DataFrame:
        times = pd.DatetimeIndex(df["valid_time_utc"])
        return pd.DataFrame(
            {
                "site_id": df["site_id"].to_numpy(),
                "doy_block": (times.dayofyear - 1) // 15,
                "hour": times.hour,
            }
        )

    train_key = key(train).assign(actual=train["actual_mw"].to_numpy(dtype="float64"))
    lookup = train_key.groupby(["site_id", "doy_block", "hour"])["actual"].mean()
    site_mean = train_key.groupby("site_id")["actual"].mean()

    test_key = key(test)
    index = pd.MultiIndex.from_frame(test_key[["site_id", "doy_block", "hour"]])
    values = lookup.reindex(index).to_numpy(dtype="float64")

    # Unseen (day-block, hour) cells fall back to the site mean rather than to zero.
    fallback = site_mean.reindex(test_key["site_id"]).to_numpy(dtype="float64")
    return np.where(np.isnan(values), np.nan_to_num(fallback), values)


def physics_only(frame: pd.DataFrame) -> np.ndarray:
    """The NWP-driven physical estimate with no learned correction applied."""
    return frame["physics_mw"].to_numpy(dtype="float64")


BASELINE_LABELS: dict[str, str] = {
    "persistence": "Persistence",
    "smart_persistence": "Smart persistence",
    "climatology": "Climatology",
    "physics_only": "Physics only (no ML)",
}
