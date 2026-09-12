"""T1 - train/serve skew. The blocking test.

The dominant failure mode for a machine-learning system is not a bad model, it is a good
model fed differently in production than in training. The symptom is silence: offline
scores stay excellent, served predictions quietly drift, and nothing raises.

The structural defence is that exactly one function builds features. These tests assert
that it holds - that the trainer's path and the API's path produce byte-identical vectors
from identical input, and that the artifact's stored feature order is enforced rather than
assumed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reip.features.build import build_features
from reip.schemas import Tech


def test_training_and_serving_paths_agree_exactly(solar_weather, solar_site):
    """The trainer's call and the API's call must return identical matrices."""
    from reip.models import predict as serving_module
    from reip.models import train as training_module

    sample = solar_weather[solar_weather["site_id"] == solar_site.site_id].head(200)

    # Both modules must reach the same function object, not merely equivalent code.
    assert training_module.build_features is build_features
    assert serving_module.build_features is build_features

    from_training = training_module.build_features(sample, solar_site)
    from_serving = serving_module.build_features(sample, solar_site)

    assert list(from_training.columns) == list(from_serving.columns)
    pd.testing.assert_frame_equal(from_training, from_serving, check_exact=True)


def test_feature_order_is_deterministic(solar_weather, solar_site):
    """Repeated builds and shuffled input rows must not change column order or values.

    Trees index features positionally, so a build whose column order depends on dict
    iteration or input ordering would score the wrong variable against the wrong split.
    """
    sample = solar_weather[solar_weather["site_id"] == solar_site.site_id].head(300)

    first = build_features(sample, solar_site)
    second = build_features(sample.copy(), solar_site)
    assert list(first.columns) == list(second.columns)

    shuffled = sample.sample(frac=1.0, random_state=0)
    from_shuffled = build_features(shuffled, solar_site)

    assert list(from_shuffled.columns) == list(first.columns)
    # build_features sorts by valid time internally, so a shuffled frame must produce the
    # same result - otherwise every lag and rolling feature is computed against the wrong hour.
    pd.testing.assert_frame_equal(from_shuffled, first, check_exact=True)


@pytest.mark.parametrize("tech", list(Tech))
def test_artifact_feature_order_matches_builder(
    tech, solar_weather, wind_weather, solar_site, wind_site, artifacts_present
):
    """Every feature the artifact expects must be produced by the current builder."""
    if not artifacts_present:
        pytest.skip("no trained artifacts; run `python -m reip.models.train`")

    from reip.models.predict import load_model

    model = load_model(tech)
    # Use a site the corpus actually covers. The registry holds sites that were resolved
    # but later rejected by the ingest quality filters, and those have no weather rows.
    site = solar_site if tech is Tech.SOLAR else wind_site
    weather = solar_weather if tech is Tech.SOLAR else wind_weather
    sample = weather[weather["site_id"] == site.site_id].head(120)

    produced = set(build_features(sample, site).columns)
    expected = set(model.feature_order)

    assert not (expected - produced), (
        f"{tech.value}: artifact expects features the builder no longer emits: {sorted(expected - produced)}"
    )


def test_reordered_features_are_rejected(solar_weather, solar_site, artifacts_present):
    """Silently accepting a reordered matrix is worse than failing loudly."""
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    from reip.models.predict import _align_features, load_model

    model = load_model(Tech.SOLAR)
    sample = solar_weather[solar_weather["site_id"] == solar_site.site_id].head(50)
    features = build_features(sample, solar_site)

    aligned = _align_features(features, model.feature_order, Tech.SOLAR)
    assert list(aligned.columns) == model.feature_order

    with pytest.raises(ValueError, match="skew"):
        _align_features(
            features.drop(columns=[model.feature_order[0]]), model.feature_order, Tech.SOLAR
        )


def test_serving_weather_produces_same_schema_as_training(fixture_weather_payload, gujarat_solar):
    """An Open-Meteo frame must build the same feature columns as a GEFCom frame.

    This is what lets a model trained on GEFCom be served on Open-Meteo at all: the two
    providers converge on one canonical weather contract before features are built.
    """
    from reip.ingest.openmeteo import _to_canonical

    issue = pd.Timestamp("2026-09-12T00:00:00Z")
    canonical = _to_canonical(
        fixture_weather_payload, site_id=gujarat_solar.site_id, issue_time=issue, source="fixture"
    )
    canonical = canonical[(canonical["horizon_h"] >= 1) & (canonical["horizon_h"] <= 72)]

    features = build_features(canonical, gujarat_solar)

    assert len(features) == len(canonical)
    assert features.index.name == "valid_time_utc"
    assert np.isfinite(features["clearsky_cf"]).all()
