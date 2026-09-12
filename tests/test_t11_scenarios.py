"""T11 - regional scenarios must be coherent, and calibrated against outcomes.

Most of these assert properties that were violated at some point while building the module,
which is the only reason to trust them as tests rather than as decoration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reip.portfolio import residuals as residual_store
from reip.portfolio.aggregate import generate_from_arrays
from reip.schemas import Tech

N_SCENARIOS = 60
HOURS = 24
SITES = 5


@pytest.fixture
def synthetic_store() -> pd.DataFrame:
    """A residual field with a known, deliberately partial correlation."""
    rng = np.random.default_rng(0)
    index = pd.date_range("2025-01-01", periods=600, freq="h", tz="UTC")
    common = rng.standard_normal((len(index), 1))
    values = 0.05 * (0.7 * common + 0.7 * rng.standard_normal((len(index), SITES)))
    return pd.DataFrame(values, index=index, columns=[f"S{i}" for i in range(SITES)])


def _generate(store: pd.DataFrame, *, dispersion: float = 1.0, capacity: float = 100.0):
    sites = list(store.columns)
    p50 = np.full((HOURS, len(sites)), capacity * 0.5)
    return generate_from_arrays(
        p10=p50 - 10,
        p50=p50,
        p90=p50 + 10,
        capacities=np.full(len(sites), capacity),
        site_ids=sites,
        valid_times=pd.date_range("2026-06-01", periods=HOURS, freq="h", tz="UTC"),
        horizons=np.full(HOURS, 24, dtype="int16"),
        tech=Tech.SOLAR,
        n_scenarios=N_SCENARIOS,
        seed=1,
        store=store,
        dispersion=dispersion,
    )


def test_shape_and_regional_total(synthetic_store):
    scenarios = _generate(synthetic_store)
    assert scenarios.values.shape == (N_SCENARIOS, HOURS, SITES)
    np.testing.assert_allclose(
        scenarios.regional_total(), scenarios.values.sum(axis=2), rtol=0, atol=0
    )


def test_dependence_lies_between_the_two_wrong_assumptions(synthetic_store):
    """The whole point: neither independent nor perfectly correlated.

    If the regional spread matched the independent bound, the joint structure was lost. If
    it matched the perfectly-correlated bound, the ensemble is no better than summing
    quantiles.
    """
    scenarios = _generate(synthetic_store)
    per_site_sd = scenarios.values.std(axis=0).mean(axis=0)
    regional_sd = scenarios.regional_total().std(axis=0).mean()

    independent = float(np.sqrt((per_site_sd**2).sum()))
    perfect = float(per_site_sd.sum())

    assert independent < regional_sd < perfect, (
        f"regional sd {regional_sd:.3f} is outside ({independent:.3f}, {perfect:.3f}); "
        "the dependence structure was not reproduced"
    )


def test_scenarios_respect_physical_bounds(synthetic_store):
    scenarios = _generate(synthetic_store, dispersion=5.0, capacity=100.0)
    assert scenarios.values.min() >= 0.0, "a scenario went negative"
    assert scenarios.values.max() <= 100.0 + 1e-9, "a scenario exceeded nameplate"


def test_dispersion_scales_the_spread(synthetic_store):
    """The calibration knob must actually widen the ensemble, monotonically."""
    narrow = _generate(synthetic_store, dispersion=1.0).regional_total().std(axis=0).mean()
    wide = _generate(synthetic_store, dispersion=2.0).regional_total().std(axis=0).mean()
    assert wide > narrow * 1.5, f"dispersion 2.0 gave sd {wide:.2f} against {narrow:.2f} at 1.0"


def test_quantiles_are_ordered(synthetic_store):
    frame = _generate(synthetic_store).quantiles()
    assert (frame["p10_mw"] <= frame["p50_mw"]).all()
    assert (frame["p50_mw"] <= frame["p90_mw"]).all()


# ------------------------------------------------------------- template blocks


def test_blocks_are_aligned_to_the_hour_of_day(synthetic_store):
    """Diurnal alignment. Not cosmetic - it moved solar coverage from 71% to 87%.

    A residual field is strongly diurnal: identically zero at night, largest near noon. A
    block starting at 03:00 laid over a window starting at 12:00 puts night-time zeros on
    the midday hours, and the regional band comes out far too narrow while every scenario
    still looks like a plausible day.
    """
    for hour in (0, 6, 13):
        blocks, _ = residual_store.template_blocks(
            synthetic_store, list(synthetic_store.columns), HOURS, start_hour=hour
        )
        assert len(blocks) > 0

    unaligned, _ = residual_store.template_blocks(
        synthetic_store, list(synthetic_store.columns), HOURS
    )
    aligned, _ = residual_store.template_blocks(
        synthetic_store, list(synthetic_store.columns), HOURS, start_hour=0
    )
    # One start hour in 24 should survive the filter, give or take edge effects.
    assert len(aligned) < len(unaligned) / 10


def test_contiguity_check_is_resolution_independent():
    """A DatetimeIndex reports int64 in whatever unit it carries.

    Comparing raw int64 against a hardcoded nanosecond constant matched nothing on a
    microsecond-resolution index, so every window looked discontiguous and no template
    could be built at all. The comparison is on timedeltas for that reason.
    """
    columns = [f"S{i}" for i in range(SITES)]
    for unit in ("ns", "us"):
        index = pd.date_range("2025-01-01", periods=200, freq="h", tz="UTC").as_unit(unit)
        store = pd.DataFrame(np.zeros((len(index), SITES)) + 0.01, index=index, columns=columns)
        blocks, _ = residual_store.template_blocks(store, columns, HOURS)
        assert len(blocks) > 0, f"no blocks found on a {unit}-resolution index"


def test_gaps_are_never_spliced():
    """A window spanning a missing hour would fabricate a jump in the error field."""
    columns = [f"S{i}" for i in range(SITES)]
    index = pd.date_range("2025-01-01", periods=200, freq="h", tz="UTC")
    index = index.delete(range(50, 60))  # punch a ten-hour hole
    store = pd.DataFrame(
        np.full((len(index), SITES), 0.01), index=index, columns=columns
    )
    blocks, _ = residual_store.template_blocks(store, columns, HOURS)

    # Only windows entirely before or entirely after the hole are usable.
    assert 0 < len(blocks) <= len(index) - HOURS


def test_unknown_sites_get_no_invented_spread(synthetic_store):
    """A site with no history is carried at p50, not given fabricated uncertainty."""
    sites = [*synthetic_store.columns, "BRAND-NEW"]
    p50 = np.full((HOURS, len(sites)), 50.0)
    scenarios = generate_from_arrays(
        p10=p50 - 10,
        p50=p50,
        p90=p50 + 10,
        capacities=np.full(len(sites), 100.0),
        site_ids=sites,
        valid_times=pd.date_range("2026-06-01", periods=HOURS, freq="h", tz="UTC"),
        horizons=np.full(HOURS, 24, dtype="int16"),
        tech=Tech.SOLAR,
        n_scenarios=N_SCENARIOS,
        seed=1,
        store=synthetic_store,
    )
    unknown = scenarios.values[:, :, sites.index("BRAND-NEW")]
    assert np.allclose(unknown, 50.0), "an unknown site was given invented spread"


# ------------------------------------------------------------- measured outcome


def test_regional_calibration_was_verified(artifacts_present):
    """The verification report must exist and must beat the naive sum on width.

    Coverage bounds are wide on purpose: this guards against the regime failures seen
    during development - 28% coverage from a broken tail model, 99% from summing quantiles -
    not against a few points of drift.
    """
    import json

    from reip.config import get_settings

    path = get_settings().reports_dir / "scenario_verification.json"
    if not path.exists():
        pytest.skip("scenario_verification.json absent; run `python -m reip.eval.scenarios`")

    results = json.loads(path.read_text(encoding="utf-8"))
    assert results, "verification produced no results"

    for entry in results:
        label = f"{entry['tech']} {entry['region']}"
        copula = entry["copula"]["coverage"]
        naive = entry["naive_quantile_sum"]
        assert 0.60 <= copula <= 0.95, f"{label}: regional coverage {copula:.1%} is far off 80%"
        assert naive["mean_width_mw"] > entry["copula"]["mean_width_mw"], (
            f"{label}: the naive quantile sum is not wider than the ensemble, so the "
            "aggregation is not doing anything"
        )
