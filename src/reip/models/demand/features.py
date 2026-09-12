"""Demand features - the train/serve boundary for the demand model.

The exact counterpart of `features/build.py`: one module, imported by both the trainer and
the server, so a feature can never be computed one way in training and another in
production. That rule caught nothing in Phase 1 only because it was enforced from the
start, and demand is where it matters most, for a reason that deserves stating plainly.

**Demand may use its own history. Generation may not.**

Phase 1 banned power lags outright. A generation forecast issued at t0 for t0+48h cannot
see generation at t0+47h, because that has not happened yet, and a model trained with it
would score beautifully and fail completely in production.

Demand is a different information set. Load *at or before the issue time* genuinely is
known when the forecast is made - a control room can read the meter - and it is by some
distance the strongest single predictor of load a day or three ahead. Refusing to use it
would be a self-inflicted handicap, not rigour.

But the asymmetry is dangerous precisely because it looks like an exception to a rule. So
every lag here is measured backwards from `issue_time`, never from `valid_time`, and T10
asserts the distinction holds: shuffling load after the issue time must leave every
prediction bit-identical.

**Load centres, not generation sites.** Demand is driven by the weather where people are,
not where the turbines are. A 42C day in Broken Hill does not switch on air conditioners
in Sydney. Each region therefore takes weather at its population centre.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Population-weighted load centre per NEM region. Demand is a function of the weather
# where the load is; the generation fleet is hundreds of kilometres away in the opposite
# direction, out where the wind and the sun are and the people are not.
LOAD_CENTRES: dict[str, tuple[str, float, float, str]] = {
    "NSW1": ("Sydney", -33.8688, 151.2093, "Australia/Sydney"),
    "QLD1": ("Brisbane", -27.4698, 153.0251, "Australia/Brisbane"),
    "SA1": ("Adelaide", -34.9285, 138.6007, "Australia/Adelaide"),
    "TAS1": ("Hobart", -42.8821, 147.3272, "Australia/Hobart"),
    "VIC1": ("Melbourne", -37.8136, 144.9631, "Australia/Melbourne"),
}

# Comfort baseline for degree-day terms, degrees C. Below it people heat, above it they
# cool, and both raise load - so raw temperature enters demand as a V, which a tree can
# only learn by spending splits on both arms. Splitting it into two one-sided terms hands
# the model the shape directly.
COMFORT_TEMP_C: float = 18.0

# Load lags, in hours before the ISSUE time. 1h is the current state of the system; 24h is
# the same hour yesterday; 168h is the same hour on the same weekday last week, which
# carries the weekday/weekend pattern without the model having to infer it.
LOAD_LAG_HOURS: tuple[int, ...] = (1, 24, 168)

# Rolling windows over the run-up to issue time, capturing level and volatility.
LOAD_ROLL_HOURS: tuple[int, ...] = (24, 168)


def _cyclical(values: pd.Series | np.ndarray, period: float, prefix: str) -> dict[str, np.ndarray]:
    """Encode a periodic quantity as sin/cos.

    Hour 23 and hour 0 are one hour apart but sit at opposite ends of a linear axis, so a
    tree would need many splits to learn they are adjacent.
    """
    radians = 2.0 * np.pi * np.asarray(values, dtype="float64") / period
    return {f"{prefix}_sin": np.sin(radians), f"{prefix}_cos": np.cos(radians)}


def australian_holidays(times: pd.DatetimeIndex) -> np.ndarray:
    """National public holidays, as a 0/1 flag.

    Only the nationally observed dates, deliberately. State-specific days differ across
    five regions and would need a per-region calendar to be correct; getting that half
    right is worse than a clean national flag plus the weekday features, which already
    carry most of the signal.

    Christmas Day 2025 is the single most extreme demand hour in this corpus - SA1 fell to
    -280 MW - so this flag is not decoration.
    """

    flags = np.zeros(len(times), dtype="float64")
    local_dates = pd.DatetimeIndex(times).date

    fixed = {(1, 1), (1, 26), (4, 25), (12, 25), (12, 26)}  # NY, Australia, ANZAC, Xmas, Boxing
    for i, day in enumerate(local_dates):
        if (day.month, day.day) in fixed:
            flags[i] = 1.0

    # Good Friday and Easter Monday move; computed rather than tabulated so the model keeps
    # working in years nobody thought to hardcode.
    for year in sorted({d.year for d in local_dates}):
        easter = _easter(year)
        movable = {easter - pd.Timedelta(days=2), easter + pd.Timedelta(days=1)}
        movable = {d.date() if hasattr(d, "date") else d for d in movable}
        for i, day in enumerate(local_dates):
            if day in movable:
                flags[i] = 1.0
    return flags


def _easter(year: int) -> pd.Timestamp:
    """Easter Sunday, by the anonymous Gregorian computus.

    Computed rather than tabulated so the calendar keeps working in years nobody thought
    to hardcode. Easter matters here because Good Friday and Easter Monday are national
    holidays whose dates move by more than a month between years, and a four-day weekend
    is one of the largest demand anomalies in the calendar.
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * lam) // 433
    month = (h + lam - 7 * m + 90) // 25
    day = (h + lam - 7 * m + 33 * month + 19) % 32
    return pd.Timestamp(year=year, month=month, day=day)


# Horizons sampled rather than every hour from 1 to 72.
#
# Expanding 26,304 hours by all 72 leads gives 1.9M rows per region, 9.5M across the NEM,
# and most of it is redundant: for one valid hour the weather features are identical at
# every lead, and only `horizon_h` and the load lags differ. A grid that is dense near the
# start - where skill changes fastest - and coarser out to 72 h captures the decay curve at
# a fifth of the cost.
DEFAULT_HORIZONS: tuple[int, ...] = (1, 2, 3, 6, 9, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72)

# Weather columns taken at the valid time. These are forecast quantities - what an NWP
# publishes - so using them at a future valid time carries no look-ahead. GHI and cloud
# are here as the physical drivers of behind-the-meter solar; see the note in
# `build_demand_features` on why measured rooftop output is not.
NWP_COLUMNS: tuple[str, ...] = ("temp_2m_c", "cloud_total", "wind_speed_10m", "ghi_wm2")


def build_demand_features(
    market: pd.DataFrame,
    weather: pd.DataFrame,
    region: str,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """One row per (valid_time, horizon) for a region, with the target attached.

    `market` supplies demand and rooftop PV at hourly UTC resolution; `weather` supplies the
    load-centre forecast on the same index.

    **Measured rooftop PV is deliberately not a feature.** It is tempting - operational
    demand is net of rooftop output, so the two move together almost by definition - and
    that is exactly what makes it wrong. `rooftop_pv_mw` in the market corpus is AEMO's
    *actual* estimate for that hour, which nobody has when the forecast is issued two days
    earlier. Feeding it in would produce a spectacular validation score and a model that
    cannot be served.

    What is legitimate is everything rooftop output is made of: the GHI and cloud forecast
    at the valid time, which an NWP genuinely provides, plus rooftop's own level as of the
    issue time. Those carry the midday-trough signal without borrowing the answer.
    """
    if region not in LOAD_CENTRES:
        raise ValueError(f"unknown region {region!r}; known: {sorted(LOAD_CENTRES)}")
    _, _, _, tz = LOAD_CENTRES[region]

    block = (
        market[market["region"] == region]
        .drop_duplicates("valid_time_utc")
        .set_index("valid_time_utc")
        .sort_index()[["demand_mw", "rooftop_pv_mw"]]
    )
    if block.empty:
        raise ValueError(f"no market rows for {region}")

    wx = (
        weather[weather["site_id"] == f"LOAD-{region}"]
        .drop_duplicates("valid_time_utc")
        .set_index("valid_time_utc")
        .sort_index()
    )
    if wx.empty:
        raise ValueError(f"no load-centre weather for {region}")

    index = block.index
    local = index.tz_convert(tz)
    load = block["demand_mw"]
    rooftop = block["rooftop_pv_mw"]

    # Everything that does not depend on the horizon, computed once.
    calendar: dict[str, np.ndarray] = {
        **_cyclical(local.hour, 24.0, "hour"),
        **_cyclical(local.dayofyear, 365.25, "doy"),
        **_cyclical(local.dayofweek, 7.0, "dow"),
        "is_weekend": (local.dayofweek >= 5).astype("float64"),
        "is_holiday": australian_holidays(local),
    }

    nwp: dict[str, np.ndarray] = {}
    for column in NWP_COLUMNS:
        if column in wx.columns:
            nwp[column] = wx[column].reindex(index).to_numpy(dtype="float64")
    if "temp_2m_c" in nwp:
        temp = pd.Series(nwp["temp_2m_c"], index=index)
        nwp["cooling_degrees"] = (temp - COMFORT_TEMP_C).clip(lower=0.0).to_numpy()
        nwp["heating_degrees"] = (COMFORT_TEMP_C - temp).clip(lower=0.0).to_numpy()
        # Air conditioning responds to accumulated heat, not the instantaneous reading: the
        # third day of a heatwave draws more than the first at the same temperature,
        # because buildings and the people in them have not cooled overnight.
        nwp["cooling_degrees_24h"] = (
            pd.Series(nwp["cooling_degrees"], index=index).rolling(24, min_periods=1).mean().to_numpy()
        )

    # History, computed on the series itself. Shifting by `horizon` below is what turns a
    # lag-of-L into "L hours before the issue time" rather than before the valid time.
    history = {f"load_lag_{h}h": load.shift(h) for h in LOAD_LAG_HOURS}
    history["rooftop_lag_24h"] = rooftop.shift(24)
    for window in LOAD_ROLL_HOURS:
        history[f"load_mean_{window}h"] = load.rolling(window, min_periods=max(2, window // 4)).mean()
        history[f"load_std_{window}h"] = load.rolling(window, min_periods=2).std()

    frames: list[pd.DataFrame] = []
    for horizon in horizons:
        columns: dict[str, np.ndarray] = {
            "horizon_h": np.full(len(index), horizon, dtype="float64"),
            "lead_day": np.full(len(index), int(np.ceil(horizon / 24)), dtype="float64"),
            **calendar,
            **nwp,
        }
        for name, series in history.items():
            columns[name] = series.shift(horizon).to_numpy(dtype="float64")

        row = pd.DataFrame(columns, index=index)
        row["__target"] = load.to_numpy(dtype="float64")
        row["__valid_time"] = index
        row["__issue_time"] = index - pd.Timedelta(hours=horizon)
        frames.append(row)

    out = pd.concat(frames)
    out = out[out["__target"].notna()]
    return out.sort_values("__valid_time", kind="mergesort").reset_index(drop=True)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """The model-visible columns: everything not prefixed with a double underscore."""
    return [c for c in frame.columns if not c.startswith("__")]
