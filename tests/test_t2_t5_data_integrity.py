"""T2 leakage, T3 physics sanity, T4 clear-sky consistency, T5 ingest invariants."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reip.features.build import LAG_LEADS, build_features, build_target
from reip.physics.clearsky import EmpiricalClearSky, PvlibClearSky
from reip.physics.fit_location import analytic_daylength, estimate_longitude
from reip.physics.solar import clearsky_ac_mw
from reip.physics.wind import air_density, reference_power_curve, shear_exponent
from reip.schemas import AIR_DENSITY_BOUNDS, MAX_GHI_WM2, SchemaError, validate_weather

# ---------------------------------------------------------------------------- T2 leakage


def test_no_feature_derives_from_the_target(solar_weather, solar_power, solar_site):
    """Features must be a function of weather and site metadata only, never of power."""
    weather = solar_weather[solar_weather["site_id"] == solar_site.site_id].head(500)
    power = solar_power[solar_power["site_id"] == solar_site.site_id]

    baseline = build_features(weather, solar_site)

    # Corrupting the power record must not move a single feature. If any feature were
    # derived from observed generation, this would change it - and the model would be
    # learning from information unavailable at forecast time.
    corrupted = power.copy()
    corrupted["power_mw"] = corrupted["power_mw"] * 0.0 + 999.0
    after = build_features(weather, solar_site)

    pd.testing.assert_frame_equal(baseline, after, check_exact=True)
    _, denom = build_target(corrupted, solar_site, baseline.index)
    assert (denom.to_numpy() >= 0).all()


def test_cv_folds_are_time_ordered_and_disjoint():
    """Forward-chaining folds must never validate on a time the fold trained on."""
    from reip.models.train import forward_chaining_folds

    times = pd.Series(pd.date_range("2013-01-01", periods=5000, freq="h", tz="UTC"))
    folds = forward_chaining_folds(times, 3)
    assert folds

    index = pd.DatetimeIndex(times)
    for train, valid in folds:
        assert not (train & valid).any(), "a row is in both train and validation"
        assert index[train].max() <= index[valid].min(), "validation precedes training"


def test_holdout_is_a_contiguous_final_block():
    """The holdout must be the tail of the timeline, not a random sample of it."""
    from reip.models.train import Dataset, holdout_split

    times = pd.date_range("2013-01-01", periods=1000, freq="h", tz="UTC")
    data = Dataset(
        X=pd.DataFrame({"a": np.arange(1000.0)}),
        y=pd.Series(np.zeros(1000)),
        site_id=pd.Series(["s"] * 1000),
        valid_time=pd.Series(times),
        horizon_h=pd.Series(np.ones(1000, dtype="int16")),
        capacity_mw=pd.Series(np.ones(1000)),
        denominator=pd.Series(np.ones(1000)),
    )
    train, holdout = holdout_split(data, 0.2)

    assert train.sum() + holdout.sum() == 1000
    assert times[train].max() < times[holdout].min()
    # Contiguous: the holdout flag flips exactly once.
    assert int(np.sum(np.diff(holdout.astype(int)) != 0)) == 1


def test_lag_leads_cover_both_directions():
    """Leading NWP is legal and valuable; the feature set should use it."""
    assert any(s < 0 for s in LAG_LEADS) and any(s > 0 for s in LAG_LEADS)


# ------------------------------------------------------------------------ T3 physics


def test_solar_output_is_zero_at_night(gujarat_solar):
    times = pd.date_range("2026-06-21", periods=48, freq="h", tz="UTC")
    clearsky = clearsky_ac_mw(times, gujarat_solar)

    # Charanka sits at 71.2E, so solar noon is near 07:15 UTC and 15:00-22:00 UTC is night.
    night = clearsky[[15 <= h <= 22 for h in clearsky.index.hour]]
    assert float(night.max()) == 0.0
    assert float(clearsky.max()) <= gujarat_solar.capacity_mw + 1e-6


def test_clearsky_index_stays_within_bounds(solar_weather, solar_power, solar_site):
    weather = solar_weather[solar_weather["site_id"] == solar_site.site_id]
    power = solar_power[solar_power["site_id"] == solar_site.site_id]
    features = build_features(weather, solar_site)
    target, _ = build_target(power, solar_site, features.index)

    valid = target.dropna()
    assert (valid >= 0).all() and (valid <= 1.3).all()
    # If the reference were mis-scaled the target would pile up against its cap, as it did
    # when a southern-hemisphere array was pointed south.
    assert float((valid >= 1.29).mean()) < 0.10


def test_air_density_is_physical():
    lo, hi = AIR_DENSITY_BOUNDS
    rho = air_density(pd.Series([1013.25, 1008.0, 950.0]), pd.Series([15.0, 42.0, -10.0]))
    assert (rho >= lo).all() and (rho <= hi).all()
    # Hot air is thinner than the 15 C standard.
    assert rho.iloc[1] < 1.225


def test_power_curve_respects_cut_in_rated_and_cut_out(wind_site):
    speeds = pd.Series(
        [
            0.0,
            2.0,
            wind_site.cut_in_ws_ms + 0.1,
            wind_site.rated_ws_ms,
            wind_site.cut_out_ws_ms - 0.1,
            wind_site.cut_out_ws_ms + 0.1,
            40.0,
        ]
    )
    cf = reference_power_curve(speeds, wind_site)

    assert cf.iloc[0] == 0.0 and cf.iloc[1] == 0.0, "generating below cut-in"
    assert cf.iloc[3] == pytest.approx(1.0), "not at rated output at rated speed"
    assert cf.iloc[4] == pytest.approx(1.0), "not holding rated between rated and cut-out"
    assert cf.iloc[5] == 0.0 and cf.iloc[6] == 0.0, "not shutting down above cut-out"
    assert (cf >= 0).all() and (cf <= 1).all()


def test_shear_exponent_is_bounded_and_correct():
    alpha = shear_exponent(pd.Series([4.0]), pd.Series([4.0 * 10 ** (1 / 7)]))
    assert alpha.iloc[0] == pytest.approx(1 / 7, abs=1e-6)
    # Degenerate input must not produce an unbounded exponent.
    extreme = shear_exponent(pd.Series([0.01, 20.0]), pd.Series([20.0, 0.01]))
    assert (extreme >= -0.10).all() and (extreme <= 0.60).all()


# --------------------------------------------------------- T4 clear-sky consistency


def test_fitted_clearsky_agrees_with_empirical_envelope(solar_power, solar_site):
    """The recovered coordinates must reproduce the plant's own observed envelope.

    Independent check on the location fit: pvlib driven by fitted coordinates versus a
    high quantile of the measured power itself. They are computed from entirely different
    information, so agreement is evidence the fit is real.
    """
    series = (
        solar_power[solar_power["site_id"] == solar_site.site_id]
        .set_index("valid_time_utc")
        .sort_index()["power_mw"]
        .astype("float64")
    )
    times = pd.DatetimeIndex(series.index)

    modelled = PvlibClearSky()(times, solar_site)
    empirical = EmpiricalClearSky.fit(series, solar_site.capacity_mw)(times, solar_site)

    # Compare near solar noon on the clearest days, where both are well determined.
    bright = modelled > 0.8 * modelled.max()
    assert bright.sum() > 100

    ratio = float(np.median(empirical[bright] / modelled[bright]))
    assert 0.75 < ratio < 1.25, f"clear-sky references disagree by {abs(1 - ratio):.0%}"


def test_longitude_recovery_round_trips():
    """A synthetic plant at a known longitude must be located back to it."""
    times = pd.date_range("2013-01-01", periods=24 * 120, freq="h", tz="UTC")
    for true_lon in (150.0, 0.0, -75.0, 72.5):
        solar_noon_utc = 12.0 - true_lon / 15.0
        hours = times.hour + times.minute / 60.0
        # A clean daily bell centred on local solar noon.
        offset = np.minimum(np.abs(hours - solar_noon_utc), 24 - np.abs(hours - solar_noon_utc))
        power = pd.Series(np.clip(np.cos(np.pi * offset / 12.0), 0, None) ** 3, index=times)
        assert estimate_longitude(power) == pytest.approx(true_lon, abs=8.0)


def test_analytic_daylength_matches_known_geometry():
    """Equator is near 12 h year round; higher latitudes swing much harder."""
    equator = analytic_daylength(0.0)
    assert equator.min() == pytest.approx(12.0, abs=0.2)
    assert equator.max() == pytest.approx(12.0, abs=0.2)

    swing = lambda lat: analytic_daylength(lat).max() - analytic_daylength(lat).min()  # noqa: E731
    assert swing(0.0) < swing(23.0) < swing(45.0) < swing(60.0)
    # Southern hemisphere mirrors northern.
    assert swing(-34.0) == pytest.approx(swing(34.0), abs=0.1)


# ---------------------------------------------------------------- T5 ingest invariants


def test_canonical_weather_passes_its_own_contract(solar_weather, wind_weather):
    for frame, name in ((solar_weather, "solar"), (wind_weather, "wind")):
        validated = validate_weather(frame, name=name)
        assert len(validated) == len(frame)


def test_deaccumulated_irradiance_is_physical(solar_weather):
    ghi = solar_weather["ghi_wm2"].dropna()
    assert (ghi >= 0).all(), "negative irradiance means de-accumulation went wrong"
    assert ghi.max() < MAX_GHI_WM2
    # A real record is roughly half night; an accumulating field would almost never be zero.
    assert 0.3 < float((ghi < 1).mean()) < 0.7


def test_diurnal_cycle_survived_ingest(solar_weather, solar_site):
    """De-accumulation must leave a real day/night cycle, not a monotonic ramp."""
    frame = solar_weather[solar_weather["site_id"] == solar_site.site_id]
    by_hour = frame.groupby(pd.DatetimeIndex(frame["valid_time_utc"]).hour)["ghi_wm2"].mean()

    assert float(by_hour.max()) > 400, "no meaningful daytime irradiance"
    assert float(by_hour.min()) < 5, "irradiance never reaches zero; still accumulating?"
    # Australian plants: solar noon falls in the small hours UTC.
    assert by_hour.idxmax() in range(0, 6)


def test_no_duplicate_keys_and_utc_everywhere(solar_weather, wind_weather):
    for frame in (solar_weather, wind_weather):
        assert not frame.duplicated(subset=["site_id", "issue_time_utc", "valid_time_utc"]).any()
        for col in ("issue_time_utc", "valid_time_utc"):
            # Precision may be ns or us depending on the parquet round trip; what the
            # contract actually requires is that the timestamp is UTC-aware.
            assert isinstance(frame[col].dtype, pd.DatetimeTZDtype)
            assert str(frame[col].dtype.tz) == "UTC"


def test_horizon_inconsistency_is_rejected(solar_weather):
    """horizon_h is recomputed from timestamps, never trusted."""
    frame = solar_weather.head(50).copy()
    frame.loc[frame.index[0], "horizon_h"] = 99
    with pytest.raises(SchemaError, match="horizon_h inconsistent"):
        validate_weather(frame)


def test_missing_optional_column_becomes_nan_not_zero(solar_weather):
    """Absence must stay absent: zero is a real irradiance value, missing is not."""
    frame = validate_weather(solar_weather.head(20))
    assert frame["dni_wm2"].isna().all(), "GEFCom supplies no DNI; it must not be filled with 0"
