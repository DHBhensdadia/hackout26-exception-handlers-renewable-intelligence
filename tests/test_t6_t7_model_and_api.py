"""T6 - the model must beat its baselines. T7 - the API must honour its contract.

T6 is the test that encodes "the model is actually good". Everything else checks that the
machinery is correct; this checks that the machinery was worth building. If a change makes
the model lose to smart persistence, that is a regression regardless of what the code
looks like.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from reip.schemas import CLEARSKY_INDEX_MAX, MAX_HORIZON_H, SiteForecast, Tech

# Coverage tolerance on the p10-p90 band. Nominal is 80%; anything far below means the
# model is overconfident and the interval is decoration rather than information.
PICP_BOUNDS = (65.0, 95.0)


# --------------------------------------------------------------------- T6 skill


@pytest.mark.parametrize("tech", ["solar", "wind"])
def test_model_beats_smart_persistence(benchmark, tech):
    """The headline claim. Smart persistence is the real reference, not plain persistence."""
    if tech not in benchmark:
        pytest.skip(f"no {tech} results in benchmark.json")

    scores = benchmark[tech]["overall"]
    model = scores["model"]["nmae_pct"]
    reference = scores["smart_persistence"]["nmae_pct"]

    assert model < reference, (
        f"{tech}: model nMAE {model:.2f}% does not beat smart persistence {reference:.2f}%"
    )


@pytest.mark.parametrize("tech", ["solar", "wind"])
def test_model_beats_physics_only(benchmark, tech):
    """The learned correction must add something over the physics it is handed as a feature."""
    if tech not in benchmark:
        pytest.skip(f"no {tech} results in benchmark.json")

    scores = benchmark[tech]["overall"]
    assert scores["model"]["nmae_pct"] < scores["physics_only"]["nmae_pct"], (
        f"{tech}: the ML adds nothing over the physical model it already receives as input"
    )


@pytest.mark.parametrize("tech", ["solar", "wind"])
def test_model_beats_every_baseline(benchmark, tech):
    if tech not in benchmark:
        pytest.skip(f"no {tech} results in benchmark.json")

    scores = benchmark[tech]["overall"]
    model = scores["model"]["nmae_pct"]
    for name in ("persistence", "smart_persistence", "climatology", "physics_only"):
        assert model < scores[name]["nmae_pct"], f"{tech}: loses to {name}"


@pytest.mark.parametrize("tech", ["solar", "wind"])
def test_uncertainty_band_is_calibrated(benchmark, tech):
    """A p10-p90 interval that does not contain the truth ~80% of the time is not a forecast."""
    if tech not in benchmark:
        pytest.skip(f"no {tech} results in benchmark.json")

    picp = benchmark[tech]["overall"]["model"].get("picp_pct")
    assert picp is not None
    lo, hi = PICP_BOUNDS
    assert lo <= picp <= hi, f"{tech}: p10-p90 coverage {picp:.1f}% is outside [{lo}, {hi}]"


@pytest.mark.parametrize("tech", ["solar", "wind"])
def test_bias_is_small(benchmark, tech):
    """A persistent one-directional error is worse for grid operations than symmetric noise."""
    if tech not in benchmark:
        pytest.skip(f"no {tech} results in benchmark.json")

    bias = abs(benchmark[tech]["overall"]["model"]["mbe_pct"])
    assert bias < 5.0, f"{tech}: mean bias {bias:.2f}% of capacity is too large"


# --------------------------------------------------------------------- prediction


def test_prediction_is_monotone_and_bounded(solar_weather, solar_site, artifacts_present):
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    from reip.models.predict import predict_frame

    weather = solar_weather[solar_weather["site_id"] == solar_site.site_id].head(240)
    frame = predict_frame(weather, solar_site)

    assert (frame["p10_mw"] <= frame["p50_mw"] + 1e-9).all(), "p10 crosses above p50"
    assert (frame["p50_mw"] <= frame["p90_mw"] + 1e-9).all(), "p50 crosses above p90"
    assert (frame["p50_mw"] >= 0).all()
    assert (frame["p90_mw"] <= solar_site.capacity_mw + 1e-6).all()

    # Night must be exactly zero, not merely small.
    night = frame["clearsky_mw"] <= 0.0
    if night.any():
        assert float(frame.loc[night, "p90_mw"].max()) == 0.0


def test_cold_start_site_gets_a_forecast(gujarat_solar, fixture_weather_payload, artifacts_present):
    """The multi-site generalisation claim, exercised on a site absent from all training data."""
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    from reip.ingest.openmeteo import _to_canonical
    from reip.models.predict import load_model, predict_site

    assert gujarat_solar.site_id not in load_model(Tech.SOLAR).metadata["sites"]

    issue = pd.Timestamp("2026-09-12T00:00:00Z")
    weather = _to_canonical(
        fixture_weather_payload, site_id=gujarat_solar.site_id, issue_time=issue, source="fixture"
    )
    weather = weather[(weather["horizon_h"] >= 1) & (weather["horizon_h"] <= MAX_HORIZON_H)]

    forecast = predict_site(weather, gujarat_solar, issue_time=issue)

    assert isinstance(forecast, SiteForecast)
    assert len(forecast.points) == MAX_HORIZON_H
    assert max(p.p50_mw for p in forecast.points) > 0, "a 730 MW park forecast to make nothing"
    assert all(p.p50_mw <= gujarat_solar.capacity_mw for p in forecast.points)


# --------------------------------------------------------------------- T7 API contract


@pytest.fixture(scope="module")
def client() -> TestClient:
    from reip.api.main import app

    return TestClient(app)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["models_loaded"]) == {"solar", "wind"}


def test_sites_endpoint_returns_a_flat_list(client):
    """A bare array, which is what the published contract promises."""
    body = client.get("/sites").json()
    assert isinstance(body, list), "/sites must return an array, not an envelope"
    assert len(body) > 0
    required = {"site_id", "name", "tech", "capacity_mw", "latitude", "longitude",
                "region", "in_training_data", "location_is_estimated"}
    assert required <= set(body[0]), f"missing {required - set(body[0])}"


def test_sites_endpoint_marks_training_membership(client, artifacts_present):
    """The flag must reflect the corpus actually trained on, not an id prefix.

    This previously read `site_id.startswith("GEFCOM-")`, and this test asserted that
    behaviour - so when the corpus moved to AEMO, both the endpoint and the test stayed
    consistent with each other and wrong about the world. Every one of the 151 trained
    plants reported itself as never-seen, which understates the cold-start claim rather
    than overstating it, but is wrong either way.

    Checked against the artifact metadata, which is the only thing that actually knows.
    """
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    import json

    from reip.config import get_settings
    from reip.schemas import Tech

    trained = set()
    for tech in Tech:
        path = get_settings().artifacts_dir / f"{tech.value}_metadata.json"
        if path.exists():
            trained.update(json.loads(path.read_text(encoding="utf-8"))["sites"])

    by_id = {s["site_id"]: s for s in client.get("/sites").json()}
    assert trained, "no trained sites recorded in any artifact"
    for site_id in list(trained)[:20]:
        if site_id in by_id:
            assert by_id[site_id]["in_training_data"] is True, f"{site_id} trained but not flagged"

    # The cold-start demo site must never be marked as seen - it is the whole demonstration.
    assert by_id["GJ-SOLAR-CHARANKA"]["in_training_data"] is False


def test_forecast_rejects_underspecified_request(client):
    response = client.post("/forecast", json={"latitude": 23.0})
    assert response.status_code == 422


def test_forecast_rejects_unknown_site(client):
    response = client.post("/forecast", json={"site_id": "NOPE"})
    assert response.status_code == 404


@pytest.mark.network
def test_forecast_contract_for_unseen_coordinates(client, artifacts_present):
    """End to end on a latitude/longitude never seen in training."""
    if not artifacts_present:
        pytest.skip("no trained artifacts")

    response = client.post(
        "/forecast",
        json={
            "latitude": 23.03,
            "longitude": 72.57,
            "tech": "solar",
            "capacity_mw": 50.0,
            "horizon_h": 72,
        },
    )
    assert response.status_code == 200, response.text

    body = response.json()
    parsed = SiteForecast.model_validate(body)  # the contract validates its own response

    assert len(parsed.points) == 72
    assert [p.horizon_h for p in parsed.points] == list(range(1, 73))
    for point in parsed.points:
        assert point.p10_mw <= point.p50_mw <= point.p90_mw
        assert 0 <= point.p90_mw <= 50.0
        # Not `p50 <= clearsky`: cloud enhancement is a real effect, and the design
        # deliberately allows the clear-sky index up to CLEARSKY_INDEX_MAX. The bound
        # that actually holds is that ceiling, plus a small absolute tolerance for the
        # sunrise/sunset hours where the reference itself is near zero.
        assert point.p90_mw <= CLEARSKY_INDEX_MAX * point.clearsky_mw + 0.01 * 50.0

    # Across the day as a whole the forecast must sit below the clear-sky envelope;
    # a model routinely predicting above theoretical maximum would be miscalibrated.
    total_p50 = sum(p.p50_mw for p in parsed.points)
    total_clearsky = sum(p.clearsky_mw for p in parsed.points)
    assert total_p50 <= total_clearsky, "daily energy forecast exceeds the clear-sky envelope"
