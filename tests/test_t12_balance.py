"""T12 - the balance must be arithmetically sound and its probabilities reliable."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from reip.balance import calibration
from reip.balance import residual as balance
from reip.config import get_settings
from reip.portfolio.aggregate import ScenarioSet
from reip.schemas import Tech

HOURS = 12
SITES = 3
SCENARIOS = 50


def _scenarios(values_mw: float, spread: float = 0.0) -> ScenarioSet:
    rng = np.random.default_rng(0)
    values = values_mw + spread * rng.standard_normal((SCENARIOS, HOURS, SITES))
    times = pd.date_range("2026-06-01", periods=HOURS, freq="h", tz="UTC")
    return ScenarioSet(
        values=np.clip(values, 0.0, None),
        site_ids=[f"S{i}" for i in range(SITES)],
        valid_times=times,
        horizons=np.full(HOURS, 24, dtype="int16"),
        block_starts=pd.DatetimeIndex([times[0]] * SCENARIOS),
    )


def _compute(demand_mw: float, gen_mw: float, headroom: float, spread: float = 0.0):
    times = pd.date_range("2026-06-01", periods=HOURS, freq="h", tz="UTC")
    return balance.compute(
        region="TEST",
        generation={Tech.SOLAR: _scenarios(gen_mw / SITES, spread)},
        demand_p50_mw=np.full(HOURS, demand_mw),
        demand_peak_mw=demand_mw,
        valid_times=times,
        horizons=np.full(HOURS, 24, dtype="int16"),
        block_starts=pd.DatetimeIndex([times[0]] * SCENARIOS),
        headroom_mw=headroom,
        demand_store=pd.DataFrame(index=pd.DatetimeIndex([]), columns=["TEST"], dtype="float64"),
        calibrate=False,
    )


def test_surplus_when_generation_exceeds_demand():
    result = _compute(demand_mw=100.0, gen_mw=300.0, headroom=50.0)
    assert (result.frame["p_surplus"] == 1.0).all()
    assert (result.frame["p_shortage"] == 0.0).all()
    np.testing.assert_allclose(result.frame["expected_surplus_mw"], 200.0, rtol=1e-6)


def test_shortage_when_residual_exceeds_headroom():
    result = _compute(demand_mw=1000.0, gen_mw=100.0, headroom=50.0)
    assert (result.frame["p_shortage"] == 1.0).all()
    assert (result.frame["p_surplus"] == 0.0).all()
    # residual 900, headroom 50 -> 850 MW uncovered
    np.testing.assert_allclose(result.frame["expected_shortage_mw"], 850.0, rtol=1e-6)


def test_neither_when_residual_sits_inside_headroom():
    result = _compute(demand_mw=500.0, gen_mw=400.0, headroom=300.0)
    assert (result.frame["p_surplus"] == 0.0).all()
    assert (result.frame["p_shortage"] == 0.0).all()
    assert (result.frame["recommended_action"] == "normal").all()


def test_probabilities_are_bounded_and_quantiles_ordered():
    result = _compute(demand_mw=500.0, gen_mw=450.0, headroom=100.0, spread=80.0)
    for column in ("p_surplus", "p_shortage"):
        assert result.frame[column].between(0.0, 1.0).all()
    assert (result.frame["residual_p10_mw"] <= result.frame["residual_p50_mw"]).all()
    assert (result.frame["residual_p50_mw"] <= result.frame["residual_p90_mw"]).all()


def test_expected_magnitudes_are_unconditional():
    """Expectation over ALL scenarios, not only those where the event occurs.

    Conditioning would make a 5%-likely 900 MW shortage read like a 900 MW shortage, and the
    number would no longer sum into energy.
    """
    result = _compute(demand_mw=500.0, gen_mw=500.0, headroom=0.0, spread=200.0)
    row = result.frame.iloc[0]
    assert 0.0 < row["p_shortage"] < 1.0, "test needs a genuinely uncertain hour"
    # Unconditional mean must be strictly below the conditional one.
    assert row["expected_shortage_mw"] < row["residual_p90_mw"]


def test_block_starts_are_required():
    """Without shared blocks the demand draw cannot be aligned to generation."""
    times = pd.date_range("2026-06-01", periods=HOURS, freq="h", tz="UTC")
    with pytest.raises(ValueError, match="block_starts"):
        balance.compute(
            region="TEST",
            generation={Tech.SOLAR: _scenarios(100.0)},
            demand_p50_mw=np.full(HOURS, 100.0),
            demand_peak_mw=100.0,
            valid_times=times,
            horizons=np.full(HOURS, 24, dtype="int16"),
            block_starts=None,
            headroom_mw=0.0,
        )


def test_event_runs_ignore_single_hour_blips():
    frame = pd.DataFrame(
        {
            "valid_time_utc": pd.date_range("2026-06-01", periods=8, freq="h", tz="UTC"),
            "p_surplus": [0.0, 0.9, 0.0, 0.9, 0.9, 0.9, 0.0, 0.0],
            "expected_surplus_mwh": [0.0, 10.0, 0.0, 20.0, 20.0, 20.0, 0.0, 0.0],
        }
    )
    runs = balance.event_runs(frame, "p_surplus")
    assert len(runs) == 1, "a one-hour blip was reported as an event"
    assert runs[0]["hours"] == 3
    assert runs[0]["energy_mwh"] == pytest.approx(60.0)


# ------------------------------------------------------------------- calibration


def test_calibration_map_is_monotone_and_spans_the_range():
    rng = np.random.default_rng(0)
    probabilities = rng.uniform(0, 1, 2000)
    # Under-confident: the event happens far more often than predicted.
    outcomes = (rng.uniform(0, 1, 2000) < np.clip(probabilities * 2, 0, 1)).astype("float64")
    mapping = calibration.fit(probabilities, outcomes)

    y = np.array(mapping["y"])
    assert (np.diff(y) >= -1e-9).all(), "calibration map is not monotone"
    assert y[0] == 0.0 and y[-1] == 1.0, "map cannot reach certainty at either end"
    # It must actually raise the mid-range, which is the under-confidence being corrected.
    assert calibration.apply(np.array([0.3]), mapping)[0] > 0.35


def test_calibration_is_identity_without_enough_data():
    mapping = calibration.fit(np.linspace(0, 1, 10), np.zeros(10))
    np.testing.assert_allclose(
        calibration.apply(np.array([0.0, 0.4, 1.0]), mapping), [0.0, 0.4, 1.0]
    )


def test_apply_without_a_mapping_is_a_passthrough():
    values = np.array([0.1, 0.5, 0.9])
    np.testing.assert_allclose(calibration.apply(values, None), values)


# -------------------------------------------------------------- measured outcome


def test_balance_probabilities_beat_climatology():
    """The verification report must exist and show skill over the base rate."""
    path = get_settings().reports_dir / "balance_verification.json"
    if not path.exists():
        pytest.skip("balance_verification.json absent; run `python -m reip.eval.balance`")

    results = json.loads(path.read_text(encoding="utf-8"))
    assert results, "balance verification produced no results"

    for entry in results:
        for event in ("surplus", "shortage"):
            skill = entry[event]["skill_vs_climatology"]
            if skill is None:
                # Never occurred in the scored window; skill against it is undefined.
                assert entry[event]["base_rate"] == 0.0
                continue
            assert skill > 0.0, (
                f"{entry['region']} {event}: Brier skill {skill:+.1%} does not beat "
                "climatology, so the probabilities carry no information"
            )
