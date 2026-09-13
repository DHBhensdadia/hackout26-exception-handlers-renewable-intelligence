"""T10 (blocking) - the demand model may see the past and must not see the future.

The generation model bans power lags outright, and that rule is easy to keep because it
has no exceptions. Demand does have one: load at or before the issue time genuinely is
known when a forecast is made, and it is the strongest predictor available. Using it is
correct.

Exceptions are where leaks live. A lag shifted by the wrong amount, or measured from the
valid time instead of the issue time, produces a model that scores beautifully in
validation and cannot be served - and nothing else in the suite would notice, because the
numbers only get *better*.

Two tests, structural and behavioural. The behavioural one is the real guard: corrupt every
observation after the issue time and demand that not one feature value moves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reip.models.demand.features import (
    LOAD_LAG_HOURS,
    build_demand_features,
    feature_columns,
)

REGION = "SA1"


@pytest.fixture(scope="module")
def load_centre_weather():
    from reip.models.demand.weather import load

    try:
        return load()
    except FileNotFoundError:
        pytest.skip("load-centre weather absent; run `python -m reip.models.demand.weather`")


@pytest.fixture(scope="module")
def market_slice(market):
    """A contiguous slice long enough for the 168-hour history to be populated."""
    block = market[market["region"] == REGION].sort_values("valid_time_utc")
    if len(block) < 1000:
        pytest.skip("not enough market history")
    return block.head(1500).reset_index(drop=True)


def test_features_ignore_everything_after_the_issue_time(market_slice, load_centre_weather):
    """The blocking check.

    Rebuild the features against a corpus whose demand after a cutoff has been replaced
    with nonsense. Every row issued at or before that cutoff must come out bit-identical.
    If any lag reaches past the issue time, the corruption propagates and this fails.
    """
    horizons = (1, 24, 48, 72)
    clean = build_demand_features(market_slice, load_centre_weather, REGION, horizons=horizons)

    cutoff = market_slice["valid_time_utc"].iloc[len(market_slice) // 2]
    corrupted = market_slice.copy()
    future = corrupted["valid_time_utc"] > cutoff
    assert future.any(), "cutoff left nothing to corrupt"
    rng = np.random.default_rng(0)
    corrupted.loc[future, "demand_mw"] = rng.uniform(-5000, 50000, size=int(future.sum()))
    corrupted.loc[future, "rooftop_pv_mw"] = rng.uniform(0, 9000, size=int(future.sum()))

    dirty = build_demand_features(corrupted, load_centre_weather, REGION, horizons=horizons)

    # Compare only rows whose issue time precedes the corruption. `horizon_h` is both a
    # feature and part of the row key, so it is excluded from the compared columns rather
    # than being counted twice.
    key = ["__valid_time", "horizon_h"]
    columns = [c for c in feature_columns(clean) if c not in key]
    a = clean[clean["__issue_time"] <= cutoff].set_index(key)[columns].sort_index()
    b = dirty[dirty["__issue_time"] <= cutoff].set_index(key)[columns].sort_index()

    common = a.index.intersection(b.index)
    assert len(common) > 100, "too few comparable rows to be a meaningful test"

    a, b = a.loc[common], b.loc[common]
    differing = [c for c in columns if not a[c].equals(b[c])]
    assert not differing, (
        f"features changed when post-issue-time data was corrupted: {differing}. "
        "A lag is reaching past the issue time."
    )


def test_lags_are_measured_from_the_issue_time(market_slice, load_centre_weather):
    """Structural check: `load_lag_Nh` must equal demand N hours before the ISSUE time.

    The behavioural test above proves nothing leaks. This proves the lag means what its
    name says - a lag that was accidentally three times too deep would be leak-free and
    still wrong.
    """
    horizon = 48
    frame = build_demand_features(
        market_slice, load_centre_weather, REGION, horizons=(horizon,)
    )
    truth = market_slice.set_index("valid_time_utc")["demand_mw"]

    sample = frame.dropna(subset=[f"load_lag_{h}h" for h in LOAD_LAG_HOURS]).iloc[len(frame) // 3]
    issue = sample["__issue_time"]

    for lag in LOAD_LAG_HOURS:
        expected = truth.get(issue - pd.Timedelta(hours=lag))
        if expected is None or pd.isna(expected):
            continue
        assert sample[f"load_lag_{lag}h"] == pytest.approx(expected), (
            f"load_lag_{lag}h is not demand {lag}h before the issue time {issue}"
        )


def test_measured_rooftop_pv_is_not_a_feature(market_slice, load_centre_weather):
    """Rooftop PV at the valid time is an actual, not a forecast, and must stay out.

    Operational demand is net of rooftop output, so the two are near-mechanically linked.
    Including the measured value would post an excellent validation score for a model that
    cannot be served, because nobody knows actual rooftop output two days ahead.
    """
    frame = build_demand_features(market_slice, load_centre_weather, REGION, horizons=(24,))
    columns = feature_columns(frame)
    assert "rooftop_pv_mw" not in columns, (
        "measured rooftop PV is being used as a feature; only its lagged value and its "
        "NWP drivers (GHI, cloud) are known at issue time"
    )
    # Its lag is fine and expected to be there.
    assert "rooftop_lag_24h" in columns


def test_target_is_never_among_the_features(market_slice, load_centre_weather):
    frame = build_demand_features(market_slice, load_centre_weather, REGION, horizons=(24,))
    columns = feature_columns(frame)
    assert not any(c.startswith("__") for c in columns)
    assert "demand_mw" not in columns


def test_trained_model_did_not_learn_from_the_future():
    """A trained artifact must not carry a feature that only exists post-issue-time."""
    import json

    from reip.config import get_settings

    path = get_settings().artifacts_dir / "demand_metadata.json"
    if not path.exists():
        pytest.skip("demand model not trained")

    features = set(json.load(path.open(encoding="utf-8"))["feature_order"])
    banned = {"demand_mw", "rooftop_pv_mw", "aemo_demand_forecast_mw", "__target"}
    assert not (features & banned), f"artifact trained on post-issue-time fields: {features & banned}"
