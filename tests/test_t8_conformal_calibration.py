"""T8 - the calibrated interval must be the one that is actually served.

This test exists because it was not true. `train.py` fitted the conformal widening, wrote
it into the artifact metadata, reported the calibrated coverage - and `predict.py` never
read it back. Every forecast the API returned carried the *raw* interval while the
benchmark quoted the calibrated one. On wind that was a 70.5% interval labelled 80%.

The gap was invisible from either side. Training reported an honest number for a
correction it had applied; serving applied no correction and reported nothing. Only
comparing the two revealed it, so that comparison is what this test automates.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from reip.models.predict import load_model, predict_frame
from reip.models.splits import widening_for
from reip.schemas import Tech, lead_bucket

# The widening is in target units (capacity factor), so the MW effect scales with plant
# size. A tolerance below this would fail on rounding; above it would let a dropped
# correction pass on a small plant.
REL_TOL = 0.02


def _uncalibrated(model):
    """The same model with its widening zeroed - what serving used to do."""
    return dataclasses.replace(model, metadata={**model.metadata, "conformal_widening": 0.0})


@pytest.fixture(scope="module")
def wind_slice(wind_weather, registry):
    """One site's weather, enough hours to exercise every lead bucket."""
    site_id = wind_weather["site_id"].iloc[0]
    frame = wind_weather[wind_weather["site_id"] == site_id].sort_values("valid_time_utc")
    if len(frame) < 200:
        pytest.skip("not enough wind weather rows for a meaningful comparison")
    return registry.get(site_id), frame.head(500).reset_index(drop=True)


def test_widening_is_applied_at_serve_time(wind_slice, artifacts_present):
    """Serving with the stored widening must differ from serving without it."""
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    site, weather = wind_slice
    model = load_model(Tech.WIND)
    stored = model.metadata.get("conformal_widening", 0.0)

    calibrated = predict_frame(weather, site, model=model)
    raw = predict_frame(weather, site, model=_uncalibrated(model))

    width_cal = (calibrated["p90_mw"] - calibrated["p10_mw"]).mean()
    width_raw = (raw["p90_mw"] - raw["p10_mw"]).mean()

    # Wind's widening is positive - the raw interval was too narrow - so the calibrated
    # band must come out strictly wider. A zero difference means predict.py has stopped
    # reading the metadata again, which is the original bug.
    assert width_cal > width_raw, (
        f"calibrated band ({width_cal:.4f} MW) is not wider than the raw band "
        f"({width_raw:.4f} MW); the stored widening {stored} was not applied"
    )

    # And by roughly the right amount: two widenings (one each side) times capacity.
    expected = 2 * np.mean(widening_for(stored, weather["horizon_h"].to_numpy())) * site.capacity_mw
    assert width_cal - width_raw == pytest.approx(expected, rel=0.25), (
        f"band grew by {width_cal - width_raw:.4f} MW, expected about {expected:.4f} MW"
    )


@pytest.mark.parametrize("tech", [Tech.SOLAR, Tech.WIND])
def test_median_stays_bracketed_after_widening(tech, wind_slice, solar_weather, registry,
                                               artifacts_present):
    """p10 <= p50 <= p90 must survive the correction, including when it tightens.

    Solar's widening is negative: the raw interval was too wide, so CQR narrows it. A
    narrowing interval can close past the median from either side, and `apply_conformal`
    cannot notice because it is never shown p50. That produced real quantile crossings.
    """
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    if tech is Tech.WIND:
        site, weather = wind_slice
    else:
        site_id = solar_weather["site_id"].iloc[0]
        weather = (
            solar_weather[solar_weather["site_id"] == site_id]
            .sort_values("valid_time_utc")
            .head(500)
            .reset_index(drop=True)
        )
        site = registry.get(site_id)

    frame = predict_frame(weather, site, model=load_model(tech))
    assert (frame["p10_mw"] <= frame["p50_mw"] + 1e-9).all(), "p10 crossed above p50"
    assert (frame["p50_mw"] <= frame["p90_mw"] + 1e-9).all(), "p50 crossed above p90"


@pytest.mark.parametrize("tech", [Tech.SOLAR, Tech.WIND])
def test_reported_coverage_is_the_calibrated_one(tech, artifacts_present):
    """Metadata must not quote a calibrated figure the serving path cannot reproduce.

    A guard on provenance rather than on numbers: if `conformal_widening` is absent or
    zero while `coverage` claims a calibration happened, the two halves have drifted apart
    again.
    """
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    meta = load_model(tech).metadata
    coverage = meta["coverage"]
    assert "conformal_widening" in meta, "artifact reports coverage but stores no widening"

    calibrated_differs = abs(coverage["test_calibrated"] - coverage["test_raw"]) > 1e-6
    widening = meta["conformal_widening"]
    nonzero = any(abs(v) > 1e-9 for v in widening.values()) if isinstance(widening, dict) else abs(widening) > 1e-9
    assert calibrated_differs == nonzero, (
        "calibrated and raw coverage differ but the stored widening is zero (or vice "
        "versa) - the metadata and the correction disagree"
    )


def test_per_bucket_widening_selects_by_horizon():
    """Each row must take its own bucket's widening, not a pooled one."""
    widenings = {"all": 0.02, "1-24h": 0.01, "25-48h": 0.03, "49-72h": 0.05}
    horizons = np.array([1, 24, 25, 48, 49, 72])
    got = widening_for(widenings, horizons)
    assert list(got) == [0.01, 0.01, 0.03, 0.03, 0.05, 0.05]

    # A bucket with too few calibration rows is absent and must fall back to pooled.
    assert list(widening_for({"all": 0.02, "1-24h": 0.01}, horizons)) == [
        0.01, 0.01, 0.02, 0.02, 0.02, 0.02
    ]

    # A bare float is what pre-bucket artifacts store; they must keep working.
    assert list(widening_for(0.03, horizons)) == [0.03] * 6


def test_lead_buckets_partition_the_horizon():
    """Every servable horizon must land in exactly one bucket."""
    labels = {lead_bucket(h) for h in range(1, 73)}
    assert "out-of-range" not in labels
    assert labels == {"1-24h", "25-48h", "49-72h"}
